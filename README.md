# Report Navigator — Problem 05, Hacktoberfest Hack Day Lucknow

## Judge Quick Start

**Problem statement:** Find exact answers to questions about long government statistics reports, cite the supporting PDF page, and return `NOT_FOUND` when the report does not contain the answer. The system must handle dense tables and scanned pages without relying on preloaded answers.

**Architecture:** FastAPI exposes document and question endpoints. PDF ingestion extracts page text and tables, applies OCR to scanned pages, and stores searchable content. BM25 retrieval (with optional FAISS embeddings) finds relevant pages; exact table lookup and a configured LLM produce validated answers with page citations.
![Report Navigator architecture diagram](<docs/diagram (1).png>)



**Live API and interactive docs:** [https://hacktoberfest-ailucknow.onrender.com/docs](https://hacktoberfest-ailucknow.onrender.com/docs)

**Try it in the API docs:**

1. Open the live docs and expand **POST `/documents`**.
2. Choose a PDF in the `file` upload field and click **Execute**. The response includes a `doc_id`.
3. Wait for ingestion to finish by checking **GET `/documents/{doc_id}`** until `status` is `ready`.
4. Expand **POST `/documents/{doc_id}/ask`** for one question, or **POST `/documents/{doc_id}/batch`** for multiple questions. Paste the returned `doc_id` into the path field and submit the request body.

For batch JSONL uploads, use **POST `/documents/{doc_id}/batch/jsonl`**. Each line must contain `id` and `question`.

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

## Run on your machine (Mac / Windows)

You need: **Git**, **Python 3.11+**, and a free **LLM API key** (step 4).
Everything below is run inside the project folder. First-time ingestion of the
272-page report takes a few minutes; after that it is cached and instant.

### 1. Clone the repo and switch to the `dev` branch

> The code lives on the **`dev`** branch, not `main`. Don't skip the checkout.

**Mac (Terminal):**
```bash
git clone https://github.com/m-tabish/hacktoberfest-AILucknow.git
cd hacktoberfest-AILucknow
git checkout dev
```

**Windows (PowerShell or Command Prompt):**
```powershell
git clone https://github.com/m-tabish/hacktoberfest-AILucknow.git
cd hacktoberfest-AILucknow
git checkout dev
```
No Git? Download the ZIP instead: GitHub → branch dropdown → `dev` →
Code → Download ZIP, unzip, and open a terminal in that folder.
(Python: Mac — `brew install python@3.12` or python.org installer;
Windows — python.org installer, **tick "Add python.exe to PATH"**.)

### 2. Create a virtual environment and install dependencies

**Mac:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
Windows (Command Prompt): activate with `.venv\Scripts\activate.bat`.
If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again.

Optional — embeddings + OCR for scanned pages (not needed for a first run):
```bash
pip install -r requirements-optional.txt
```
plus the `tesseract` binary — Mac: `brew install tesseract` ·
Windows: install from https://github.com/UB-Mannheim/tesseract/wiki and add
its install folder (e.g. `C:\Program Files\Tesseract-OCR`) to PATH.

### 3. Download the dataset (report + questions)

**Mac:**
```bash
git clone https://github.com/CodewithJha/hack-day-lucknow-datasets /tmp/datasets
cp /tmp/datasets/p5-report-qa-rag/report_A.pdf .
cp /tmp/datasets/p5-report-qa-rag/questions_with_answers.jsonl .
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/CodewithJha/hack-day-lucknow-datasets $env:TEMP\datasets
copy $env:TEMP\datasets\p5-report-qa-rag\report_A.pdf .
copy $env:TEMP\datasets\p5-report-qa-rag\questions_with_answers.jsonl .
```
Or just download those two files from the `p5-report-qa-rag` folder on GitHub
and drop them into the project folder.

### 4. Add your LLM API key (required for exact answers)

Copy the example env file — **Mac:** `cp .env.example .env` ·
**Windows:** `copy .env.example .env` — then open `.env` in any text editor
and set your key:

```
LLM_API_KEY=<your key>
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile
```

Free key: https://console.groq.com → API Keys → Create (the defaults above
already match Groq). Prefer OpenAI? Use your OpenAI key and set
`LLM_BASE_URL=https://api.openai.com/v1` and `LLM_MODEL=gpt-4o-mini`.
Without a key the app still runs, but exact-number questions return a
low-confidence `NOT_FOUND` fallback instead of the extracted value.
**Never commit your `.env`** — it is gitignored.

### 5. Run it — pick one

**A. Chat dashboard (both OSes, with the venv active):**
```bash
streamlit run app.py
```
Opens http://localhost:8501. In the sidebar upload `report_A.pdf`, wait for
ingestion to finish, then ask in the chat, e.g.
*"What was the number of road accident deaths in Pune city in 2023?"* →
expected answer **351**, citation **[Page 101]**, with the source row and the
page image under the answer.

**B. Batch + score (the submission path):**
```bash
# Mac
python3 run_batch.py --pdf report_A.pdf --questions questions_with_answers.jsonl --out answers.jsonl
python3 evaluate.py --answers answers.jsonl --gold questions_with_answers.jsonl

# Windows — same, but use `py` instead of `python3`
py run_batch.py --pdf report_A.pdf --questions questions_with_answers.jsonl --out answers.jsonl
py evaluate.py --answers answers.jsonl --gold questions_with_answers.jsonl
```
`evaluate.py` prints exact-match % and page accuracy % on the 50 gold
questions — that is your score estimate for the hidden evaluation.

**C. REST API (for judges / programmatic access):**
```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```
Swagger UI at http://localhost:8000/docs (OpenAPI schema at `/openapi.json`).
Same services as the UI; no authentication. Flow:
1. `POST /documents` (multipart `file`) → `202` with `doc_id`; ingestion runs
   in the background (same PDF again → `200`, reused).
2. Poll `GET /documents/{doc_id}` until `status` is `ready`.
3. `POST /documents/{doc_id}/ask` `{"question": "..."}` → answer, page,
   confidence, source passages, page image URL.
4. `POST /documents/{doc_id}/batch` `{"questions": [{"id", "question"}]}`, or
   upload a questions `.jsonl` to `POST /documents/{doc_id}/batch/jsonl` →
   answers in the submission format.

Also: `GET /documents`, `DELETE /documents/{doc_id}`,
`GET /documents/{doc_id}/pages/{page_no}/image`, `GET /health`.
On macOS 14 set `EMBEDDING_DEVICE=cpu` (in `.env`) — see Troubleshooting.

### Troubleshooting

| Symptom | Fix |
|---|---|
| Most answers are `NOT_FOUND` | `LLM_API_KEY` missing/wrong, or you launched from a different folder — `.env` must sit in the project root next to `app.py` |
| `streamlit` / `python` not found | The venv is not active (prompt should show `(.venv)`), or Python was installed without PATH (Windows: reinstall and tick "Add python.exe to PATH", or use `py`) |
| Ingestion seems slow the first time | Normal — 272 pages are rendered + parsed once; later runs reuse `data/` and start instantly. Delete `data/` to force a fresh ingestion |
| PowerShell: activation script blocked | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then `.venv\Scripts\Activate.ps1` again |
| OCR errors on scanned pages | Install the `tesseract` binary (step 2, optional) — core text pages work without it |
| Mac crashes during ingestion with `MPSNDArray ... unrecognized selector` | macOS < 15 + recent torch: Apple-GPU embeddings crash. Add `EMBEDDING_DEVICE=cpu` to `.env` |

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
