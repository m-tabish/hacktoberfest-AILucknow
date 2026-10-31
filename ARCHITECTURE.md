# Report Navigator (Problem 05) — Python System Architecture
Hacktoberfest Hack Day Lucknow · Team of 2 · Build deadline 4:00 PM IST, Oct 31, 2026
Dataset: github.com/CodewithJha/hack-day-lucknow-datasets → `p5-report-qa-rag/`

## 0. What the system actually has to do (from the real dataset)

- Public data: `report_A.pdf` (272 pages, Road Accidents in India 2023), 50 example questions.
  45 answers are a **single integer** (no commas), 5 are `NOT_FOUND`.
- Submission format (`sample_answers.jsonl`), one JSON per line:
  `{"id": "P000", "answer": "351", "page": 101, "confidence": 0.9}`
- **Hidden evaluation:** a DIFFERENT report (same family, different year, some pages are
  scanned images with no text layer) + 140 new questions.
  → The pipeline must ingest *any* new PDF at runtime. No hardcoded answers, cities, or pages.
- `gold_pages` are **PDF page numbers** (1-indexed). The printed footer number is ~24 less.
  Always output the PDF page number.
- This PDF is CorelDRAW-generated: plain `get_text()` scrambles reading order, table titles /
  headers extract at the end of a page, and continued tables ("Contd...") carry their headers
  on earlier pages. → Page-level retrieval + coordinate-sorted extraction, not small-chunk RAG.

> **Implementation notes (as built in this repo)** — the design below is the
> reference architecture; the shipped code deviates in four deliberate ways for
> reliability on hack day:
> 1. **BM25 is a custom pure-Python implementation** (`src/qa/hybrid_search.py`) — no `rank-bm25` dependency.
> 2. **LLM client uses stdlib `urllib`** against any OpenAI-compatible endpoint — no `openai` package. With no `LLM_API_KEY`, cell-lookup/abstain paths still answer and LLM-path questions get a clear low-confidence fallback.
> 3. **Core requirements are lean** (`pymupdf, streamlit, python-dotenv, rapidfuzz, pandas`). Embeddings/FAISS/OCR deps live in `requirements-optional.txt` and are lazy-imported — the system runs BM25-only without them.
> 4. **Dataclasses instead of pydantic** (`src/models.py`), and table extraction is `find_tables()` first with a **pseudo-row fallback** parsed from coordinate-sorted lines; `columns_json` is only stored when a header row maps confidently, `values_json` is always stored.

---

## 1. High-level architecture

```
                        ┌─────────────────────────────────────────────┐
                        │            Streamlit Dashboard               │
                        │  Tab 1: Chat (with citations)                │
                        │  Tab 2: Batch Run + Evaluation               │
                        │  Sidebar: Upload PDF / Ingestion status      │
                        └──────────────┬──────────────────────────────┘
                                       │ direct Python calls (no separate API server)
                        ┌──────────────▼──────────────────────────────┐
                        │              Service layer                   │
                        │   chat_service.py   ·   batch_service.py     │
                        └──────┬───────────────────────────┬──────────┘
                               │                           │
                ┌──────────────▼─────────────┐  ┌──────────▼────────────────┐
                │        QA / Retrieval       │  │        Ingestion           │
                │  entity extract (RapidFuzz) │  │  pdf_loader → ocr          │
                │  cell_lookup (SQL, exact)   │  │  → table_extract           │
                │  hybrid_search (BM25+FAISS) │  │  → chunker → embedder      │
                │  llm_answer (JSON out)      │  │  → indexer                 │
                │  validator (int / NOT_FOUND)│  │                            │
                └──────┬──────────────────────┘  └──────────┬────────────────┘
                       │                                    │
                ┌──────▼────────────────────────────────────▼───────────┐
                │                     STORAGE                          │
                │  SQLite (report.db)  ·  FAISS index files            │
                │  BM25 pickle  ·  data/uploads/<doc_id>.pdf           │
                │  data/pages/<doc_id>/page_XXX.png (citation preview) │
                └──────────────────────────────────────────────────────┘
                                       │
                                LLM API (OpenAI-compatible:
                                Groq / OpenAI / Meta Model API)
```

Design rule: **deterministic first, LLM second.**
If a table cell can be found by exact SQL lookup, never ask the LLM to guess it.

---

## 2. Tech stack / libraries

