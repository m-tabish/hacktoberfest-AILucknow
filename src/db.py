"""SQLite storage: connection, schema, and every SQL query in one place.

Vectors never go in SQLite — they live in FAISS files; `chunks.faiss_pos` is the
mapping. Everything else (pages, chunks text, table rows, QA log) is here.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    filename      TEXT,
    num_pages     INTEGER,
    ingested_at   TEXT,
    ocr_pages     INTEGER DEFAULT 0,
    status        TEXT
);
CREATE TABLE IF NOT EXISTS pages (
    doc_id        TEXT,
    page_no       INTEGER,
    printed_no    INTEGER,
    raw_text      TEXT,
    is_scanned    INTEGER DEFAULT 0,
    image_path    TEXT,
    PRIMARY KEY (doc_id, page_no)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      INTEGER PRIMARY KEY,
    doc_id        TEXT,
    page_no       INTEGER,
    chunk_type    TEXT,
    text          TEXT,
    faiss_pos     INTEGER
);
CREATE TABLE IF NOT EXISTS table_rows (
    row_id        INTEGER PRIMARY KEY,
    doc_id        TEXT,
    page_no       INTEGER,
    table_title   TEXT,
    row_label     TEXT,
    row_label_norm TEXT,
    columns_json  TEXT,
    values_json   TEXT
);
CREATE TABLE IF NOT EXISTS qa_log (
    id            INTEGER PRIMARY KEY,
    doc_id        TEXT,
    question      TEXT,
    answer        TEXT,
    page          INTEGER,
    confidence    REAL,
    source        TEXT,
    created_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_rows_norm ON table_rows(doc_id, row_label_norm);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks(doc_id, page_no);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, chunk_type);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- documents
def upsert_document(conn, doc_id: str, filename: str, num_pages: int, status: str = "ingesting"):
    conn.execute(
        "INSERT OR REPLACE INTO documents(doc_id, filename, num_pages, ingested_at, ocr_pages, status)"
        " VALUES (?,?,?,?,COALESCE((SELECT ocr_pages FROM documents WHERE doc_id=?),0),?)",
        (doc_id, filename, num_pages, now_iso(), doc_id, status),
    )
    conn.commit()


def update_document_status(conn, doc_id: str, status: str, ocr_pages: int | None = None):
    if ocr_pages is None:
        conn.execute("UPDATE documents SET status=? WHERE doc_id=?", (status, doc_id))
    else:
        conn.execute(
            "UPDATE documents SET status=?, ocr_pages=? WHERE doc_id=?",
            (status, ocr_pages, doc_id),
        )
    conn.commit()


def get_document(conn, doc_id: str):
    row = conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    return dict(row) if row else None


def list_documents(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY ingested_at DESC")]


def delete_document_data(conn, doc_id: str):
    for tbl in ("pages", "chunks", "table_rows"):
        conn.execute(f"DELETE FROM {tbl} WHERE doc_id=?", (doc_id,))
    conn.commit()


def doc_stats(conn, doc_id: str) -> dict:
    def one(sql, args=(doc_id,)):
        r = conn.execute(sql, args).fetchone()
        return r[0] if r else 0

    return {
        "pages": one("SELECT COUNT(*) FROM pages WHERE doc_id=?"),
        "chunks": one("SELECT COUNT(*) FROM chunks WHERE doc_id=?"),
        "table_rows": one("SELECT COUNT(*) FROM table_rows WHERE doc_id=?"),
        "tables": one("SELECT COUNT(DISTINCT page_no) FROM table_rows WHERE doc_id=?"),
        "ocr_pages": one("SELECT COUNT(*) FROM pages WHERE doc_id=? AND is_scanned=1"),
    }


# ---------------------------------------------------------------- pages
def insert_page(conn, doc_id: str, page):
    conn.execute(
        "INSERT OR REPLACE INTO pages(doc_id, page_no, printed_no, raw_text, is_scanned, image_path)"
        " VALUES (?,?,?,?,?,?)",
        (doc_id, page.page_no, page.printed_no, page.raw_text, page.is_scanned, page.image_path),
    )


def get_page(conn, doc_id: str, page_no: int):
    row = conn.execute(
        "SELECT * FROM pages WHERE doc_id=? AND page_no=?", (doc_id, page_no)
    ).fetchone()
    return dict(row) if row else None


def all_pages_text(conn, doc_id: str):
    """[(page_no, raw_text)] for the whole document — used for entity-presence checks."""
    return [
        (r["page_no"], r["raw_text"] or "")
        for r in conn.execute("SELECT page_no, raw_text FROM pages WHERE doc_id=?", (doc_id,))
    ]


# ---------------------------------------------------------------- chunks
def insert_chunk(conn, doc_id: str, chunk) -> int:
    cur = conn.execute(
        "INSERT INTO chunks(doc_id, page_no, chunk_type, text, faiss_pos) VALUES (?,?,?,?,?)",
        (doc_id, chunk.page_no, chunk.chunk_type, chunk.text, chunk.faiss_pos),
    )
    return cur.lastrowid


def update_chunk_faiss_pos(conn, chunk_id: int, faiss_pos: int):
    conn.execute("UPDATE chunks SET faiss_pos=? WHERE chunk_id=?", (faiss_pos, chunk_id))


def get_chunks(conn, doc_id: str, chunk_types: tuple | None = None):
    if chunk_types:
        q = ",".join("?" * len(chunk_types))
        rows = conn.execute(
            f"SELECT * FROM chunks WHERE doc_id=? AND chunk_type IN ({q}) ORDER BY chunk_id",
            (doc_id, *chunk_types),
        )
    else:
        rows = conn.execute("SELECT * FROM chunks WHERE doc_id=? ORDER BY chunk_id", (doc_id,))
    return [dict(r) for r in rows]


def get_chunks_for_page(conn, doc_id: str, page_no: int, chunk_types: tuple | None = None):
    if chunk_types:
        q = ",".join("?" * len(chunk_types))
        rows = conn.execute(
            f"SELECT * FROM chunks WHERE doc_id=? AND page_no=? AND chunk_type IN ({q}) ORDER BY chunk_id",
            (doc_id, page_no, *chunk_types),
        )
    else:
        rows = conn.execute(
            "SELECT * FROM chunks WHERE doc_id=? AND page_no=? ORDER BY chunk_id", (doc_id, page_no)
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- table rows
def insert_table_row(conn, doc_id: str, row) -> int:
    from src.ingest.normalize import normalize_label

    cur = conn.execute(
        "INSERT INTO table_rows(doc_id, page_no, table_title, row_label, row_label_norm,"
        " columns_json, values_json) VALUES (?,?,?,?,?,?,?)",
        (
            doc_id,
            row.page_no,
            row.table_title,
            row.row_label,
            normalize_label(row.row_label),
            json.dumps(row.columns) if row.columns else None,
            json.dumps(row.values),
        ),
    )
    return cur.lastrowid


def _row_to_dict(r) -> dict:
    d = dict(r)
    d["values"] = json.loads(d.pop("values_json") or "[]")
    d["columns"] = json.loads(d.pop("columns_json")) if d.get("columns_json") else None
    if "columns_json" in d:
        d.pop("columns_json")
    return d


def find_table_rows(conn, doc_id: str, row_label_norm: str):
    rows = conn.execute(
        "SELECT * FROM table_rows WHERE doc_id=? AND row_label_norm=? ORDER BY page_no",
        (doc_id, row_label_norm),
    )
    return [_row_to_dict(r) for r in rows]


def distinct_row_labels(conn, doc_id: str):
    """[(row_label, row_label_norm)] distinct — the entity vocabulary."""
    rows = conn.execute(
        "SELECT row_label, row_label_norm, COUNT(*) c FROM table_rows WHERE doc_id=?"
        " GROUP BY row_label_norm ORDER BY c DESC",
        (doc_id,),
    )
    return [(r["row_label"], r["row_label_norm"]) for r in rows]


# ---------------------------------------------------------------- qa log
def log_qa(conn, doc_id: str, question: str, answer) -> None:
    conn.execute(
        "INSERT INTO qa_log(doc_id, question, answer, page, confidence, source, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (doc_id, question, answer.answer, answer.page, answer.confidence, answer.source, now_iso()),
    )
    conn.commit()
