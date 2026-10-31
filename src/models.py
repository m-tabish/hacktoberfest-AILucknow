"""Plain dataclasses shared by every module (the Dev1/Dev2 contract).

Kept dependency-free on purpose: pydantic was in the original architecture doc
but dataclasses cover everything needed here and keep requirements lean.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Document:
    doc_id: str
    filename: str
    num_pages: int = 0
    ocr_pages: int = 0
    status: str = "ingesting"  # 'ready' | 'ingesting' | 'failed'


@dataclass
class PageData:
    page_no: int                      # PDF page number, 1-indexed — cite THIS
    raw_text: str = ""                # coordinate-sorted text
    lines: list = field(default_factory=list)  # [(y, line_text)] in reading order
    has_image: bool = False
    is_scanned: int = 0
    printed_no: Optional[int] = None  # footer number if detected — never cite
    image_path: Optional[str] = None


@dataclass
class Chunk:
    page_no: int
    chunk_type: str                   # 'page' | 'narrative' | 'table_row'
    text: str
    chunk_id: Optional[int] = None
    faiss_pos: Optional[int] = None


@dataclass
class TableRow:
    page_no: int
    row_label: str
    values: list = field(default_factory=list)   # ordered parsed numbers (int/float)
    table_title: Optional[str] = None
    columns: Optional[dict] = None               # only when a header row mapped confidently
    row_id: Optional[int] = None

    @property
    def row_label_norm(self) -> str:
        from src.ingest.normalize import normalize_label

        return normalize_label(self.row_label)


@dataclass
class QuestionContext:
    entity: Optional[str] = None          # original label, e.g. 'Pune'
    entity_norm: Optional[str] = None
    metric: Optional[str] = None          # 'killed' | 'injured' | 'accidents' | special keys
    year: Optional[int] = None
    raw_question: str = ""


@dataclass
class Answer:
    answer: str                           # integer string without commas, or 'NOT_FOUND'
    page: int = 0                         # PDF page number; 0 for NOT_FOUND
    confidence: float = 0.0
    source: str = "llm"                   # 'cell_lookup' | 'llm' | 'abstain' | 'no_llm_fallback'
    sources: list = field(default_factory=list)  # chunk texts used (citations in UI)
    page_image: Optional[str] = None
    note: str = ""
    qid: Optional[str] = None
    llm_trace: Optional[dict] = None

    def to_submission_dict(self) -> dict:
        return {
            "id": self.qid,
            "answer": self.answer,
            "page": int(self.page or 0),
            "confidence": round(float(self.confidence), 2),
        }
