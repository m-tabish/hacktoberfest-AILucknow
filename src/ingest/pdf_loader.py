"""PDF loading with PyMuPDF: coordinate-sorted text, lines, page renders.

Plain page.get_text() scrambles reading order on CorelDRAW-generated reports
(table titles/headers land at the end of the page). Sorting words by (y, x)
and regrouping them into lines restores real reading order.
"""
from __future__ import annotations

from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # older installs expose only `fitz`
    import fitz  # type: ignore

from src import config
from src.ingest.normalize import clean_text, parse_int_token
from src.models import PageData

LINE_Y_TOLERANCE = 3.0  # points; words within this y distance are one line


def open_pdf(path: str | Path):
    return fitz.open(str(path))


def _sorted_lines(page) -> list:
    """[(y, line_text)] in reading order, built from word coordinates."""
    words = page.get_text("words")  # x0, y0, x1, y1, word, block, line, word_no
    words = sorted(words, key=lambda w: (round(w[1] / LINE_Y_TOLERANCE), w[0]))
    lines: list[list] = []  # [y, [word, ...]]
    for w in words:
        y = w[1]
        if lines and abs(y - lines[-1][0]) <= LINE_Y_TOLERANCE:
            lines[-1][1].append(w[4])
        else:
            lines.append([y, [w[4]]])
    return [(y, " ".join(ws)) for y, ws in lines]


def _detect_printed_no(page, lines) -> int | None:
    """Footer page number: last standalone integer near the bottom of the page."""
    try:
        height = page.rect.height
        words = page.get_text("words")
        candidates = []
        for w in words:
            if w[1] > height * 0.92:
                v = parse_int_token(w[4])
                if v is not None and 0 < v < 10000:
                    candidates.append((w[0], v))
        if candidates:
            candidates.sort()
            return candidates[-1][1]
    except Exception:
        pass
    return None


def page_has_image(page) -> bool:
    try:
        return len(page.get_images(full=True)) > 0
    except Exception:
        return False


def render_page_png(page, out_path: Path, dpi: int = config.PAGE_RENDER_DPI) -> str | None:
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix = page.get_pixmap(dpi=dpi)
        pix.save(str(out_path))
        return str(out_path)
    except Exception:
        return None


def load_page(page, page_no: int) -> PageData:
    """Extract one page (no OCR, no rendering — caller decides)."""
    lines = _sorted_lines(page)
    raw_text = clean_text("\n".join(t for _, t in lines))
    return PageData(
        page_no=page_no,
        raw_text=raw_text,
        lines=lines,
        has_image=page_has_image(page),
        printed_no=_detect_printed_no(page, lines),
    )
