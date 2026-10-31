#!/usr/bin/env python3
"""Report Navigator — REST API (FastAPI) for programmatic / judge access.

Thin wrapper over src/services, the same functions the Streamlit UI calls.
Run from the project root:
  uvicorn api:app --host 0.0.0.0 --port 8000
Swagger UI: http://localhost:8000/docs · OpenAPI schema: /openapi.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Literal, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from src import config, db
from src.services import batch_service, chat_service, document_service, ingest_service

app = FastAPI(
    title="Report Navigator API",
    version="1.0.0",
    description=(
        "Question answering over long statistics-report PDFs, with page citations.\n\n"
        "**Typical flow**\n"
        "1. `POST /documents` with the PDF → returns `doc_id` (ingestion runs in the "
        "background; a 272-page report takes a few minutes).\n"
        "2. Poll `GET /documents/{doc_id}` until `status` is `ready`.\n"
        "3. `POST /documents/{doc_id}/ask` for one question, or "
        "`POST /documents/{doc_id}/batch` for many (submission format).\n\n"
        "Answers are an integer string without commas, or `NOT_FOUND`. `page` is the "
        "1-indexed **PDF** page number (0 for `NOT_FOUND`). No authentication."
    ),
)

# In-memory progress for ingestions started by this process: {doc_id: {...}}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ------------------------------------------------------------------ schemas
class DocumentStatus(BaseModel):
    doc_id: str = Field(examples=["3b61a3244ccc"])
    filename: Optional[str] = None
    status: Literal["ingesting", "ready", "failed", "interrupted"] = Field(
        description="`interrupted` = ingestion was cut off by a server restart; re-upload.")
    num_pages: Optional[int] = None
    ingested_at: Optional[str] = None
    progress: float = Field(description="0.0–1.0")
    message: Optional[str] = Field(None, description="Current step, or the error if failed.")
    pages: int = 0
    chunks: int = 0
    table_rows: int = 0
    tables: int = Field(0, description="Pages containing extracted table rows.")
    ocr_pages: int = 0


class AskRequest(BaseModel):
    question: str = Field(examples=["How many people were killed in road accidents in Pune?"])
    include_trace: bool = Field(False, description="Include the raw LLM request/response trace.")


class AskResponse(BaseModel):
    answer: str = Field(description="Integer string without commas, or `NOT_FOUND`.",
                        examples=["351"])
    page: int = Field(description="1-indexed PDF page; 0 for NOT_FOUND.", examples=[101])
    confidence: float = Field(examples=[0.9])
    source: str = Field(description="How it was answered: "
                                    "`cell_lookup` | `llm` | `abstain` | `no_llm_fallback`.")
    sources: list[str] = Field(description="Source passages / table rows used as evidence.")
    page_image_url: Optional[str] = Field(
        None, description="Relative URL of the cited page image.")
    note: str = ""
    llm_trace: Optional[dict] = None


class BatchQuestion(BaseModel):
    id: str = Field(examples=["P000"])
    question: str = Field(examples=["How many people were killed in road accidents in Pune?"])


class BatchRequest(BaseModel):
    questions: list[BatchQuestion]


class SubmissionAnswer(BaseModel):
    id: Optional[str] = Field(examples=["P000"])
    answer: str = Field(examples=["351"])
    page: int = Field(examples=[101])
    confidence: float = Field(examples=[0.9])


class BatchResponse(BaseModel):
    answers: list[SubmissionAnswer]


class Health(BaseModel):
    status: str
    llm_configured: bool
    llm_model: str
    embeddings_enabled: bool


# ------------------------------------------------------------------ helpers
def _get_document(doc_id: str) -> Optional[dict]:
    conn = db.connect()
    try:
        db.init_db(conn)
        return db.get_document(conn, doc_id)
    finally:
        conn.close()


def _status(doc_id: str) -> DocumentStatus:
    if not re.fullmatch(r"[0-9a-f]{12}", doc_id):
        raise HTTPException(422, "doc_id must be 12 lowercase hex characters")
    with _jobs_lock:
        job = dict(_jobs.get(doc_id) or {})
    stats = chat_service.document_stats(doc_id)
    doc = stats.pop("document") or {}
    if not doc and not job:
        raise HTTPException(404, f"Document {doc_id} not found")
    status = job.get("status") or doc.get("status") or "ingesting"
    if status == "ingesting" and not job:
        status = "interrupted"
    progress = 1.0 if status == "ready" else job.get("progress", 0.0)
    return DocumentStatus(
        doc_id=doc_id, filename=doc.get("filename") or job.get("filename"), status=status,
        num_pages=doc.get("num_pages"), ingested_at=doc.get("ingested_at"),
        progress=round(progress, 3), message=job.get("message"), **stats)


def _require_ready(doc_id: str) -> None:
    st = _status(doc_id)
    if st.status != "ready":
        raise HTTPException(409, f"Document {doc_id} is not ready (status: {st.status})")


def _run_ingest(doc_id: str, tmp_path: str, filename: str, force: bool) -> None:
    def _progress(frac, msg):
        with _jobs_lock:
            _jobs[doc_id].update(progress=min(max(frac, 0.0), 1.0), message=msg)

    try:
        ingest_service.ingest_pdf(tmp_path, original_filename=filename,
                                  progress=_progress, force=force)
        with _jobs_lock:
            _jobs[doc_id].update(status="ready", progress=1.0, message="Done")
    except Exception as exc:
        conn = db.connect()
        try:
            db.update_document_status(conn, doc_id, "failed")
        finally:
            conn.close()
        with _jobs_lock:
            _jobs[doc_id].update(status="failed", message=f"{type(exc).__name__}: {exc}")
    finally:
        os.unlink(tmp_path)


def _answer_dict(doc_id: str, ans, include_trace: bool) -> AskResponse:
    return AskResponse(
        answer=ans.answer, page=int(ans.page or 0), confidence=round(float(ans.confidence), 2),
        source=ans.source, sources=[str(s) for s in ans.sources or []],
        page_image_url=(f"/documents/{doc_id}/pages/{ans.page}/image"
                        if ans.page_image and ans.page else None),
        note=ans.note or "", llm_trace=ans.llm_trace if include_trace else None)


# ------------------------------------------------------------------ routes
@app.get("/health", response_model=Health, tags=["system"])
def health():
    return Health(status="ok", llm_configured=bool(config.LLM_API_KEY),
                  llm_model=config.LLM_MODEL, embeddings_enabled=config.ENABLE_EMBEDDINGS)


@app.post("/documents", response_model=DocumentStatus, status_code=202, tags=["documents"],
          summary="Upload a report PDF and start ingestion",
          responses={200: {"model": DocumentStatus,
                           "description": "Same PDF already ingested; reused."}})
def upload_document(background: BackgroundTasks,
                    file: UploadFile = File(..., description="Report PDF"),
                    force: bool = Query(False, description="Re-ingest even if already ready.")):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Upload a .pdf file")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        while chunk := file.file.read(1 << 20):
            tmp.write(chunk)
        tmp_path = tmp.name
    doc_id = ingest_service.file_doc_id(tmp_path)

    with _jobs_lock:
        running = _jobs.get(doc_id, {}).get("status") == "ingesting"
        if not running:
            existing = _get_document(doc_id)
            reuse = existing and existing["status"] == "ready" and not force
            if not reuse:
                _jobs[doc_id] = {"status": "ingesting", "progress": 0.0,
                                 "message": "Queued", "filename": file.filename}
    if running or reuse:
        os.unlink(tmp_path)
        st = _status(doc_id)
        if reuse:
            return JSONResponse(st.model_dump(), status_code=200)
        return st
    background.add_task(_run_ingest, doc_id, tmp_path, file.filename, force)
    return _status(doc_id)


@app.get("/documents", response_model=list[DocumentStatus], tags=["documents"],
         summary="List ingested documents (newest first)")
def list_documents():
    conn = db.connect()
    try:
        db.init_db(conn)
        ids = [d["doc_id"] for d in db.list_documents(conn)]
    finally:
        conn.close()
    with _jobs_lock:
        ids += [j for j in _jobs if j not in ids]
    return [_status(i) for i in ids]


@app.get("/documents/{doc_id}", response_model=DocumentStatus, tags=["documents"],
         summary="Ingestion status, progress and stats")
def get_document(doc_id: str):
    return _status(doc_id)


@app.delete("/documents/{doc_id}", status_code=204, tags=["documents"],
            summary="Delete a document and all of its parsed data")
def delete_document(doc_id: str):
    if _status(doc_id).status == "ingesting":
        raise HTTPException(409, "Document is still ingesting")
    document_service.delete_document(doc_id)
    with _jobs_lock:
        _jobs.pop(doc_id, None)


@app.get("/documents/{doc_id}/pages/{page_no}/image", response_class=FileResponse,
         tags=["documents"], summary="Rendered PNG of a PDF page (for checking citations)",
         responses={200: {"content": {"image/png": {}}}})
def page_image(doc_id: str, page_no: int):
    _require_ready(doc_id)
    conn = db.connect()
    try:
        db.init_db(conn)
        page = db.get_page(conn, doc_id, page_no)
    finally:
        conn.close()
    if not page or not page.get("image_path") or not Path(page["image_path"]).exists():
        raise HTTPException(404, f"No image for page {page_no}")
    return FileResponse(page["image_path"], media_type="image/png")


@app.post("/documents/{doc_id}/ask", response_model=AskResponse, tags=["questions"],
          summary="Answer one question, with citations")
def ask(doc_id: str, req: AskRequest):
    _require_ready(doc_id)
    return _answer_dict(doc_id, chat_service.ask(doc_id, req.question), req.include_trace)


@app.post("/documents/{doc_id}/batch", response_model=BatchResponse, tags=["questions"],
          summary="Answer many questions (submission format)",
          description="Synchronous: allow ~5–10 s per question that needs the LLM.")
def batch(doc_id: str, req: BatchRequest):
    _require_ready(doc_id)
    questions = [q.model_dump() for q in req.questions]
    return BatchResponse(answers=batch_service.run_batch(doc_id, questions))


@app.post("/documents/{doc_id}/batch/jsonl", tags=["questions"],
          summary="Upload a questions .jsonl, get answers.jsonl back",
          description="Each input line: `{\"id\": ..., \"question\": ...}` (extra keys "
                      "ignored). Returns one `{\"id\",\"answer\",\"page\",\"confidence\"}` "
                      "per line.",
          response_class=PlainTextResponse,
          responses={200: {"content": {"application/x-ndjson": {}}}})
def batch_jsonl(doc_id: str, file: UploadFile = File(..., description="questions .jsonl")):
    _require_ready(doc_id)
    questions = []
    for n, line in enumerate(file.file.read().decode("utf-8").splitlines(), start=1):
        if line.strip():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                raise HTTPException(422, f"Line {n} is not valid JSON")
            questions.append({"id": d.get("id"), "question": d.get("question", "")})
    answers = batch_service.run_batch(doc_id, questions)
    return PlainTextResponse("\n".join(json.dumps(a) for a in answers) + "\n",
                             media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=answers.jsonl"})
