# UI and HTTP API Architecture

## Product shape

Provide a simple upload/results UI and an HTTP endpoint for receiving a PDF and its questions and returning answers. Keep implementation choices framework-neutral: UI and server frameworks are replaceable adapters, not part of the answer pipeline.

## Two entry points, one inference path

```text
Official scoring (offline)                  Upload/results flow
--------------------------                  -------------------
predict.py --pdf --questions --output       UI
              |                               |
              +--------> shared pipeline <--- HTTP API
                               |
                       answers JSONL
```

The event scorer runs `predict.py` directly with local files and no network. The UI calls the HTTP API. Both use the same inference code, validation, and answer schema. If organizers expect the scorer itself to call a public endpoint instead of the published offline CLI, document that exception and its exact protocol before changing the scoring interface.

## HTTP contract

Unless organizers provide a definitive protocol, use this small default:

- `POST /predict`
- Multipart fields: `pdf` (one PDF) and `questions` (JSONL with `id` and `question` per line).
- Success: `200 OK`, `application/x-ndjson`, one record per question with `id`, `answer`, `page`, and `confidence`.
- Errors: `400` for malformed input, `413` for oversized files, `422` for structurally invalid questions, and a safe generic `500` for unexpected processing errors.

The HTTP response must match the CLI output schema. For `NOT_FOUND`, `page` is `null`; otherwise it is a 1-based physical PDF page index. Do not return traces or extracted report content.

## Component responsibilities

### Shared inference core

- Build the report index from the supplied PDF at runtime.
- Accept local paths or validated input records without depending on HTTP or UI libraries.
- Return validated answer records; leave transport and presentation to adapters.
- Stay within the event's 20-minute, 2-CPU, 6-GB scoring limits.

### HTTP adapter

- Validate multipart fields, file sizes, PDF input, JSONL encoding, required fields, and unique IDs.
- Write uploads to a private temporary directory with generated filenames, never client-supplied paths.
- Call the shared inference core and return a complete JSONL response.
- Remove temporary uploads and derived files on success and all error paths.
- Do not log filenames, question contents, answers, extracted text, or uploaded data. Log only safe operational details such as request ID, duration, and status.
- Bound concurrent jobs and request time. Return clear errors when capacity or time limits are reached.
- Do not retain uploaded data after the response unless organizers explicitly require retention.

### UI adapter

- Let a user select the PDF and matching questions JSONL, submit them, inspect answer/page/confidence rows, and download the returned JSONL.
- Show validation and processing errors plainly; never display server traces.
- Call the HTTP API. Do not implement separate parsing, retrieval, or answer extraction.

## Public exposure and secret inputs

Before public exposure, use HTTPS, authentication, request-size limits, safe temporary-file handling, and an owner for service uptime. Keep credentials in deployment configuration, not source code or client-visible UI configuration.

Treat organizer-provided hidden data as confidential: do not persist it, include it in logs, or commit it to Git. If organizers require asynchronous processing or a callback, document that contract before implementing it.

## Acceptance checks

- The CLI still meets the published command and runs with networking disabled.
- API and CLI produce schema-equivalent results for the same PDF and questions.
- Invalid JSONL, duplicate/missing IDs, non-PDF input, and oversized files fail safely.
- Temporary uploads are deleted after success and error paths; logs contain no document or question contents.
- Request concurrency is bounded and a valid request completes within available time and memory.
- The UI can upload both files, display results, and download the JSONL response.
- If organizers specify a protocol, use their path, field names, authentication, and response format instead of defaults here.
