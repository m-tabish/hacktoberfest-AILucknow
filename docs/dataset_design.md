# Dataset Design — Report Navigator (Problem 5)

This is the compact data reference for implementing Report Navigator. It records the dataset shape and vevaluation contract described in `dataset/Participant_Guide_Detailed.pdf`, together with the checked-in question and output examples. Consult this file before inspecting the source files; update it only when the supplied data or official guide changes.

## What the task is

This is a document question-answering task over long statistical reports, not a general chatbot benchmark. Given a PDF report plus a JSONL file of questions, return an exact integer found in the report, cite the physical PDF page that supports it, and abstain as `NOT_FOUND` when the report does not provide the requested fact.

The guide describes `report_A.pdf` as a 272-page official road-accident statistics report. It contains narrative material and many tables. The report year represented by the public questions is 2023. The hidden evaluation uses a different report from the same family, with a different year and some scanned pages, so page numbers, table positions, and answers must be discovered from the PDF supplied at runtime.

## Files and their roles

| File | What it contains | How to use it |
|---|---|---|
| `dataset/Participant_Guide_Detailed.pdf` | Rules for all hack-day problems and the authoritative Problem 5 task, metrics, command, resource limits, and integrity requirements. | Reference for the challenge contract. It is a 26-page participant guide, not the 272-page statistics report to search. |
| `dataset/report_A.pdf` | Public example statistics report, described in the guide as 272 pages. | Input to local development and schema checks. Build the page index from the runtime `--pdf` argument. |
| `dataset/questions_with_answers.jsonl` | 50 public question records with gold answers, answerability, question type, and supporting page list. | Use as a development/evaluation benchmark; do not hard-code its answers. |
| `dataset/sample_answers.jsonl` | Three JSONL output-shaped examples. | Schema illustration only. The repeated `12345`, page `10`, and confidence `0.5` values are placeholders, not answer labels. |

The challenge guide writes `questions_with_answers.jsonl`; the checked-in filename also ends in `.jsonl`. A `.json` variant is not present. JSONL means one independent JSON object per line, not a single JSON array.

## Public question records

Each line in `questions_with_answers.jsonl` has these fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable question identifier, such as `P000`. Preserve it exactly in output. |
| `question` | string | Natural-language request for a statistic. Wording may include alternate spellings, qualifiers, or parenthetical context. |
| `answer` | string | Gold integer as text, or exactly `NOT_FOUND` for an unanswerable question. |
| `answer_type` | string | `count` for answerable examples; `abstain` for unanswerable examples. |
| `gold_pages` | array of integers | One or more acceptable supporting PDF page indexes for the gold answer. Empty for unanswerable questions. |
| `qtype` | string | Coarse semantic family label. Useful for evaluation slices and error analysis, not as an answer lookup key. |

The checked-in file has 50 rows: 45 answerable (`count`) and 5 unanswerable (`abstain`). The answer values are strings to preserve the required output representation. `gold_pages` can contain multiple valid page references when the same statistic appears in multiple report locations.

### Question-family inventory

| `qtype` | Count | Information requested |
|---|---:|---|
| `city_killed` | 7 | People killed in a named city. |
| `city_twowheeler_killed` | 7 | Two-wheeler riders killed in a named city. |
| `city_accidents` | 5 | Total accidents in a named city. Some questions identify a million-plus city. |
| `city_injured` | 5 | People injured in a named city. |
| `city_overspeeding_killed` | 5 | City-level deaths attributed to over-speeding. |
| `city_pedestrians_killed` | 5 | Pedestrians killed in a named city. |
| `state_killed` | 3 | People killed in a state or union territory. |
| `state_accidents` | 2 | Total accidents in a state. |
| `road_user_killed` | 2 | Deaths for a road-user/vehicle category at India scope. |
| `violation_killed` | 2 | Deaths attributed to a violation category; public examples include All India and mobile-phone use. |
| `collision_type_accidents` | 1 | Accidents for a collision type. |
| `collision_type_killed` | 1 | Deaths for a collision type. |
| `unanswerable` | 5 | Requested fact is not found in the report; output must abstain. |

Labels above describe the public questions, not an exhaustive ontology. Generalize from their semantics and evidence, not from fixed page numbers or the `id`/`qtype` alone.

## Data dimensions and matching challenges

