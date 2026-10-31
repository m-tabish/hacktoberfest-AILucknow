"""Smoke test against the real public dataset (Report A).

Requires /tmp/p5/report_A.pdf + /tmp/p5/questions.jsonl (override with
REPORT_A_PDF / REPORT_A_QUESTIONS env vars). Skips cleanly if absent.
Ingests into a throwaway data dir; no LLM key is used — this verifies
ingestion, storage, hybrid retrieval (page 101 for the Pune question) and
the no-LLM abstain/fallback behaviour.

Run: python -m pytest tests/test_gold_smoke.py -s
"""
import json
import os
import sys
import tempfile
from pathlib import Path

PDF = Path(os.environ.get("REPORT_A_PDF", "/tmp/p5/report_A.pdf"))
QUESTIONS = Path(os.environ.get("REPORT_A_QUESTIONS", "/tmp/p5/questions.jsonl"))

if not PDF.exists():
    try:
        import pytest

        pytest.skip("Report A dataset not present", allow_module_level=True)
    except ImportError:
        print("SKIP: dataset not present")
        raise SystemExit(0)

# throwaway storage (stable path, so reruns reuse the 'ready' ingestion)
# + guarantee no LLM key leaks into this test
os.environ["REPORT_NAVIGATOR_DATA_DIR"] = str(
    Path(tempfile.gettempdir()) / "reportnav-smoke-fixed")
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import db  # noqa: E402
from src.qa import entity, hybrid_search  # noqa: E402
from src.qa.answerer import answer_question  # noqa: E402
from src.services import ingest_service  # noqa: E402

_stats = None
_doc_id = None


def _ensure_ingested():
    global _stats, _doc_id
    if _stats is None:
        _stats = ingest_service.ingest_pdf(PDF, original_filename="report_A.pdf")
        _doc_id = _stats["doc_id"]
    return _stats


def test_ingestion_counts():
    stats = _ensure_ingested()
    print("STATS:", stats)
    assert stats["pages"] == 272
    assert stats["chunks"] > 500
    assert stats["table_rows"] > 100


def test_pune_row_on_page_101():
    _ensure_ingested()
    conn = db.connect()
    try:
        rows = db.find_table_rows(conn, _doc_id, "pune")
        p101 = [r for r in rows if r["page_no"] == 101]
        assert p101, f"no Pune row on page 101 (pages found: {[r['page_no'] for r in rows]})"
        values = p101[0]["values"]
        print("Pune p101 values:", values)
        assert 1230 in values and 351 in values
    finally:
        conn.close()


def test_hybrid_retrieval_finds_page_101():
    _ensure_ingested()
    gold = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]
    q0 = next(g for g in gold if g["id"] == "P000")
    assert q0["answer"] == "351" and q0["gold_pages"] == [101]
    conn = db.connect()
    try:
        ctx = entity.extract_context(conn, _doc_id, q0["question"])
        print("CTX:", ctx.entity, ctx.metric, ctx.year)
        assert ctx.entity_norm == "pune"
        results = hybrid_search.search_pages(conn, _doc_id, q0["question"], ctx, top_pages=5)
        pages = [r["page_no"] for r in results]
        print("Top candidate pages:", pages)
        assert 101 in pages
    finally:
        conn.close()


def test_no_llm_answerer_paths():
    _ensure_ingested()
    conn = db.connect()
    try:
        # unanswerable in gold (Bareilly is not a million-plus city in the report)
        ans = answer_question(conn, _doc_id,
                              "How many road accidents were reported in Bareilly city in 2023?",
                              qid="PX")
        print("Bareilly answer:", ans.answer, ans.source, ans.confidence)
        assert ans.answer == "NOT_FOUND"
        # Pune question without an LLM key: must not crash; either a deterministic
        # cell hit (351) or the clear low-confidence fallback.
        ans2 = answer_question(
            conn, _doc_id,
            "What was the number of road accident deaths in Pune city in 2023?", qid="P000")
        print("Pune answer:", ans2.answer, ans2.source, ans2.confidence, ans2.note)
        assert ans2.answer in ("351", "NOT_FOUND")
        if ans2.answer == "NOT_FOUND":
            assert ans2.source == "no_llm_fallback" and ans2.confidence <= 0.3
    finally:
        conn.close()


if __name__ == "__main__":
    test_ingestion_counts()
    test_pune_row_on_page_101()
    test_hybrid_retrieval_finds_page_101()
    test_no_llm_answerer_paths()
    print("ALL SMOKE TESTS PASSED")
