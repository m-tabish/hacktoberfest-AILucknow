"""Single source of truth for paths, model names and thresholds.

Paths can be overridden with the REPORT_NAVIGATOR_DATA_DIR env var (used by tests
to ingest into a temporary directory).
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # optional at import time; .env is a convenience, not a requirement
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = Path(os.environ.get("REPORT_NAVIGATOR_DATA_DIR", PROJECT_ROOT / "data"))
UPLOADS_DIR = DATA_DIR / "uploads"
PAGES_DIR = DATA_DIR / "pages"
INDEX_DIR = DATA_DIR / "index"
DB_PATH = DATA_DIR / "db" / "report.db"


def ensure_dirs() -> None:
    for d in (UPLOADS_DIR, PAGES_DIR, INDEX_DIR, DB_PATH.parent):
        d.mkdir(parents=True, exist_ok=True)


def doc_upload_path(doc_id: str) -> Path:
    return UPLOADS_DIR / f"{doc_id}.pdf"


def doc_pages_dir(doc_id: str) -> Path:
    return PAGES_DIR / doc_id


def doc_index_dir(doc_id: str) -> Path:
    return INDEX_DIR / doc_id


# --- LLM (OpenAI-compatible endpoint; swapped via .env only) ---
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
LLM_TIMEOUT_S = int(os.environ.get("LLM_TIMEOUT_S", "60"))

# --- Embeddings (optional; system runs BM25-only without them) ---
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
ENABLE_EMBEDDINGS = os.environ.get("ENABLE_EMBEDDINGS", "1") not in ("0", "false", "False")

# --- Ingestion ---
OCR_MIN_CHARS = 50          # pages with less native text than this are treated as scanned
OCR_DPI = 300
PAGE_RENDER_DPI = 150       # citation preview images
MIN_NUMBERS_FOR_TABLE_SCAN = 30  # only run find_tables() on number-dense pages (speed)

# --- Chunking ---
NARRATIVE_CHUNK_CHARS = 800
NARRATIVE_OVERLAP_CHARS = 120
PAGE_CHUNK_MAX_CHARS = 20000

# --- Retrieval / answering ---
RETRIEVAL_TOP_PAGES = int(os.environ.get("RETRIEVAL_TOP_PAGES", "5"))
LLM_CONTEXT_PAGES = 3
ENTITY_FUZZY_THRESHOLD = 85  # RapidFuzz score
NOT_FOUND = "NOT_FOUND"
