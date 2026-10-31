"""Answer validation: integer-or-NOT_FOUND, page must be a candidate, confidence rules."""
from __future__ import annotations

import re

from src import config
from src.ingest.normalize import extract_numbers


def clean_answer_value(raw) -> str | None:
    """Normalise a raw answer to an integer string or NOT_FOUND; None if unusable."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if "NOT_FOUND" in s.upper().replace(" ", "_") or s.upper() == "NOT FOUND":
        return config.NOT_FOUND
    s = s.replace(",", "")
    m = re.search(r"-?\d+", s)
    if m:
        try:
            return str(int(m.group(0)))
        except ValueError:
            return None
    if "not found" in s.lower():
        return config.NOT_FOUND
    return None


def validate_llm_result(result: dict, candidate_pages: list, page_texts: dict) -> dict | None:
    """Validate/normalise an LLM JSON result.

    candidate_pages: page numbers the LLM was shown.
    page_texts: {page_no: text} for those pages.
    Returns {'answer','page','confidence'} or None if unusable.
    """
    if not isinstance(result, dict):
        return None
    ans = clean_answer_value(result.get("answer"))
    if ans is None:
        return None
    try:
        conf = float(result.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = min(max(conf, 0.0), 1.0)
    if ans == config.NOT_FOUND:
        return {"answer": ans, "page": 0, "confidence": max(conf, 0.5)}
    try:
        page = int(result.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    target = int(ans)
    cited_has = page in candidate_pages and target in extract_numbers(page_texts.get(page, ""))
    if not cited_has:
        # relocate to a candidate page whose text actually contains the number
        for p in candidate_pages:
            if target in extract_numbers(page_texts.get(p, "")):
                page = p
                cited_has = True
                break
    if page not in candidate_pages:
        return None
    # confidence rule: value literally present on the cited page -> at least 0.85
    if target in extract_numbers(page_texts.get(page, "")):
        conf = max(conf, 0.85)
    else:
        conf = min(conf, 0.6)
    return {"answer": ans, "page": page, "confidence": round(conf, 2)}
