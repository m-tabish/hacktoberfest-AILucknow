# Architecture and Evaluation Plan

This is the build map for Report Navigator. Keep the implementation focused on the event contract: exact integer answers, checkable physical-page citations, and honest abstention. Do not add infrastructure that does not improve those outcomes or provide the required upload/results interface.

## Architecture layers

```text
CLI: predict.py ─────────────┐
HTTP upload endpoint ────────┼──> shared pipeline ──> page evidence ──> answer JSONL
UI (HTTP client) ────────────┘
                                  │
                       ingest → retrieve → verify
```

| Layer | Owns | Build requirements |
|---|---|---|
| 1. Entry points | CLI, HTTP endpoint, UI | CLI uses the required `--pdf`, `--questions`, and `--output` arguments. HTTP accepts a PDF and JSONL questions and returns the same records. UI uploads both and presents/downloads results. Framework-specific code stays in these adapters. |
| 2. Input/output contract | Validation and serialization | Validate PDF, JSONL, required fields, IDs, and output types. Emit exactly one record per ID. Keep errors out of successful output. API and CLI must use the same validation and serializer. |
| 3. PDF ingestion | Page-aware text, table and OCR extraction | Parse the supplied PDF at runtime. Keep 1-based physical page number, headings, table headers, row labels, and cell values together. Use native text when valid; OCR only image-only/broken-text pages. Bound OCR work and time. |
| 4. Retrieval | Candidate pages/regions | Find likely evidence using question entities and scope (year, geography, measure, road-user/cause category). Retrieve table rows together with their headers and surrounding context. Use a small local lexical baseline first. |
| 5. Answer verification | Exact value, page, abstention, confidence | Accept a number only when evidence matches the requested entity, year, measure, and category. If evidence is missing, conflicting, or weak, return `NOT_FOUND` with `page: null`. Keep evidence and diagnostics internal. |
| 6. Evaluation | Metrics, error slices, resource use | Compare JSONL predictions to public gold records. Report exact match, citation accuracy, official score, hallucination rate, answerable recall, retrieval diagnostics, runtime, and peak memory. |

### Minimal source layout

```text
predict.py             # CLI adapter
api.py                 # HTTP adapter; exact filename/framework is a choice
ui.py                  # UI adapter; exact filename/framework is a choice
src/pipeline.py        # shared orchestration
src/pdf_ingest.py      # page extraction and targeted OCR
src/retrieve.py        # page/region retrieval
src/answer.py          # grounded number selection and abstention
src/contracts.py       # shared input/output validation and JSONL serialization
tests/test_smoke.py    # CLI/API schema smoke coverage
```

Keep only modules that have real responsibilities. The HTTP and UI layers must call the shared pipeline; they must not contain their own answer logic. The CLI must work with networking disabled even when the endpoint is down.

## Public dataset facts and risk

- The participant guide describes a 272-page official road-accident report with narrative content and many tables.
- The public benchmark contains 50 questions: 45 answerable and 5 unanswerable, across city/state/national measures, road-user categories, collision types, and violations.
- The hidden evaluation uses a different report/year and includes scanned pages. Rebuild the page index from each supplied PDF; never rely on public-report page numbers or memorized answers.
- The central risk is selecting a nearby but semantically wrong table value. A city match alone is insufficient: measure, geography, year, row category, and column heading must also match.

## Metrics to implement

For each gold question, compare one output record by ID. Compute:

1. **Exact Match (EM):** normalize predicted and gold answers by removing commas and spaces, as the guide specifies; then compare exact strings. `NOT_FOUND` must match exactly.
2. **Citation Accuracy:** for answerable questions, predicted physical page must be in that question's `gold_pages`; for unanswerable questions, count correct only when the answer is `NOT_FOUND`.
3. **Official Score:** `0.75 × EM + 0.25 × Citation Accuracy`.
4. **Hallucination rate:** share of unanswerable questions answered with a number. Lower is better and it is the P5 tie-break metric.
5. **Answerable recall:** share of answerable questions given a non-`NOT_FOUND` answer. Reported diagnostic; increasing recall by guessing can hurt EM and hallucination.
6. **Retrieval Recall@k (diagnostic only):** share of answerable questions whose gold page appears among the top `k` retrieved pages. This isolates retrieval misses from extraction mistakes; it is not an official scoring metric.

Always report numerators and denominators (for example, `EM 31/50`) alongside rates. With only five unanswerable public examples, a single miss changes hallucination rate by 20 percentage points. Do not treat small-sample confidence as precise.

## How to evaluate

### 1. Contract tests

- Confirm the sample input runs through the CLI and HTTP endpoint.
- Validate exact IDs, no missing/duplicate outputs, answer string rules, page range/null behavior, finite confidence `[0,1]`, and valid JSONL.
- Use malformed JSONL, duplicate IDs, invalid PDF bytes, empty PDF, and oversized uploads to check safe failures.
- Compare CLI and HTTP output records for the same local input; they should be schema-equivalent and use the same inference path.