| Purpose | Library | Why this one |
|---|---|---|
| PDF text + words + page images | `PyMuPDF` (`import fitz` / `pymupdf`) | Fast, coordinate data (`get_text("words")`), `find_tables()`, `get_pixmap()` for page renders + OCR input |
| PDF table backup check | `pdfplumber` | Cross-check `find_tables()` results on a few pages; not the primary path |
| OCR (scanned pages) | `pytesseract` + `Pillow` + system `tesseract` binary | Only for pages with < 50 chars of native text |
| Embeddings | `sentence-transformers` with `BAAI/bge-small-en-v1.5` | Local, free, no API-key failure in demo. Fallback: `all-MiniLM-L6-v2` |
| Vector search | `faiss-cpu` | One file per document, zero server setup |
| Keyword search | `rank-bm25` | Exact city/state names — embeddings alone confuse Pune's 4 numbers on one page |
| Fuzzy entity match | `rapidfuzz` | "Vadodra" vs "Vadodara", "Allahabad (Prayagraj)" aliases |
| Structured / tabular data | **SQLite via stdlib `sqlite3`** (+ `pandas` for debugging views) | Single file, no server, perfect at this scale. See §4 |
| LLM calls | `openai` Python client pointed at any OpenAI-compatible base URL | Swap Groq / OpenAI / Meta by changing `.env` only |
| Output validation | `pydantic` | Force LLM output into `{answer, page, confidence}` schema |
| UI | `streamlit` | Chat UI, file upload, progress, tables — fastest for 2 people in ~5 hrs |
| Config | `python-dotenv` | API keys / model names in `.env`, never in code |
| Numbers parsing | stdlib `re` | Strip commas (Indian format `1,72,890` → `172890`), extract integers |

**Explicitly NOT used:** LangChain / LlamaIndex (debugging overhead), Postgres / Chroma server /
Elasticsearch (setup cost), React / FastAPI as a separate tier (structure the code so FastAPI
can wrap the service layer later, but Streamlit calls services directly today).

`requirements.txt`:
```
pymupdf
pdfplumber
pytesseract
Pillow
sentence-transformers
faiss-cpu
rank-bm25
rapidfuzz
pandas
openai
pydantic
streamlit
python-dotenv
```
System dependency: `tesseract` binary (`apt install tesseract-ocr` / `brew install tesseract`).

---

## 3. File / folder structure

```
report-navigator/
├── README.md
├── ARCHITECTURE.md            # this document
├── requirements.txt
├── .env.example               # LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, EMBEDDING_MODEL
│
├── app.py                     # Streamlit entry point ONLY (UI, no business logic)
├── run_batch.py               # CLI: python run_batch.py --pdf X.pdf --questions Q.jsonl --out answers.jsonl
├── evaluate.py                # CLI: score answers.jsonl vs questions_with_answers.jsonl
│
├── src/
│   ├── config.py              # paths, model names, thresholds (single source of truth)
│   ├── db.py                  # SQLite connection + schema creation + all SQL queries
│   ├── models.py              # pydantic / dataclasses: Document, Page, Chunk, TableRow, Answer
│   │
│   ├── ingest/
│   │   ├── pdf_loader.py      # open PDF, per-page words sorted by (y, x), page PNG render
│   │   ├── ocr.py             # is_scanned(page_text) -> OCR via pytesseract at 300 dpi
│   │   ├── table_extract.py   # find_tables() -> rows; header carry-over for "Contd..." pages
│   │   ├── chunker.py         # builds 3 chunk types (see §5)
│   │   ├── normalize.py       # number parsing, entity/name normalisation, text cleaning
│   │   └── indexer.py         # embeddings -> FAISS file, BM25 -> pickle, rows -> SQLite
│   │
│   ├── qa/
│   │   ├── entity.py          # extract entity + metric + year from a question (keywords + RapidFuzz vs row_labels)
│   │   ├── cell_lookup.py     # deterministic SQL lookup: row_label + column -> value_int
│   │   ├── hybrid_search.py   # BM25 + FAISS over chunks, merged + reranked, returns candidate PAGES
│   │   ├── llm_client.py      # OpenAI-compatible client wrapper (one place that calls the model)
│   │   ├── prompts.py         # the strict JSON-answer prompt (versioned string constant)
│   │   ├── answerer.py        # orchestrates: cell_lookup -> hybrid_search -> LLM -> validator
│   │   └── validator.py       # integer / NOT_FOUND checks, comma stripping, confidence rules
│   │
│   └── services/
│       ├── ingest_service.py  # upload -> hash -> ingest pipeline, with progress callback for UI
│       ├── chat_service.py    # one question -> Answer + citations + source chunks + page image path
│       └── batch_service.py   # many questions -> answers.jsonl + evaluation summary
│
├── data/                      # .gitignore everything in here
│   ├── uploads/               # <doc_id>.pdf  (doc_id = first 12 chars of SHA-256 of file)
│   ├── pages/<doc_id>/        # page_001.png ... rendered once at ingestion for citations / OCR
│   ├── index/<doc_id>/        # chunks.faiss + bm25.pkl
│   └── db/report.db           # the single SQLite file
│
└── tests/
    ├── test_normalize.py      # "1,72,890" -> 172890, "NOT_FOUND" handling
    └── test_gold_smoke.py     # Pune killed 2023 = 351 p101, Pune accidents 2023 = 1230 p101
```

