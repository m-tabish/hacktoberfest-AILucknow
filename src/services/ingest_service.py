"""Ingestion orchestration: file -> doc_id -> pages/rows/chunks/indexes in SQLite.

Idempotent: re-ingesting the same file (same SHA-256) when status='ready'
returns the existing stats without redoing work, unless force=True.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from src import config, db
from src.ingest import chunker, indexer, ocr, pdf_loader, table_extract


def file_doc_id(pdf_path: str | Path) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:12]


def ingest_pdf(pdf_path: str | Path, original_filename: str | None = None,
               progress=None, force: bool = False, conn=None) -> dict:
    """Ingest a PDF. `progress(frac, msg)` optional callback (Streamlit progress).

    Returns a stats dict: doc_id, filename, pages, ocr_pages, tables(pages with
    rows), table_rows, chunks, faiss (bool), reused (bool).
    """
    config.ensure_dirs()
    pdf_path = Path(pdf_path)
    doc_id = file_doc_id(pdf_path)
    filename = original_filename or pdf_path.name
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        db.init_db(conn)
        existing = db.get_document(conn, doc_id)
        if existing and existing["status"] == "ready" and not force:
            stats = db.doc_stats(conn, doc_id)
            return {"doc_id": doc_id, "filename": filename, "reused": True,
                    "faiss": (config.doc_index_dir(doc_id) / "chunks.faiss").exists(), **stats}

        # copy into uploads/ under the doc_id name
        dest = config.doc_upload_path(doc_id)
        if pdf_path.resolve() != dest.resolve():
            shutil.copyfile(pdf_path, dest)

        doc = pdf_loader.open_pdf(dest)
        num_pages = len(doc)
        db.upsert_document(conn, doc_id, filename, num_pages, status="ingesting")
        db.delete_document_data(conn, doc_id)

        pages_dir = config.doc_pages_dir(doc_id)
        last_title: str | None = None
        ocr_pages = 0
        total_rows = 0

        for idx in range(num_pages):
            page_no = idx + 1
            if progress:
                progress(idx / max(num_pages, 1), f"Page {page_no}/{num_pages}")
            page = doc[idx]
            page_data = pdf_loader.load_page(page, page_no)

            # OCR branch: low native text + page has an image
            if ocr.needs_ocr(page_data.raw_text) and page_data.has_image:
                ocr_text = ocr.ocr_page(page)
                if len(ocr_text.strip()) > len(page_data.raw_text.strip()):
                    page_data.raw_text = ocr_text
                    page_data.lines = [(float(i), ln) for i, ln in enumerate(ocr_text.splitlines())]
                    page_data.is_scanned = 1
                    ocr_pages += 1

            # citation preview image
            img = pdf_loader.render_page_png(
                page, pages_dir / f"page_{page_no:03d}.png")
            page_data.image_path = img

            # tables: title may live on this or the previous page; Contd pages
            # inherit the running title
            title = table_extract.find_table_title(page_data.raw_text, fallback=last_title)
            if title:
                last_title = title
            rows = table_extract.extract_page_rows(
                page, page_data, title,
                numeric_density_high=table_extract.should_run_table_scan(page_data.raw_text),
            )

            db.insert_page(conn, doc_id, page_data)
            for row in rows:
                db.insert_table_row(conn, doc_id, row)
            total_rows += len(rows)
            for chunk in chunker.build_chunks_for_page(page_data, rows):
                db.insert_chunk(conn, doc_id, chunk)
            if page_no % 25 == 0:
                conn.commit()
        conn.commit()
        doc.close()

        if progress:
            progress(0.95, "Building search indexes…")
        idx = indexer.index_document(doc_id, conn)
        db.update_document_status(conn, doc_id, "ready", ocr_pages=ocr_pages)
        stats = db.doc_stats(conn, doc_id)
        if progress:
            progress(1.0, "Done")
        return {"doc_id": doc_id, "filename": filename, "reused": False,
                "faiss": idx["faiss"], **stats}
    finally:
        if own_conn:
            conn.close()
