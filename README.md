# Report Navigator — Problem 05, Hacktoberfest Hack Day Lucknow

A RAG system that answers questions about a long government statistics report
and **cites the PDF page** every answer comes from. Built for the hidden
evaluation setup: it ingests *any* new report PDF at runtime (including pages
that are scanned images) and answers a fresh set of questions — nothing about
the public report is hardcoded.

Public dataset (`p5-report-qa-rag`): `report_A.pdf` (272 pages, *Road
Accidents in India 2023*), 50 example questions — 45 answers are a single
integer count, 5 are `NOT_FOUND`. Hidden evaluation uses a different report
of the same family + 140 new questions.

## How it works (30 seconds)

1. **Ingest** — PyMuPDF extracts coordinate-sorted text per page (plain
   extraction scrambles these CorelDRAW PDFs), OCR fills in scanned pages,
   tables become structured rows in **SQLite**, and text becomes three chunk
   types (`page`, `narrative`, `table_row`) indexed with a pure-Python BM25
   (+ optional FAISS embeddings).
2. **Answer** — deterministic first, LLM second:
   entity+metric extraction → exact SQL cell lookup → hybrid BM25/FAISS
   retrieval to candidate **pages** → abstain if the entity appears nowhere →
   LLM reads the full candidate pages and returns strict JSON → validator
   enforces integer-or-`NOT_FOUND`, correct page, and confidence rules.
3. **Cite** — every answer carries its PDF page number (not the printed
   footer number), the exact source passage/row, and the page image.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

## Quickstart

```bash
pip install -r requirements.txt            # lean core
pip install -r requirements-optional.txt   # optional: embeddings + OCR (also needs `tesseract` binary)
cp .env.example .env                       # add LLM_API_KEY for full QA (Groq/OpenAI/Meta-compatible)
```

### Chat dashboard

```bash
streamlit run app.py
```

Upload a report PDF in the sidebar, ingest, then chat (Tab 1) or run a batch
of questions (Tab 2).

### Batch (the submission path)

```bash
python run_batch.py --pdf report_A.pdf --questions questions.jsonl --out answers.jsonl
python evaluate.py --answers answers.jsonl --gold questions_with_answers.jsonl
```

Output format, one JSON per line:

```json
{"id": "P000", "answer": "351", "page": 101, "confidence": 0.95}
```

`answer` is an integer string **without commas**, or `NOT_FOUND`;
`page` is the **PDF page number** (1-indexed).

### Without an LLM key

The system still runs: cell-lookup and abstain (`NOT_FOUND`) questions are
answered deterministically, retrieval works BM25-only, and LLM-dependent
questions return a clear low-confidence fallback naming the top candidate
page instead of guessing.

## Tests

```bash
python tests/test_normalize.py     # number/label/validator units
python tests/test_gold_smoke.py    # end-to-end on Report A: ingestion counts,
                                   # Pune row on p101, retrieval finds p101
```

## Layout

```
app.py · run_batch.py · evaluate.py     # entry points (UI / batch / scoring)
src/config.py · db.py · models.py       # settings, SQLite schema+queries, dataclasses
src/ingest/   pdf_loader, ocr, table_extract, chunker, normalize, indexer
src/qa/       entity, cell_lookup, hybrid_search, llm_client, prompts, answerer, validator
src/services/ ingest_service, chat_service, batch_service
data/         uploads/ pages/ index/ db/report.db   (gitignored, per-document)
```
