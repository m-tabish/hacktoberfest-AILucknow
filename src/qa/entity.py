"""Question understanding: entity + metric + year.

Entity matching is done against the actual row labels stored for the document
(never a hardcoded city list), so it works on the hidden report too.
RapidFuzz is used when available; a difflib fallback keeps it working without.
"""
from __future__ import annotations

import re

from src import config, db
from src.ingest.normalize import normalize_label
from src.models import QuestionContext

# base metric -> words that signal it in a question / page
METRIC_SYNONYMS = {
    "killed": ["killed", "deaths", "death", "fatalities", "fatality", "died", "dead"],
    "injured": ["injured", "injuries", "injury", "hurt"],
    "accidents": ["accidents", "accident", "crashes", "crash"],
}

SUBJECT_KEYWORDS = {
    "two_wheeler": ["two-wheeler", "two wheeler", "two-wheelers", "two wheelers"],
    "pedestrian": ["pedestrian", "pedestrians"],
    "overspeeding": ["over-speeding", "overspeeding", "over speeding"],
    "mobile_phone": ["mobile phone"],
    "drunken": ["drunken", "alcohol", "drug"],
}


def detect_metric(question: str) -> str | None:
    q = question.lower()
    # 'how many road accidents ... killed' style questions: the metric asked is
    # the one attached to persons/deaths; order checks by specificity.
    if any(w in q for w in METRIC_SYNONYMS["killed"]):
        return "killed"
    if any(w in q for w in METRIC_SYNONYMS["injured"]):
        return "injured"
    if any(w in q for w in METRIC_SYNONYMS["accidents"]):
        return "accidents"
    return None


def detect_subject(question: str) -> str | None:
    q = question.lower()
    for subj, words in SUBJECT_KEYWORDS.items():
        if any(w in q for w in words):
            return subj
    return None


def detect_year(question: str) -> int | None:
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    return int(years[-1]) if years else None


def _fuzzy_best(question_norm: str, labels: list) -> tuple | None:
    """Best (label, norm, score) fuzzy partial match, or None."""
    best = None
    try:
        from rapidfuzz import fuzz

        for label, norm in labels:
            if not norm:
                continue
            s = fuzz.partial_ratio(norm, question_norm)
            if best is None or s > best[2]:
                best = (label, norm, s)
    except Exception:
        import difflib

        for label, norm in labels:
            if not norm:
                continue
            s = difflib.SequenceMatcher(None, norm, question_norm).ratio() * 100
            if best is None or s > best[2]:
                best = (label, norm, s)
    return best


# Labels made only of these words are header fragments / question words
# (e.g. a parsed row literally labelled "Number"), never real entities.
GENERIC_LABEL_TOKENS = {
    "number", "total", "of", "the", "a", "an", "in", "on", "persons",
    "person", "road", "accidents", "accident", "killed", "injured",
    "deaths", "death", "fatalities", "injuries", "city", "state", "states",
    "year", "during", "reported", "occurred", "involved", "classified",
}


def _is_generic_label(norm: str) -> bool:
    toks = norm.split()
    return bool(toks) and all(t in GENERIC_LABEL_TOKENS for t in toks)


def extract_context(conn, doc_id: str, question: str) -> QuestionContext:
    ctx = QuestionContext(
        raw_question=question,
        metric=detect_metric(question),
        year=detect_year(question),
    )
    ctx.subject = detect_subject(question)  # extra attribute, used for synonyms/prompts
    q_norm = normalize_label(question)
    labels = [(l, n) for l, n in db.distinct_row_labels(conn, doc_id)
              if not _is_generic_label(n)]
    # 1) exact substring match — longest label wins (most specific)
    hits = [(label, norm) for label, norm in labels if norm and norm in q_norm]
    if hits:
        label, norm = max(hits, key=lambda h: len(h[1]))
        ctx.entity, ctx.entity_norm = label, norm
        return ctx
    # 2) distinctive single-token match (e.g. label 'Allahabad (Prayagraj)', question 'Prayagraj')
    token_hits = []
    for label, norm in labels:
        for tok in norm.split():
            if len(tok) >= 5 and tok in q_norm:
                token_hits.append((label, norm))
                break
    if len({n for _l, n in token_hits}) == 1:
        ctx.entity, ctx.entity_norm = token_hits[0]
        return ctx
    # 3) fuzzy match
    best = _fuzzy_best(q_norm, labels)
    if best and best[2] >= config.ENTITY_FUZZY_THRESHOLD:
        ctx.entity, ctx.entity_norm = best[0], best[1]
    return ctx
