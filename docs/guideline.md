# Project Guideline — Report Navigator

This document is the working specification for shaping this repository into a strong, reproducible submission for **Problem 5: Report Navigator** at Hacktoberfest Hack Day Lucknow. It translates the participant guide and the supplied question/output examples into implementation decisions, acceptance checks, and a development order.

## 1. Product goal

Build an offline tool that receives a long statistics PDF and JSONL questions, then returns one exact answer, its supporting **1-based PDF page index**, and a calibrated confidence for every question. It must either support the answer with evidence from the input report or abstain with `NOT_FOUND`. The target user is someone who needs a checkable statistic from a large report, not a fluent but unverifiable chatbot.

The event describes the hidden input as a different report in the same family, with a different year, new question wording, and some scanned pages. Therefore, the system must derive its index from the PDF supplied at runtime. It must not depend on the supplied report's page layout, memorized answers, fixed page numbers, or pre-extracted report content.

## 2. Source-of-truth files

| File | Role | Guidance |
|---|---|---|
| `dataset/Participant_Guide_Detailed.pdf` | Event rules and Problem 5 specification | Follow its output schema, metrics, limits, and integrity rules. |
| `dataset/questions_with_answers.jsonl` | 50 public examples (45 answerable, 5 unanswerable) | Use for development and evaluation; fields include `id`, `question`, `answer`, `answer_type`, `gold_pages`, and `qtype`. |
| `dataset/sample_answers.jsonl` | Output-shape example | Treat as schema only. Its repeated `12345`, page `10`, and confidence `0.5` values are placeholders, not correct predictions. |

The requested filename `questions_with_answers.json` differs from the checked-in file: the actual file is `questions_with_answers.jsonl` (one JSON object per line). Keep paths configurable; do not rename or silently assume the nonexistent `.json` file.

## 3. Acceptance contract

The project also requires a simple upload/results UI and an HTTP endpoint for PDF and question uploads. Keep both as framework-neutral adapters over the same inference code; they do not replace or alter the offline CLI required by the event scorer. See [UI/API architecture](ui_api_architecture.md) for the proposed contract and data-handling requirements.

The submission entry point must support the guide's command:

```text
python predict.py --pdf {pdf_path} --questions {questions_jsonl} --output {answers_jsonl}
```

For every input question, emit exactly one valid JSON object per line with these fields:

```json
{"id":"P000","answer":"351","page":101,"confidence":0.92}
```

- Preserve each input `id` exactly and return all IDs once; output order may follow the input order.
- `answer` is a string containing digits only (no commas, spaces, signs, units, or explanation), or exactly `NOT_FOUND`.
- `page` is an integer from `1` through the PDF page count for an answer, and `null` for `NOT_FOUND`.
- `confidence` is a finite JSON number from `0` through `1`.
- Do not add prose, Markdown fences, or logging to the output file. Send diagnostics to stderr.
- Invalid input, an unreadable PDF, and a malformed question line should produce a useful nonzero failure rather than partial or malformed output.

Automated scoring uses `0.75 × Exact Match + 0.25 × Citation Accuracy`. The public examples include several valid gold pages for some answers; any listed `gold_pages` page can support citation accuracy. Unanswerable cases are correct only when the answer is `NOT_FOUND`. Hallucination rate is a tie-break metric, so an unsupported number is worse than an honest abstention.

## 4. Hard constraints and integrity

- Scoring runs offline: **2 CPU cores, 6 GB RAM, 20 minutes total including PDF ingestion**, and no network. Any local model files must fit within 3 GB.
- Build the index at run time from the `--pdf` argument. Do not ship pre-extracted text/tables, cached indexes, memorized answers, answer lookup tables, or report-specific page mappings.
- Do not use the original challenge data source, hidden data, crafted repeated runs to infer hidden answers, or cloud LLM APIs during scoring.
- Declare external data, models, licenses, and AI-tool use in the root `README.md` as required by the event guide.
- Keep the repository under the event's size limits and do not commit challenge data or generated report text. Keep only source code, tests, documentation, and permitted model assets.
- Set deterministic behavior where practical. The event's reproducibility tolerance for this problem is 0.03 score.

## 5. Recommended system design

Keep the implementation small and separable. A suitable initial layout is:

```text
predict.py                 # CLI, validation, orchestration, JSONL writing
src/
  pdf_ingest.py            # per-page extraction and optional OCR
  normalize.py             # question and text normalization
  retrieve.py              # candidate page/region search
  extract_answer.py        # evidence-grounded numeric extraction
  confidence.py            # confidence features and abstention
tests/
  test_smoke.py            # schema and end-to-end smoke test
docs/
  guideline.md
  decisions.md
  error_analysis.md
```

This is a suggested organization, not a requirement to create empty modules. Keep modules only when they reduce coupling or make behavior easier to verify.

### 5.1 Ingest the PDF by physical page

Create one document record per physical PDF page, retaining the page index as `page_number = zero_based_index + 1`. Store extracted text and, where useful, table-like lines for that page. Never use the printed footer/page label as the citation: the guide explicitly requires the 1-based PDF page index.

Detect pages with missing or nearly empty text. For those pages, optionally render and OCR them with an installed local tool such as Tesseract. OCR should be bounded by time and page count; cache only in a temporary runtime directory if needed. If OCR is unavailable or times out, continue with the extracted pages and abstain when evidence is insufficient instead of crashing.

### 5.2 Normalize without losing evidence

