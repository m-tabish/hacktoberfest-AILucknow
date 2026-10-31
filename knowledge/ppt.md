# Report Navigator
### Evidence-grounded answers from long government reports

---

## Page 1 — Problem + Solution

### The problem

Government statistics reports can run hundreds of pages and contain dense tables, multi-level headers, and scanned pages. Finding one exact figure is slow; a generic chatbot can confuse a city, year, or column and answer with confidence anyway.

### Our solution

Upload a report once, then ask a question or submit a batch. Report Navigator extracts and indexes the document, looks for an exact table value first, and uses page-level retrieval plus a configured LLM when structured lookup cannot resolve the question. Answers include a PDF page citation and can abstain with `NOT_FOUND`.

```mermaid
flowchart LR
    U[Upload report PDF] --> X[Extract page text and tables]
    X --> O[OCR fallback for scanned pages]
    O --> I[(SQLite + BM25 index)]
    I --> Q[Question]
    Q --> D{Exact table cell?}
    D -->|Yes| A[Validated answer + page]
    D -->|No| R[BM25 + optional FAISS retrieves pages]
    R --> L[Configured LLM reads candidate pages]
    L --> V[Validate answer and citation]
    V --> A
```

**Design principle:** deterministic lookup first; model-assisted extraction only when needed. No report-specific answers are hardcoded.

---

## Page 2 — Demo: From PDF to Answer

### Live API

[Open the interactive API docs](https://hacktoberfest-ailucknow.onrender.com/docs)

1. Use **POST `/documents`** to upload a PDF.
2. Copy the `doc_id` from the response.
3. Check **GET `/documents/{doc_id}`** until its status is `ready`.
4. Put that ID in **POST `/documents/{doc_id}/ask`** for one question or **POST `/documents/{doc_id}/batch`** for multiple questions.
5. Review the answer, cited PDF page, source passages, and optional page image.

Example ask body:

```json
{"question": "How many people were killed in road accidents in Pune in 2023?"}
```

The submission answer format is:

```json
{"id": "P000", "answer": "351", "page": 101, "confidence": 0.92}
```

For an unanswerable question, the required submission format uses `"answer": "NOT_FOUND"` and `"page": null`.

---

## Page 3 — Impact

### Who benefits

- **Journalists:** verify a statistic and go directly to the cited page.
- **Policy researchers:** search long reports without manually scanning every table.
- **Public officials:** retrieve figures with source evidence that can be checked.

### Why it matters

- Reduces time spent locating figures in lengthy reports.
- Makes answers auditable through page citations and source passages.
- Reduces unsupported guesses by validating numbers against extracted report text and allowing abstention.
- Supports new reports at runtime rather than relying on memorized answers for a single PDF.

### How we measure impact

We evaluate exact-match answer accuracy, citation accuracy, hallucination/abstention behavior, answerable-question recall, and runtime. These are evaluation measures; no performance score is claimed on this slide without a completed benchmark run.

---

## Page 4 — Limitations + Most Crucial Component

### Current limitations

- Multi-level table headers and tables continued across pages can make row-to-column matching ambiguous.
- OCR is a fallback for scanned pages, but recognition errors can corrupt names or numbers.
- Arbitrary charts and diagrams are not yet interpreted as visual data; page images are primarily for citation review.
- Retrieval only gives the model a limited set of candidate pages. If retrieval misses the evidence, the model cannot use it.
- The validator checks that a number appears on a cited page, but that alone cannot prove it came from the correct table column.
- A cloud LLM endpoint requires network access and is not suitable for an offline-only scoring environment.

### The crucial part: evidence quality

`src/qa/answerer.py` is the orchestration brain: it coordinates entity/metric extraction, exact cell lookup, retrieval, abstention, LLM calls, and validation. The most critical quality dependency is the **evidence pipeline**—accurate PDF/table extraction followed by retrieval of the right page. The answerer cannot recover a value that ingestion missed or retrieval failed to surface.

**Next priority:** improve table-header understanding and verify row/column extraction against manually checked pages before expanding to chart understanding or larger infrastructure.
