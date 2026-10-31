"""Deterministic cell lookup: entity row + metric column -> exact value.

Uses mapped columns when available, with a guarded fallback for repeated
subject-group tables whose headers could not be mapped. Conflicting values
still defer to retrieval + LLM.
"""
from __future__ import annotations

from src import db

_COLUMN_VARIANTS = {
    "killed": ["killed", "fatalities", "deaths", "persons_killed"],
    "injured": ["injured", "injuries", "persons_injured"],
    "accidents": ["accidents", "total_accidents", "road_accidents"],
}

def candidate_column_keys(metric: str | None, year: int | None) -> list:
    if not metric:
        return []
    bases = _COLUMN_VARIANTS.get(metric, [metric])
    if year:
        # Only year-suffixed keys: falling back to a bare metric key when the
        # question names a year risks returning another year's figure.
        return [f"{b}_{year}" for b in bases]
    return list(bases)


def lookup(conn, doc_id: str, ctx) -> dict | None:
    """Return {'value', 'page', 'row'} or None."""
    if not ctx.entity_norm or not ctx.metric:
        return None
    keys = candidate_column_keys(ctx.metric, ctx.year)
    if not keys:
        return None
    found: dict[int, tuple] = {}  # value -> (page, row)
    for row in db.find_table_rows(conn, doc_id, ctx.entity_norm):
        cols = row.get("columns") or {}
        for k in keys:
            if k in cols and isinstance(cols[k], (int, float)):
                found.setdefault(int(cols[k]), (row["page_no"], row))
                break
    if len(found) == 1:
        value, (page, row) = next(iter(found.items()))
        return {"value": value, "page": page, "row": row}
    return None
