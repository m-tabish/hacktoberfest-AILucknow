# Judge Q&A: Report Navigator

## 1. What is the chunking strategy?

We keep three complementary chunk types, all tied to their original PDF page:

- **Page chunks** preserve the page context (up to 20,000 characters). The answer model receives complete candidate pages so it can interpret table headers alongside their rows.
- **Narrative chunks** are 800 characters with 120 characters of overlap. They improve retrieval for prose without crossing page boundaries.
- **Table-row chunks** put the table title, page number, row label, and extracted values together. This makes a city or category row easier to retrieve as one piece of evidence.

## 2. How do you extract content other than ordinary PDF text?

PyMuPDF reads words with their page coordinates and sorts them into lines to restore reading order. On number-dense pages, table extraction first tries PyMuPDF's `find_tables()`. A pseudo-row parser then scans coordinate-sorted lines as a fallback, preserving ordered numeric values even when column headers cannot be mapped safely.

Pages with fewer than 50 characters of native text are treated as scanned and sent through optional Tesseract OCR at 300 DPI. Pages are also rendered as images for citation previews. The current system does **not** reliably interpret arbitrary charts, diagrams, or image-only table structure; OCR text and table parsing are its extraction paths, not visual chart understanding.

## 3. How do you know the content was extracted correctly?

We expose ingestion statistics such as page, chunk, table-row, and OCR-page counts. Answers include source passages and a PDF page citation, and the UI/API can show the cited page image for human checking. Before returning an LLM answer, the validator checks the answer format, that the cited page is among the retrieved pages, and that the integer appears in the extracted page text; it can relocate the citation to another candidate page containing that integer.

These checks provide evidence, not a guarantee that every table cell or header was interpreted correctly. A number can appear on a page but belong to a different column. That is why table extraction and column matching remain key areas for evaluation and improvement.

## 4. What is the embedding strategy, and why BGE Small?

Embeddings are an optional semantic-retrieval enhancement. The configured default is the local `BAAI/bge-small-en-v1.5` sentence-transformer. It encodes narrative and table-row chunks (not the large page chunks), and normalized vectors are searched with FAISS inner product. Small model size keeps local indexing practical; semantic similarity can find paraphrases that do not share the same wording.

The model is not required for the system to run: BM25 remains available if embedding dependencies or the local model are unavailable. Alternatives include `all-MiniLM-L6-v2`, a larger E5/BGE model when resources allow, or BM25-only retrieval. We have not established a benchmark proving BGE Small is universally best for this report family; it is a compact default, and should be compared on a held-out question set before changing it.

## 5. Why use BM25 and FAISS together?

**BM25** is lexical search. It is especially useful for exact city names, years, table labels, and category terms. This repository uses a small custom pure-Python BM25 scorer, so it has no separate `rank-bm25` dependency.

**FAISS** adds semantic similarity over local embeddings. It can help when a question uses wording different from the report. Retrieval combines lexical scores, optional FAISS scores, and entity/table-row matches, then aggregates evidence by page. BM25-only operation is the fallback when embeddings are disabled or unavailable.

The two methods cover different failure modes: semantic similarity alone can confuse nearby numbers or similar entities, while lexical matching alone can miss paraphrases. The final answer is still checked against candidate page text.

## 6. Why not use a vector database?

At the current scale—a single uploaded report with a few thousand chunks—a separate vector-database server would add deployment, networking, and persistence work without a clear benefit. SQLite stores document, page, row, and chunk metadata; BM25 is stored locally; FAISS stores the optional vector index as a per-document file. This keeps the application self-contained and easy to run or inspect.

FAISS is itself a vector-search library, but it is not a full vector database: it does not provide the service, metadata filtering, or multi-tenant operations of a database product. If the project grows to many concurrent documents or needs distributed filtering and lifecycle management, a vector database such as Qdrant or PostgreSQL with pgvector would be reasonable alternatives.

## 7. What are the project's strong points?

- It ingests a new PDF at runtime instead of relying on pre-extracted answers for a known report.
- It uses deterministic table-cell lookup before asking an LLM, and abstains when an entity is absent.
- It combines coordinate-aware PDF extraction, table rows, OCR fallback, lexical search, and optional semantic search.
- Answers carry a PDF page citation and source evidence, making them easier to inspect.
- Core storage and BM25 search are local and lightweight; embeddings and OCR are optional enhancements.

## 8. What are the limitations?

- Complex multi-row or multi-level table headers can be ambiguous. When the parser cannot map columns confidently, values are retained in order but exact cell lookup may not be possible.
- OCR errors, scanned tables, rotated pages, and unusual layouts can reduce extraction quality. OCR is an optional dependency and may produce no text if it is missing or fails.
- There is no general chart/diagram understanding. Image rendering supports human evidence review, not automatic visual reasoning over every graphic.
- Retrieval only sends a limited number of candidate pages to the LLM; a relevant page omitted by retrieval cannot be answered from that request.
- The validator checks schema and textual presence, not the full meaning of a table header. A plausible number can still be associated with the wrong category.
- The configured LLM endpoint may be a cloud API, so network availability, latency, model behavior, and API limits affect answers. A cloud endpoint also does not satisfy an offline-only scoring environment.
- The current embedding index is a simple per-document FAISS flat index; it is designed for this project's scale, not large multi-user workloads.

## 9. What is the core of the project? Which part is the “brain” and most crucial?

`src/qa/answerer.py` is the answer-orchestration “brain.” It extracts the question's entity and metric, tries deterministic SQL cell lookup, retrieves candidate pages, checks whether an entity is absent, calls the configured LLM when needed, and validates the result.

The quality bottleneck is the **evidence pipeline**: extracting table rows and headers accurately, then retrieving the right page. The orchestrator coordinates those parts, but it cannot recover information that ingestion lost or retrieval failed to find. For numeric questions, table extraction and exact row/column matching are especially crucial.

## 10. What are the future plans for improvement?

1. Improve table structure recovery for multi-level headers and continued tables, and measure row/column extraction accuracy independently.
2. Add robust OCR/layout handling for scanned tables, rotated pages, and low-quality scans; evaluate OCR against manually checked pages.
3. Add chart and image-table extraction where the report family needs it, with confidence and human-review evidence.
4. Expand evaluation to report exact-match accuracy, citation accuracy, abstention quality, extraction errors, and latency on held-out reports.
5. Calibrate confidence using evaluation data and make header-to-value validation stricter so a number appearing on a page is not treated as sufficient proof by itself.
6. Provide a fully local inference option for environments that prohibit network access, and test it within the scoring time and memory limits.
7. Revisit vector-database adoption only if document volume, concurrent users, or metadata-filtering needs outgrow the current SQLite and per-document FAISS design.
