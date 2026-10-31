"""Chunking: 3 chunk types (architecture doc §5).

- 'page'      : full page text — the unit the LLM ultimately reads.
- 'narrative' : ~800-char sliding windows, never crossing a page boundary.
- 'table_row' : one per extracted table row, header/title context injected so
                the row is self-describing in search.
"""
from __future__ import annotations

import re

from src import config
from src.models import Chunk


def table_row_text(row) -> str:
    title = row.table_title or "Table"
    head = f"[Page {row.page_no} | {title}] {row.row_label} — "
    if row.columns:
        body = "; ".join(f"{k}: {v}" for k, v in row.columns.items())
    else:
        body = "values: " + ", ".join(str(v) for v in row.values)
    return head + body


def build_chunks_for_page(page_data, table_rows: list) -> list:
    chunks: list[Chunk] = []
    text = page_data.raw_text or ""
    if text:
        chunks.append(Chunk(page_no=page_data.page_no, chunk_type="page",
                            text=text[: config.PAGE_CHUNK_MAX_CHARS]))
        flat = re.sub(r"\s+", " ", text).strip()
        size, overlap = config.NARRATIVE_CHUNK_CHARS, config.NARRATIVE_OVERLAP_CHARS
        if len(flat) > 200:
            step = max(size - overlap, 1)
            n = 0
            for start in range(0, len(flat), step):
                piece = flat[start:start + size]
                if len(piece) < 80 and start > 0:
                    break
                chunks.append(Chunk(page_no=page_data.page_no,
                                    chunk_type="narrative", text=piece))
                n += 1
                if n >= 12 or start + size >= len(flat):
                    break
    for row in table_rows:
        chunks.append(Chunk(page_no=row.page_no, chunk_type="table_row",
                            text=table_row_text(row)))
    return chunks
