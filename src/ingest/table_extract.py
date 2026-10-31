"""Table extraction.

Strategy (per architecture doc §6):
1. PyMuPDF find_tables() first — only on number-dense pages, for speed.
2. Fallback pseudo-rows from coordinate-sorted lines: a line shaped like
   [optional serial] + label + >=3 numbers is almost certainly a table row
   in these statistical reports.
values are ALWAYS stored; columns are only set when a header row maps
confidently (see map_header_cells).
"""
from __future__ import annotations

import re

from src import config
from src.ingest.normalize import normalize_label, parse_number_token
from src.models import TableRow

_TITLE_RE = re.compile(r"(Table\s+\d+(?:\.\d+)?|Annexure\s+\d+|Appendix\s+[A-Z0-9]+)", re.I)

STOP_LABELS = {
    "share", "per cent", "percent", "percentage", "total", "grand total",
    "sl no", "s no", "states uts", "state ut", "category", "year",
    "accidents", "killed", "injured", "persons killed", "persons injured",
    "number of accidents", "number of persons", "rank",
}

_METRIC_KEYWORDS = [
    ("accident", "accidents"),
    ("killed", "killed"),
    ("fatalit", "killed"),
    ("death", "killed"),
    ("injur", "injured"),
]


def find_table_title(text: str, fallback: str | None = None) -> str | None:
    m = _TITLE_RE.search(text or "")
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return fallback


def is_continuation(text: str) -> bool:
    return bool(re.search(r"\b(Contd|Concld)\b", text or ""))


def map_header_cells(cells: list) -> list | None:
    """Map header cells to column keys like 'accidents_2023'.

    Returns a list aligned with `cells` (None for unmappable cells), or None
    when fewer than 2 cells map — i.e. we are not confident.
    """
    out, mapped = [], 0
    for c in cells:
        t = (c or "").lower()
        key = None
        for kw, metric in _METRIC_KEYWORDS:
            if kw in t:
                ym = re.search(r"(19|20)\d{2}", t)
                key = f"{metric}_{ym.group(0)}" if ym else metric
                break
        if key:
            mapped += 1
        out.append(key)
    return out if mapped >= 2 else None


def _row_from_cells(cells: list, page_no: int, title, header_keys=None) -> TableRow | None:
    cells = [(c or "").strip() for c in cells]
    cells = [c for c in cells if c != ""]
    if len(cells) < 4:
        return None
    i = 0
    # optional serial number cell
    v0 = parse_number_token(cells[0])
    if v0 is not None and isinstance(v0, int) and 0 < v0 <= 500 and parse_number_token(cells[1]) is None:
        i = 1
    label_parts = []
    while i < len(cells) and parse_number_token(cells[i]) is None:
        label_parts.append(cells[i])
        i += 1
    values = []
    for c in cells[i:]:
        v = parse_number_token(c)
        if v is not None:
            values.append(v)
    label = " ".join(label_parts).strip(" .,:;")
    if not label or len(values) < 3:
        return None
    if normalize_label(label) in STOP_LABELS or len(label) > 60:
        return None
    columns = None
    if header_keys and len(header_keys) == len(cells):
        cols = {}
        for key, c in zip(header_keys, cells):
            if key:
                v = parse_number_token(c)
                if v is not None:
                    cols[key] = v
        if len(cols) >= 2:
            columns = cols
    return TableRow(page_no=page_no, row_label=label, values=values,
                    table_title=title, columns=columns)


def extract_with_find_tables(page, page_no: int, title) -> list:
    """find_tables() path. Returns [] on any failure — never raises."""
    try:
        finder = page.find_tables()
        tables = list(finder.tables) if finder else []
    except Exception:
        return []
    rows: list[TableRow] = []
    for tbl in tables:
        try:
            raw = tbl.extract()
        except Exception:
            continue
        if not raw:
            continue
        header_keys = None
        start = 0
        # Confidence bar for column mapping (empirically necessary on these
        # CorelDRAW reports): accept a mapping ONLY if every mapped key is
        # year-suffixed (e.g. 'killed_2023' from one header cell containing
        # both metric and year) and no header-area row contains bare year
        # cells. Two-level headers (metric row + separate year row) otherwise
        # collapse into plausible-looking but WRONG columns — keep values only.
        bare_year_header = any(
            re.fullmatch(r"(19|20)\d{2}", (c or "").strip())
            for r in raw[:3] for c in r
        )
        if not bare_year_header:
            for cand_rows in (1, 2):
                if len(raw) >= cand_rows:
                    combined = []
                    width = max(len(r) for r in raw[:cand_rows])
                    for ci in range(width):
                        parts = [(raw[ri][ci] or "") for ri in range(cand_rows) if ci < len(raw[ri])]
                        combined.append(" ".join(parts))
                    hk = map_header_cells(combined)
                    if hk and all(k is None or re.search(r"_(19|20)\d{2}$", k)
                                  for k in hk):
                        header_keys, start = hk, cand_rows
                        break
        for cells in raw[start:]:
            r = _row_from_cells(list(cells), page_no, title, header_keys)
            if r:
                rows.append(r)
    return rows


def pseudo_rows_from_lines(lines: list, page_no: int, title) -> list:
    """Fallback: parse table rows out of coordinate-sorted text lines."""
    rows: list[TableRow] = []
    for _y, line in lines:
        tokens = line.split()
        if len(tokens) < 5:
            continue
        i = 0
        v0 = parse_number_token(tokens[0])
        if (v0 is not None and isinstance(v0, int) and 0 < v0 <= 500
                and parse_number_token(tokens[1]) is None):
            i = 1
        label_tokens = []
        while i < len(tokens) and parse_number_token(tokens[i]) is None:
            label_tokens.append(tokens[i])
            i += 1
        rest = tokens[i:]
        if not label_tokens or len(rest) < 3:
            continue
        numeric, values = 0, []
        for t in rest:
            v = parse_number_token(t)
            if v is not None:
                numeric += 1
                values.append(v)
        # data rows are number-dense; narrative lines are not
        if numeric < 3 or numeric / max(len(rest), 1) < 0.8:
            continue
        label = " ".join(label_tokens).strip(" .,:;")
        norm = normalize_label(label)
        if not norm or norm in STOP_LABELS or "%" in label or len(label_tokens) > 6:
            continue
        if not any(ch.isalpha() for ch in label):
            continue
        rows.append(TableRow(page_no=page_no, row_label=label, values=values,
                             table_title=title, columns=None))
    return rows


def extract_page_rows(page, page_data, title, numeric_density_high: bool = True) -> list:
    """All table rows for one page, deduped by (label_norm, values)."""
    rows: list[TableRow] = []
    if numeric_density_high:
        rows.extend(extract_with_find_tables(page, page_data.page_no, title))
    rows.extend(pseudo_rows_from_lines(page_data.lines, page_data.page_no, title))
    seen, out = set(), []
    for r in rows:
        key = (normalize_label(r.row_label), tuple(r.values))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def count_numeric_tokens(text: str) -> int:
    return sum(1 for t in (text or "").split() if parse_number_token(t) is not None)


def should_run_table_scan(text: str) -> bool:
    return count_numeric_tokens(text) >= config.MIN_NUMBERS_FOR_TABLE_SCAN