Questions vary across several dimensions that must agree before accepting a numeric cell:

- **Measure:** accidents, deaths/killed, or injuries.
- **Geography:** city, state/union territory, or India/All India.
- **Population/category:** all people, pedestrians, two-wheeler riders, road-user classes, or a specified violation.
- **Cause/type:** for example over-speeding or collision type.
- **Time:** the requested year, shown as 2023 in public questions.
- **Answerability:** the report may not contain an apparently plausible requested fact.

Names are not always normalized consistently. Public wording includes aliases and spelling variants such as Allahabad (Prayagraj), Thiruvanthapuram, Vijaywada, Vadodra, and Asansol Durgapur. Matching should normalize aliases while preserving the distinction between geographic scopes and categories. A matching city name alone is not sufficient evidence: the measure, year, category, and table column must also match.

The main extraction challenge is table interpretation. A number may be adjacent to a row label while its meaning depends on a column header, parent heading, or neighboring category. Keep table headers and row labels attached to candidate values. Do not answer by selecting the first number on a relevant page.

## Output contract

The required command is:

```text
python predict.py --pdf {pdf_path} --questions {questions_jsonl} --output {answers_jsonl}
```

Output is one JSON object per input question, for example:

```json
{"id":"P000","answer":"351","page":101,"confidence":0.92}
```

- `id`: exact input ID, once per question.
- `answer`: digits only as a string (no commas, spaces, units, or explanation), or exactly `NOT_FOUND`.
- `page`: integer from 1 to the number of pages for an answer; `null` for `NOT_FOUND`.
- `confidence`: numeric value in `[0, 1]`.
- Citation uses the **1-based physical PDF page index**, not a printed footer number.
- A malformed JSONL line makes the run invalid; missing IDs, commas in answers, and invalid page indexes make affected answers wrong.

## Scoring and interpretation

The primary score is:

```text
Score = 0.75 × Exact Match + 0.25 × Citation Accuracy
```

Exact match compares the answer after removing commas and spaces; `NOT_FOUND` must match exactly. Citation accuracy accepts a cited page listed in that question's `gold_pages`; for an unanswerable question it is correct when the answer is `NOT_FOUND`. The guide also tracks hallucination rate (tie-break), answerable recall (reported), and the composite score. An unsupported number on an unanswerable question is a costly failure; abstention is a required capability, not an optional fallback.

## Runtime, environment, and integrity

- Total wall-clock budget: **20 minutes**, including PDF ingestion and index construction.
- Sandbox: **2 CPU cores, 6 GB RAM, no network**.
- Local model files: at most **3 GB**.
- The index must be built at runtime from `--pdf`; handle pages with no text layer without crashing or hanging.
- Cloud LLM APIs are unavailable/prohibited during scoring. Any local model must be permitted and declared as specified in the guide.
- Do not use the original data behind the challenge dataset, hidden data, hard-coded/memorized answers, or pre-extracted report text/tables. The guide says shipping pre-extracted text, tables, or answers from a report is disqualifying; derived PDF text over 1 MB is flagged.
- Declare external data, models, licenses, and AI-assistant use in the root `README.md`.
- Reproducibility tolerance for P5 is 0.03 score.

## Practical implementation implications

1. Parse the supplied PDF page by page and retain the physical page index from the parser.
2. Detect empty/scanned pages. Use bounded local OCR when available; otherwise do not invent evidence from missing text.
3. Retrieve relevant pages and table regions using entity, measure, category, geography, and year cues.
4. Extract a value only when its row/column context supports the question. Retain the source span/page internally for debugging.
5. Return `NOT_FOUND` if the report lacks the fact, retrieval is weak, evidence conflicts, or OCR/table context is unreliable.
6. Evaluate exact match, citation accuracy, score, answerable recall, and hallucination separately. Report sample counts beside rates because the public set is small.
7. Treat the three lines in `sample_answers.jsonl` as schema fixtures only; use `questions_with_answers.jsonl` for public gold evaluation.

## Source note

This design reference summarizes the Problem 5 section of `Participant_Guide_Detailed.pdf` (the guide identifies the report, sample sizes, task, metrics, format, limits, and rules) and the checked-in JSONL schemas. The question-family counts were computed from the 50 public records. The public examples are development data only; hidden evaluation content is not available and must not be inferred or reproduced.