Normalize text for matching (case folding, whitespace, punctuation, common abbreviations and number formats) but retain the original page text/table cells for evidence and answer parsing. Build small, transparent aliases for common entity spellings or alternate city names, and normalize category wording such as vehicle/user groups. Do not use broad fuzzy matching as proof: it can retrieve a page but cannot establish which number answers the question.

### 5.3 Retrieve pages and regions

Use a CPU-friendly retrieval baseline first: a TF-IDF/BM25-style index over page text and table-row snippets, with exact entity/category/year terms. Add lightweight heuristics for question class (`qtype` patterns such as city killed, state accidents, road-user killed, or collision type) where they generalize to unseen wording. Rank evidence regions, not only whole pages, so neighboring row labels and column headings remain available.

For table questions, keep a row together with its column headers and nearby labels. The numeric cell alone is not evidence. Retrieval should identify a likely table, then answer extraction should verify the entity, metric (accidents, killed, injured), time period, and requested breakdown against that table context.

### 5.4 Extract only evidence-supported answers

Parse candidate integers from the retrieved evidence while preserving table structure and nearby labels. Resolve commas and spacing only when converting a clearly identified integer to the required digits-only output. Prefer an exact row/column match over a language model guess. If multiple candidate values remain, use additional context and a deterministic ranking rule; if ambiguity remains, return `NOT_FOUND`.

A small local model may help rerank or interpret question phrasing, but it must run without network and may not invent the answer. Keep answer selection anchored to an extracted report span or table cell. Record the evidence internally (page, matching text/row, chosen value, retrieval score, and reason) for debugging, while keeping the required JSONL output clean.

### 5.5 Abstain and assign confidence

Return `NOT_FOUND` when the report lacks the requested fact, retrieved evidence is weak, no matching row/column exists, OCR is unreliable, or candidate values conflict. For `NOT_FOUND`, set `page` to `null`.

Do not equate retrieval similarity with answer confidence. Calibrate confidence using observable signals such as entity/metric/year agreement, exact row/column match, OCR quality, score margin between candidates, and consistency across evidence regions. Use held-out public examples to assess calibration; never tune confidence using hidden results. Confidence is required in the schema even though the primary score does not directly reward it.

## 6. Validation plan

Use the public JSONL as a development benchmark, not as a source of hard-coded outputs.

1. Validate every line against the expected fields and confirm all 50 IDs are unique and present.
2. Measure exact match, citation accuracy, composite score, answerable recall, and hallucination rate separately. Normalize answers only as the official metric does (commas/spaces removed; `NOT_FOUND` exact).
3. Split analysis by `qtype`, answerability, and evidence type (narrative versus table). With only 50 examples, report counts next to rates and avoid claiming statistical certainty.
4. During tuning, use question-family holdouts or leave-one-family-out checks where feasible. This helps reveal memorization of recurring templates.
5. Add edge tests for malformed JSONL, duplicate/missing IDs, empty pages, scanned/no-text pages, comma-separated values, ambiguous rows, out-of-range citations, and conflicting candidate numbers.
6. Run the full smoke path under a time limit representative of the scoring sandbox. Measure PDF ingestion and inference together; keep a margin under 20 minutes and 6 GB.
7. Before submission, verify determinism, exact output schema, no network calls, and that a clean checkout can run using only declared dependencies and permitted model files.

The supplied `sample_answers.jsonl` is only a shape example. Do not use its numbers as expected answers or as a test oracle. The public gold answers and page lists are in `questions_with_answers.jsonl`.

## 7. Development order

1. **Make the CLI contract pass.** Parse arguments, validate inputs, preserve IDs, write valid JSONL, and implement a clear abstention fallback.
2. **Build per-page extraction.** Keep physical page numbers and inspect extraction quality on text and table pages.
3. **Create a reproducible baseline.** Retrieve pages with lexical ranking, then extract answers from matching rows/contexts.
4. **Evaluate failures.** Categorize retrieval misses, entity mismatch, wrong metric/column, number parsing, page citation, OCR, and unanswerable hallucination.
5. **Improve the largest failure class.** Add only targeted normalization, table handling, OCR, or reranking supported by evidence.
6. **Harden resource use.** Profile runtime and memory; ensure bounded OCR and graceful handling of problematic pages.
7. **Complete submission docs.** Keep the evaluator-required `README.md` at the repository root, and maintain `docs/decisions.md` plus `docs/error_analysis.md` with real measured choices and failures.
8. **Freeze and reproduce.** Run the final smoke/evaluation command from a clean checkout; record the exact commit and results before code freeze.

## 8. Definition of done

- The required CLI works on arbitrary input paths and builds its PDF index at runtime.
- Every valid question gets exactly one schema-valid output row; no IDs are dropped or fabricated.
- Answers are exact, digits-only, and supported by the cited physical PDF page, or the system honestly abstains.
- The implementation handles text and scanned pages within sandbox limits without network access.
- Public validation, per-category error analysis, runtime, and reproducibility are documented honestly.
- The root README contains every required event section, including AI tools and data/model licenses; `docs/decisions.md` and `docs/error_analysis.md` are complete rather than generic placeholders.
- No challenge answers, pre-extracted report content, or hidden data are embedded in the repository.

## 9. Reading list

- [Participant guide](../dataset/Participant_Guide_Detailed.pdf): full event contract; see the general submission rules and Problem 5.
- [Public questions and gold answers](../dataset/questions_with_answers.jsonl): development examples, answer types, qtypes, and allowed citation pages.
- [Output example](../dataset/sample_answers.jsonl): JSONL shape only; values are placeholders.
