# Project Instructions

These instructions apply to all work in this repository. Read `docs/guideline.md`, `docs/dataset_design.md`, `docs/ui_api_architecture.md`, and `docs/architecture_and_evaluation.md` before changing project behavior.

## Goal

Build Report Navigator: an evidence-grounded system that answers questions about a supplied statistics PDF, cites its physical page, and abstains when the report does not support an answer. Provide both the required offline scoring CLI and an upload/results HTTP endpoint. Keep the UI and HTTP service framework-independent; choose frameworks only when implementation needs them. Do not couple answer logic to a UI or web framework.

## Required interfaces

- Preserve the evaluator CLI exactly: `python predict.py --pdf {pdf_path} --questions {questions_jsonl} --output {answers_jsonl}`.
- Provide an HTTP endpoint suitable for organizer uploads and result retrieval. It is a required interface, not an optional demo. Accept the PDF and question JSONL and return the same answer records as the CLI. Keep the contract documented in one place and adapt it if organizers provide a definitive protocol.
- Provide a simple upload/results UI. It must call the HTTP interface and must not duplicate PDF parsing, retrieval, or answer logic.
- Route CLI and HTTP requests through one shared inference pipeline. The CLI must run without a network connection even when the HTTP service is unavailable.
- Validate uploads and question records; limit file size, runtime, and concurrent jobs. Use generated temporary paths and remove uploaded files and derived content on success and failure. Never log or retain hidden questions, PDFs, extracted text, or answers.
- Before public exposure, require HTTPS, authentication stored outside source/client code, and safe error messages. Do not expose stack traces or uploaded content in responses.

## Output contract

- Emit one JSON object per input question with `id`, `answer`, `page`, and `confidence`; preserve each input ID exactly and once.
- `answer` is digits only as a string, or exactly `NOT_FOUND`. No commas, units, or prose.
- For an answer, `page` is the **1-based physical PDF page index**. For `NOT_FOUND`, `page` is `null`.
- `confidence` is a finite number in `[0, 1]`. Keep CLI and HTTP output schemas identical.
- Reject malformed JSONL, missing/duplicate IDs, invalid PDFs, and invalid output values clearly; never return partial success as if complete.

## Dataset and answer rules

- The challenge report is a long official road-accident statistics PDF with narrative text and tables. Public questions concern 2023; hidden evaluation uses a different report/year and includes scanned pages.
- The public set has 50 questions: 45 answerable counts and 5 unanswerable. Use it for evaluation, not answer lookup or memorization.
- `sample_answers.jsonl` is schema-only; its repeated values are placeholders. The question file is JSONL, one object per line.
- Build indexes from the PDF supplied at runtime. Keep row labels, column headers, and evidence together. Match the requested geography, year, measure, and population/category before selecting a number.
- Return `NOT_FOUND` when evidence is absent, ambiguous, or unreliable. Never infer a number from a similar page or a high retrieval score alone.
- Never hard-code answers, page mappings, report-derived text/tables, or hidden data. Do not use the original challenge data source or probe hidden tests.

## Event constraints

- Scoring runs offline with 2 CPU cores, 6 GB RAM, no network, and a 20-minute total limit including PDF ingestion. Local model files must be at most 3 GB.
- Do not make the CLI depend on an HTTP server, external service, cloud LLM, or network download. Any public demo endpoint is a separate entry point over the same local pipeline.
- Handle image-only/scanned pages without crashing or hanging; OCR, if used, must be local and bounded by the same resource limit.
- Keep behavior deterministic where practical. P5 reproducibility tolerance is 0.03 score.
- Follow repository limits and dependency rules in the participant guide. Pin Python dependencies with `==`; declare external models/data, licenses, and AI-tool use in the root `README.md`.

## Implementation and documentation

- Make the smallest complete change. Keep framework-specific code at the interface boundary and the inference core framework-neutral.
- Preserve evidence internally for debugging and error analysis, but do not add extra fields to the required answer output.
- Keep `docs/decisions.md` and `docs/error_analysis.md` factual and measured; do not claim experiments or results that were not run.
- Keep the root `README.md` because the evaluator checks it. Store supporting project documentation in `docs/`.
- Add or update the required smoke coverage when implementing the prediction path; test schema, IDs, abstention, citations, and CLI/API parity.