Work split: **Dev 1** = `ingest/` + `db.py` + `indexer.py`. **Dev 2** = `qa/` + `app.py` +
`evaluate.py`. Contract between them = the SQLite schema (§4) + `models.py`. Agree those first.

---

## 4. Storage design — yes, SQLite (plus FAISS files)

SQLite is the right call at this scale (272 pages, a few thousand rows). No server, one file,
easy to inspect with `pandas.read_sql`. Vectors do NOT go in SQLite — they go in FAISS, and
SQLite stores the mapping `chunk_id -> faiss position`.

### SQLite schema

```sql
CREATE TABLE documents (
    doc_id        TEXT PRIMARY KEY,       -- sha256[:12]
    filename      TEXT,
    num_pages     INTEGER,
    ingested_at   TEXT,                   -- ISO timestamp
    ocr_pages     INTEGER,                -- how many pages needed OCR
    status        TEXT                    -- 'ready' | 'ingesting' | 'failed'
);

CREATE TABLE pages (
    doc_id        TEXT,
    page_no       INTEGER,                -- PDF page number, 1-indexed  <-- cite THIS
    printed_no    INTEGER,                -- footer number if detected (never cite this)
    raw_text      TEXT,                   -- coordinate-sorted text
    is_scanned    INTEGER,                -- 1 if OCR was used
    image_path    TEXT,                   -- data/pages/<doc_id>/page_XXX.png
    PRIMARY KEY (doc_id, page_no)
);

-- Three chunk types in one table, distinguished by chunk_type (see §5)
CREATE TABLE chunks (
    chunk_id      INTEGER PRIMARY KEY,
    doc_id        TEXT,
    page_no       INTEGER,
    chunk_type    TEXT,                   -- 'page' | 'narrative' | 'table_row'
    text          TEXT,                   -- text that gets embedded / shown as citation
    faiss_pos     INTEGER                 -- row number in the FAISS index, NULL for 'page' chunks
);

-- THE numbers table. One extracted table = many rows. This is what makes exact answers possible.
CREATE TABLE table_rows (
    row_id        INTEGER PRIMARY KEY,
    doc_id        TEXT,
    page_no       INTEGER,
    table_title   TEXT,                   -- e.g. 'Table 6.2: ... Million Plus Cities' (may come from prev page)
    row_label     TEXT,                   -- e.g. 'Pune', 'Maharashtra', 'Run off Road'
    row_label_norm TEXT,                  -- lowercased, punctuation stripped — for matching
    columns_json  TEXT,                   -- {"accidents_2022": 1029, "accidents_2023": 1007, ...}
    values_json   TEXT                    -- ordered raw values as extracted, fallback if headers unclear
);

CREATE TABLE qa_log (
    id            INTEGER PRIMARY KEY,
    doc_id        TEXT,
    question      TEXT,
    answer        TEXT,                   -- integer string or 'NOT_FOUND'
    page          INTEGER,
    confidence    REAL,
    source        TEXT,                   -- 'cell_lookup' | 'llm' | 'abstain'
    created_at    TEXT
);
CREATE INDEX idx_rows_norm ON table_rows(doc_id, row_label_norm);
CREATE INDEX idx_chunks_page ON chunks(doc_id, page_no);
```

### How a number in a table is stored — example (page 101, Table 6.2 pattern)

Extracted row (12 numbers per city) becomes:
```json
{
  "doc_id": "a1b2c3d4e5f6", "page_no": 101, "table_title": "Table 6.2 ... Million Plus Cities",
  "row_label": "Pune", "row_label_norm": "pune",
  "columns_json": {"accidents_2022": null, "accidents_2023": 1230, "killed_2023": 351, "injured_2023": null}
}
```
Header names come from the table's header row; when the header is ambiguous, keep the ordered
`values_json` too and let the LLM path handle that page. Never throw the raw row away.

