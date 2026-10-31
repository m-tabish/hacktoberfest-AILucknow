#!/usr/bin/env python3
"""Report Navigator — Streamlit dashboard.

UI only: all logic lives in src/services. Run from the project root:
  streamlit run app.py
Layout: sidebar = upload/ingest/status, Tab 1 = chat with citations,
Tab 2 = batch run + evaluation.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from src import db
from src.services import batch_service, chat_service, document_service, ingest_service

st.set_page_config(page_title="Report Navigator", page_icon="📄", layout="wide")


# ------------------------------------------------------------------ helpers
def _highlight(text: str, needle: str) -> str:
    if needle and needle != "NOT_FOUND" and needle in text:
        return text.replace(needle, f"<mark>{needle}</mark>")
    return text


def _render_answer(ans: dict):
    if ans["answer"] == "NOT_FOUND":
        st.warning(f"**Not found in the report** · confidence {ans['confidence']:.2f}")
    else:
        st.markdown(f"## {ans['answer']}")
        st.markdown(
            f"📄 **Page {ans['page']}** · Confidence: {ans['confidence']:.2f} · "
            f"Source: `{ans['source']}`"
        )
    if ans.get("note"):
        st.caption(ans["note"])
    for i, src in enumerate(ans.get("sources") or []):
        with st.expander(f"View source passage {i + 1}"):
            st.markdown(_highlight(src, ans["answer"]), unsafe_allow_html=True)
    if ans.get("page_image"):
        with st.expander("View page image"):
            st.image(ans["page_image"])


def _doc_options():
    conn = db.connect()
    try:
        db.init_db(conn)
        return [d for d in db.list_documents(conn) if d["status"] == "ready"]
    finally:
        conn.close()


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("📄 Report Navigator")
    uploaded = st.file_uploader("Upload report PDF", type=["pdf"])
    if uploaded is not None:
        if st.button("Ingest PDF", type="primary"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded.getbuffer())
                tmp_path = tmp.name
            bar = st.progress(0.0)
            status = st.empty()

            def _progress(frac, msg):
                bar.progress(min(max(frac, 0.0), 1.0))
                status.caption(msg)

            stats = ingest_service.ingest_pdf(
                tmp_path, original_filename=uploaded.name, progress=_progress)
            st.session_state["doc_id"] = stats["doc_id"]
            st.success(
                f"Ready: {stats['pages']} pages · {stats['table_rows']} table rows · "
                f"{stats['chunks']} chunks · OCR pages: {stats['ocr_pages']}"
            )
    docs = _doc_options()
    if docs:
        labels = {d["doc_id"]: f"{d['filename']} ({d['doc_id']})" for d in docs}
        current = st.session_state.get("doc_id", docs[0]["doc_id"])
        if current not in labels:
            current = docs[0]["doc_id"]
        chosen = st.selectbox("Document", list(labels), format_func=lambda k: labels[k],
                              index=list(labels).index(current))
        st.session_state["doc_id"] = chosen
        stats = chat_service.document_stats(chosen)
        c1, c2 = st.columns(2)
        c1.metric("Pages", stats["pages"])
        c2.metric("OCR pages", stats["ocr_pages"])
        c1.metric("Table rows", stats["table_rows"])
        c2.metric("Chunks", stats["chunks"])
        latest_doc = docs[0]
        st.caption(f"Most recently parsed: {latest_doc['filename']}")
        if st.button("Delete latest parsed document", key="delete_latest_document"):
            try:
                deleted = document_service.delete_document(latest_doc["doc_id"])
            except Exception as exc:
                st.error(f"Could not delete this document: {exc}")
            else:
                if deleted:
                    for key in (
                        "doc_id", "messages", "batch_answers", "batch_questions", "batch_gold"
                    ):
                        st.session_state.pop(key, None)
                    st.success(f"Deleted {latest_doc['filename']} and its parsed context.")
                    st.rerun()
                else:
                    st.warning("This document was already deleted.")
    else:
        st.info("Upload and ingest a report PDF to begin.")

doc_id = st.session_state.get("doc_id")

tab_chat, tab_batch = st.tabs(["💬 Chat", "📋 Batch + Evaluation"])

# ------------------------------------------------------------------ chat tab
with tab_chat:
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                _render_answer(msg["content"])
    question = st.chat_input("Ask a question about the report…")
    if question:
        if not doc_id:
            st.error("Ingest a PDF first (sidebar).")
        else:
            st.session_state["messages"].append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Searching the report…"):
                    ans = chat_service.ask(doc_id, question)
                ans_dict = {
                    "answer": ans.answer, "page": ans.page,
                    "confidence": ans.confidence, "source": ans.source,
                    "sources": ans.sources, "page_image": ans.page_image,
                    "note": ans.note,
                }
                _render_answer(ans_dict)
                st.session_state["messages"].append(
                    {"role": "assistant", "content": ans_dict})

# ------------------------------------------------------------------ batch tab
with tab_batch:
    q_file = st.file_uploader("Questions .jsonl (id, question)", type=["jsonl"], key="q")
    gold_file = st.file_uploader("Gold answers .jsonl (optional, for scoring)",
                                 type=["jsonl"], key="g")
    if q_file is not None and st.button("Run batch", type="primary"):
        if not doc_id:
            st.error("Ingest a PDF first (sidebar).")
        else:
            questions = []
            for line in q_file.getvalue().decode("utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    questions.append({"id": d.get("id"), "question": d.get("question", "")})
            bar = st.progress(0.0)
            answers = batch_service.run_batch(
                doc_id, questions,
                progress=lambda f, m: bar.progress(min(max(f, 0.0), 1.0)))
            st.session_state["batch_answers"] = answers
            st.session_state["batch_questions"] = {q["id"]: q["question"] for q in questions}
            if gold_file is not None:
                gold = [json.loads(l) for l in
                        gold_file.getvalue().decode("utf-8").splitlines() if l.strip()]
                st.session_state["batch_gold"] = gold
    answers = st.session_state.get("batch_answers")
    if answers:
        try:
            import pandas as pd

            qmap = st.session_state.get("batch_questions", {})
            df = pd.DataFrame([
                {"id": a["id"], "question": qmap.get(a["id"], ""),
                 "answer": a["answer"], "page": a["page"], "confidence": a["confidence"]}
                for a in answers
            ])
            st.dataframe(df, use_container_width=True)
        except Exception:
            st.json(answers)
        payload = "\n".join(json.dumps(a) for a in answers)
        st.download_button("Download answers.jsonl", payload,
                           file_name="answers.jsonl", mime="application/json")
        gold = st.session_state.get("batch_gold")
        if gold:
            from evaluate import compute_metrics

            m = compute_metrics(answers, gold)
            c1, c2, c3 = st.columns(3)
            c1.metric("Exact match %", m["exact_match_pct"])
            c2.metric("Page accuracy %", m["page_accuracy_pct"])
            c3.metric("NOT_FOUND P / R", f"{m['not_found_precision']} / {m['not_found_recall']}")
