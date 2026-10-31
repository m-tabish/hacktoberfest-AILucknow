"""Answer orchestration (architecture doc §7):

cell_lookup (deterministic) -> hybrid retrieval -> abstain check ->
LLM over full candidate pages -> validator. Every path logs to qa_log and
returns sources for the UI's citation view.
"""
from __future__ import annotations

from src import config, db
from src.ingest.normalize import normalize_label
from src.models import Answer
from src.qa import cell_lookup, entity, hybrid_search, llm_client, prompts, validator


def _sources_for_page(conn, doc_id: str, page_no: int, ctx, answer_str: str = "") -> list:
    if not page_no:
        return []
    chunks = db.get_chunks_for_page(conn, doc_id, page_no, ("table_row", "narrative"))
    picked = []
    for c in chunks:
        t = c["text"]
        if (ctx and ctx.entity_norm and ctx.entity_norm in normalize_label(t)) or (
            answer_str and answer_str not in ("", config.NOT_FOUND) and answer_str in t.replace(",", "")
        ):
            picked.append(t)
        if len(picked) >= 3:
            break
    if not picked:
        picked = [c["text"] for c in chunks[:2]]
    return picked


def _page_image(conn, doc_id: str, page_no: int):
    if not page_no:
        return None
    row = db.get_page(conn, doc_id, page_no)
    return row["image_path"] if row else None


def answer_question(conn, doc_id: str, question: str, qid: str | None = None) -> Answer:
    ctx = entity.extract_context(conn, doc_id, question)

    # 1) deterministic cell lookup
    hit = cell_lookup.lookup(conn, doc_id, ctx)
    if hit:
        ans = Answer(
            answer=str(hit["value"]), page=hit["page"], confidence=0.95,
            source="cell_lookup", qid=qid,
            sources=_sources_for_page(conn, doc_id, hit["page"], ctx, str(hit["value"])),
            page_image=_page_image(conn, doc_id, hit["page"]),
            llm_trace={"status": "not_called", "reason": "Answer came from deterministic table lookup."},
        )
        db.log_qa(conn, doc_id, question, ans)
        return ans

    # 2) hybrid retrieval -> candidate pages
    candidates = hybrid_search.search_pages(conn, doc_id, question, ctx)
    cand_pages = [c["page_no"] for c in candidates]
    top_chunks = []
    for c in candidates[:2]:
        top_chunks += [ch["text"] for ch in c["chunks"][:2]]

    # 3) abstain: entity appears nowhere in the document
    absent = bool(ctx.entity_norm) and not hybrid_search.entity_present(conn, doc_id, ctx.entity_norm)
    if absent:
        ans = Answer(
            answer=config.NOT_FOUND, page=0, confidence=0.8, source="abstain", qid=qid,
            sources=top_chunks[:2],
            note=f"'{ctx.entity}' was searched across all pages and does not appear in this report.",
            llm_trace={"status": "not_called", "reason": "Entity was not found in the document."},
        )
        db.log_qa(conn, doc_id, question, ans)
        return ans

    # 4) no LLM configured -> clear low-confidence fallback (retrieval still shown)
    if not llm_client.is_configured():
        top_page = cand_pages[0] if cand_pages else 0
        ans = Answer(
            answer=config.NOT_FOUND, page=0, confidence=0.2, source="no_llm_fallback", qid=qid,
            sources=top_chunks[:3],
            note=("LLM not configured (set LLM_API_KEY in .env), so the exact cell could not be "
                  f"extracted. Retrieval's top candidate page is {top_page or '—'}."),
            llm_trace={"status": "not_called", "reason": "LLM_API_KEY is not configured."},
        )
        db.log_qa(conn, doc_id, question, ans)
        return ans

    # 5) LLM over full candidate pages, one retry on invalid output
    use_pages = cand_pages[: config.LLM_CONTEXT_PAGES]
    page_texts = {}
    for p in use_pages:
        row = db.get_page(conn, doc_id, p)
        page_texts[p] = row["raw_text"] if row else ""
    result = None
    llm_attempts = []
    for _attempt in range(2):
        trace = {}
        raw = llm_client.complete_json(
            prompts.SYSTEM_PROMPT,
            prompts.build_user_prompt(question, [(p, page_texts[p]) for p in use_pages]),
            trace=trace,
        )
        llm_attempts.append(trace)
        result = validator.validate_llm_result(raw or {}, use_pages, page_texts)
        if result:
            break
    if result is None:
        reason = llm_client.last_error or "Gemini's answer did not match the report text or candidate pages."
        ans = Answer(
            answer=config.NOT_FOUND, page=0, confidence=0.3, source="llm_invalid", qid=qid,
            sources=top_chunks[:3],
            note=f"Could not validate Gemini's answer: {reason}",
            llm_trace={"status": "completed", "attempts": llm_attempts},
        )
        db.log_qa(conn, doc_id, question, ans)
        return ans

    ans = Answer(
        answer=result["answer"], page=result["page"], confidence=result["confidence"],
        source="llm" if result["answer"] != config.NOT_FOUND else "abstain", qid=qid,
        sources=_sources_for_page(conn, doc_id, result["page"], ctx, result["answer"]),
        page_image=_page_image(conn, doc_id, result["page"]),
        llm_trace={"status": "completed", "attempts": llm_attempts},
    )
    db.log_qa(conn, doc_id, question, ans)
    return ans
