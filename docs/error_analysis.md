# Error Analysis

Use this document to explain where the system fails and what evidence supports each proposed fix. Report counts as well as rates because the public benchmark contains only 50 questions.

## Evaluation snapshot

| Run / commit | Exact match | Citation accuracy | Composite score | Answerable recall | Hallucination rate | Runtime | Peak memory |
|---|---:|---:|---:|---:|---:|---:|---:|
| Not measured | — | — | — | — | — | — | — |

## Required slices

Break results down by `qtype`, answerability, and text/table/OCR evidence. Include the number of examples in every slice. For each failure, record the question ID, expected answer and allowed pages, predicted answer/page, evidence retrieved, failure category, and a concrete next step. Avoid copying large portions of report text into this document.

## Failure categories to track

- Retrieval missed the supporting page or table.
- Entity, alias, year, or geographic scope mismatch.
- Wrong measure or population (for example, accidents versus people killed).
- Wrong table row, column, or aggregation.
- Number parsing or formatting error.
- Correct answer with an incorrect physical PDF page citation.
- OCR failure or loss of table reading order.
- Unsupported answer on an unanswerable question.
- Conservative abstention on an answerable question.
- Runtime, memory, malformed input, or output-schema failure.

## Findings

No evaluation has been run yet. Add measured findings here; do not present hypotheses as results.