### 2. Public benchmark run

Run all 50 records against `report_A.pdf` and compute the metrics above. Use `questions_with_answers.jsonl` for gold labels; `sample_answers.jsonl` is only a format example and its values are placeholders. Do not put public answers or page mappings into the implementation.

### 3. Diagnose every miss

Write one row per failed question with: ID, qtype, gold answer/pages, predicted answer/page, top retrieved pages, and one primary failure label:

- retrieval missed the page;
- OCR/text extraction failed;
- table row or column mismatch;
- wrong entity, year, measure, or category;
- integer normalization error;
- citation off by one / wrong physical page;
- false abstention;
- hallucination on an unanswerable question.

If the gold page is not retrieved, fix retrieval/ingestion. If it is retrieved but the value is wrong, fix table context or answer verification. This prevents optimizing the wrong layer.

### 4. Avoid public-set overfitting

The public set is small and templates repeat. Use grouped/leave-question-family-out validation during tuning where practical, then report the final all-50 public score separately. Do not claim the public score estimates hidden performance exactly. Hidden pages and the different report/year are the real generalization test.

### 5. Resource and robustness run

Measure full PDF ingestion plus all answers with networking disabled, on CPU and within 2 cores / 6 GB RAM. Record wall-clock time and peak memory; keep margin below 20 minutes. Include pages with no text layer, empty extraction, malformed table reading order, and OCR failure. Set bounded timeouts and return `NOT_FOUND` where evidence remains unreliable.

### 6. Score targets

The participant guide's rough P5 bands are:

| Band | Official score | Exact match |
|---|---:|---:|
| Lazy baseline | ≤ 0.30 | ≤ 0.15 |
| Good | ≥ 0.60 | ≥ 0.55 |
| Excellent | ≥ 0.80 | ≥ 0.78 |

Always answering `NOT_FOUND` is about 0.06. Treat **score ≥ 0.60 and EM ≥ 0.55 on the public set** as a useful “good-band” development target, not a guarantee of hidden-set success. Also track citation accuracy and hallucinations so a high score does not hide unsafe guessing. The guide's P5 audit tolerance is 0.03 score.

## Assessment of the supplied Docling/VLM setup

**Useful as a local experiment; not suitable as the default scoring pipeline as pasted.**

- The challenge scorer has no GPU, only 2 CPU cores and 6 GB RAM, no network, a 20-minute total limit, and a 3 GB local-model cap. An M2/RTX 3050 setup does not match that environment.
- The guide's `llama3.2-vision:latest` is the 11B variant. Ollama lists it at 7.8 GB, and Ollama's release notes say the 11B model needs at least 8 GB VRAM; it does not fit the stated 4 GB RTX 3050 or the event's 3 GB model limit. [Ollama model card](https://ollama.com/library/llama3.2-vision), [Ollama release notes](https://ollama.com/blog/llama3.2-vision).
- The pasted `ibm-granite/granite-docling-8b-mlx` identifier and legacy-looking `vlm_engine_type` / `model_name` arguments do not match the current Docling documented Granite Docling preset/model. Current docs list Granite Docling 258M and show the model passed through `VlmPipelineOptions(vlm_options=...)`. Pin a Docling version before adapting any example. [Docling vision-model guide](https://github.com/docling-project/docling/blob/main/docs/usage/vision_models.md), [Docling pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/).
- Full-page VLM conversion is expensive for a 272-page report. Docling's own example table reports 6.15 seconds per page for one MLX SmolDocling benchmark (about 28 minutes for 272 pages, before question answering); this is not a direct benchmark of the pasted model but is enough to reject an unmeasured all-pages VLM pass under a 20-minute limit. [Docling model benchmark table](https://github.com/docling-project/docling/blob/main/docs/usage/vision_models.md).
- A more fitting first experiment is fast native PDF text extraction, with table structure retained where possible, and local OCR only on pages with no/broken text. Docling's native PDF pipeline is model-free and fast but does not add OCR, layout, or table-structure analysis, so validate table quality; use its standard PDF pipeline selectively if the native parse is insufficient. [Docling pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/).

The guide may help you inspect table/OCR output on your own laptop. Before adopting any parser, run it on a representative set of public gold pages and report (a) parse/OCR coverage, (b) answer/citation metrics, and (c) full-document CPU runtime/memory. A visually convincing Markdown export by itself does not prove the system can answer the benchmark correctly.

## Readiness verdict

The **layered design is appropriate** for this dataset and keeps the event requirements intact. The repository currently contains documentation but no working ingestion, retrieval, answerer, CLI, endpoint, or evaluation code. Therefore, it is **not yet possible to say the system is good enough**. It becomes evidence-backed when the implemented pipeline meets the good-band public target, stays within resource limits, and passes hidden-report-style robustness checks; only the evaluator can establish hidden-set performance.
