"""Chat service: one question -> Answer with citations (used by Streamlit)."""
from __future__ import annotations

from src import db
from src.models import Answer
from src.qa.answerer import answer_question


def ask(doc_id: str, question: str) -> Answer:
    conn = db.connect()
    try:
        db.init_db(conn)
        return answer_question(conn, doc_id, question)
    finally:
        conn.close()


def document_stats(doc_id: str) -> dict:
    conn = db.connect()
    try:
        db.init_db(conn)
        doc = db.get_document(conn, doc_id)
        stats = db.doc_stats(conn, doc_id)
        return {"document": doc, **stats}
    finally:
        conn.close()