**Files on disk (not in SQLite):** original PDF, per-page PNGs, `chunks.faiss`, `bm25.pkl` —
all keyed by `doc_id`, so ingesting the hidden report creates a parallel set and never
overwrites Report A. Switching documents = switching `doc_id`.

---

## 5. Chunking strategy (3 chunk types — this replaces generic 700-char chunking)

1. **`page` chunk (not embedded, used as LLM context):** the full coordinate-sorted text of one
   page. Retrieval ultimately returns *pages*, and the LLM reads a whole page.
2. **`narrative` chunks (embedded):** narrative paragraphs split at ~600–800 chars with
   100-char overlap, never crossing a page boundary. For text/fact questions.
3. **`table_row` chunks (embedded + in SQLite):** one per table row, with header context
   injected into the text so the row is self-describing, e.g.:
   `"[Page 101 | Table 6.2 Million Plus Cities] Pune — Accidents 2023: 1230; Killed 2023: 351; Injured 2023: ..."`
   This is the single most important chunk type for this dataset.

---

## 6. How a NEW PDF is ingested (the hidden report)

Triggered identically from the dashboard sidebar upload or from `run_batch.py --pdf`.

```
1. Save upload -> compute SHA-256 -> doc_id = hash[:12]
   If doc_id already in `documents` with status='ready': reuse index, skip to QA. (Idempotent)
2. INSERT documents row, status='ingesting'. Streamlit shows st.progress per stage.
3. FOR each PDF page (PyMuPDF):
   a. words = page.get_text("words") sorted by (round(y), x)   -> raw_text in reading order
   b. render page PNG at 200 dpi -> data/pages/<doc_id>/page_XXX.png
   c. IF len(raw_text) < 50 chars AND page contains an image:
        is_scanned=1 -> re-render at 300 dpi -> pytesseract OCR -> raw_text = OCR text
   d. tables = page.find_tables() -> for each table: extract rows,
      attach table_title (search page + previous page for 'Table X.Y' / 'Annexure N'),
      IF page text contains 'Contd'/'Concld': inherit header row from the table's first page
   e. INSERT pages row, INSERT table_rows (values parsed by normalize.py)
4. Build chunks (3 types, §5) -> INSERT chunks
5. Embed narrative + table_row chunks (bge-small, batched) -> FAISS index -> chunks.faiss
   + write faiss_pos back into chunks table
6. Build BM25 over the same chunk texts -> bm25.pkl
7. UPDATE documents SET status='ready', ocr_pages=<count>
8. Ingestion report shown in UI: pages, scanned/OCR pages, tables found, table rows, chunks
```

Expected time: 272 pages ≈ 1–3 min on a laptop (OCR pages are the slow part — OCR only the
low-text pages, never the whole book).

---

## 7. Answering a question (chat and batch use the same `answerer.py`)

```
1. entity.py:  question -> {entity: "Pune", metric: "killed", year: 2023}
   - metric from keyword map: deaths/killed/fatalities -> killed; injured -> injured;
     accidents -> accidents; two-wheeler / pedestrian / over-speeding -> specialised tables
   - entity by RapidFuzz match against DISTINCT row_label_norm in table_rows for this doc_id
2. cell_lookup.py (deterministic, try FIRST):
   SELECT * FROM table_rows WHERE doc_id=? AND row_label_norm=?
   -> if the row has the requested column: answer = that value, confidence = 0.95, source='cell_lookup'
3. hybrid_search.py (if no exact cell):
   BM25 top-10 chunks + FAISS top-10 chunks -> merge, rerank by
   (contains entity) + (contains metric word) -> candidate PAGES (top 3, deduped)
4. Abstain check: if entity appears in NO chunk/page of this document
   -> answer = "NOT_FOUND", page = 0, confidence = 0.8, source='abstain'  (do not call the LLM)
5. llm: send full text of candidate pages (each labelled [PDF Page N]) + strict prompt:
   "Answer with a single integer from the context, or NOT_FOUND. No commas.
    Return ONLY JSON: {"answer": "...", "page": N, "confidence": 0..1}"
6. validator.py: strip commas, require ^\d+$ or NOT_FOUND, page must be one of the candidate
   pages, clamp confidence. If validation fails once -> retry LLM once -> else NOT_FOUND / low confidence.
7. INSERT qa_log; return Answer + the exact chunk(s)/row used (for citations in UI)
```

