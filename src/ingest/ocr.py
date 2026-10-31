"""OCR fallback for scanned pages (no text layer).

Optional: if pytesseract / Pillow / the tesseract binary are missing, OCR
silently returns "" and ingestion continues with the (empty) native text.
"""
from __future__ import annotations

import io

from src import config


def needs_ocr(raw_text: str) -> bool:
    return len((raw_text or "").strip()) < config.OCR_MIN_CHARS


def ocr_page(page, dpi: int = config.OCR_DPI) -> str:
    """OCR one PyMuPDF page. Returns '' on any failure — never raises."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return ""
    try:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img) or ""
    except Exception:
        return ""