Confidence rules (simple, explainable to judges):
`cell_lookup` = 0.95 · LLM answer whose value literally appears in the cited page text = 0.85 ·
LLM semantic-only = 0.6 · abstain with entity absent everywhere = 0.8 · abstain on weak retrieval = 0.4.

Batch mode: loop steps 1–7 over a questions `.jsonl`, write `answers.jsonl` in the sample
format. `evaluate.py` compares against gold: exact-match %, page accuracy %, NOT_FOUND precision/recall.

---

## 8. Chat dashboard (Streamlit) — with citations, yes

Layout (single page, two tabs):

```
┌──────────────────────┬────────────────────────────────────────────────────┐
│ SIDEBAR              │  TAB 1: CHAT                                       │
│ ┌──────────────────┐ │  ┌──────────────────────────────────────────────┐  │
│ │ Upload report PDF│ │  │ You: How many road accident deaths in Pune   │  │
│ │ [ report_B.pdf ] │ │  │      city in 2023?                           │  │
│ └──────────────────┘ │  │                                              │  │
│ Status: ● Ready      │  │ Assistant:                                   │  │
│ Pages: 272           │  │ ┌──────────────────────────────────────────┐ │  │
│ OCR pages: 6         │  │ │ 351                                      │ │  │
│ Tables: 84 · Rows:.. │  │ │ [📄 Page 101]  Confidence: 0.95 ●●●●○     │ │  │
│ Chunks: 3,412        │  │ │ Source: Table 6.2 — Million Plus Cities  │ │  │
│                      │  │ └──────────────────────────────────────────┘ │  │
│ Document: [Report A▾]│  │ ▸ View source passage / table row            │  │
│ [ Re-ingest ]        │  │ ▸ View page image                            │  │
│                      │  │                                              │  │
│ ── Batch ──          │  │ [ Ask a question about the report... ] [➤]   │  │
│ Upload questions.jsonl│ └──────────────────────────────────────────────┘  │
│ [ Run batch ]        │  TAB 2: BATCH + EVALUATION                         │
│ Download answers.jsonl│  st.dataframe of id/question/answer/page/conf    │
│                      │  If gold provided: Exact match 62% · Page acc 78%  │
└──────────────────────┴────────────────────────────────────────────────────┘
```

Citation behaviour (the part judges check):
- Every answer shows a **citation chip `[Page 101]`** = PDF page number.
- **"View source passage"** expander: the exact `table_row` / chunk text the answer came from,
  with the answer value highlighted (`st.markdown` with `<mark>`).
- **"View page image"** expander: the stored page PNG (`st.image`). Stretch goal: draw the
  row's bounding box on the PNG with PyMuPDF before display.
- `NOT_FOUND` answers render distinctly: grey card, "Not found in the report", confidence shown,
  plus the note "entity searched across all N pages".
- Chat history in `st.session_state.messages`; each assistant message stores its Answer object
  (answer, page, confidence, sources) so expanders survive reruns.
- Sidebar ingestion: `st.file_uploader` → ingest_service with `st.progress` per stage →
  stats via `st.metric` (pages / OCR pages / tables / chunks) read from SQLite.

Streamlit building blocks used: `st.sidebar`, `st.tabs`, `st.chat_message`, `st.chat_input`,
`st.file_uploader`, `st.progress`, `st.expander`, `st.image`, `st.dataframe`, `st.metric`,
`st.download_button` (answers.jsonl), `st.session_state`, `@st.cache_resource` for the
embedding model + FAISS index (load once, not per question).

---

## 9. .env.example

```
LLM_API_KEY=
LLM_BASE_URL=https://api.groq.com/openai/v1     # or OpenAI / Meta Model API endpoint
LLM_MODEL=llama-3.3-70b-versatile               # or gpt-4o-mini
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RETRIEVAL_TOP_PAGES=3
ABSTAIN_BM25_THRESHOLD=...  # tune on the 50 gold questions
```

## 10. Build order to 4 PM

1. `db.py` schema + `normalize.py` + smoke test (Pune = 351 / 1230, page 101) — agree schema first.
2. Ingestion for Report A (skip OCR initially) → verify counts in UI / SQLite.
3. `cell_lookup` + `hybrid_search` + LLM answerer → `run_batch.py` on the 50 → `evaluate.py` score.
4. Streamlit chat tab with citations (wire `chat_service`).
5. OCR branch for low-text pages.
6. Batch tab + download; freeze; rehearse demo (1 table number, 1 text fact, 1 NOT_FOUND).
