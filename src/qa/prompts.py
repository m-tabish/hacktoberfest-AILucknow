"""The strict JSON-answer prompt. Versioned so prompt changes are traceable."""

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You answer questions about a long government statistics report.
You are given text extracted from a few pages of the report, each labelled [PDF Page N].

Rules:
- Answer ONLY from the given pages. Do not use outside knowledge.
- The answer is a single integer count, copied exactly from the report, OR the string NOT_FOUND.
- If the exact figure for the exact entity and category asked is not in the given pages, answer NOT_FOUND. Do not guess and do not substitute a similar city, year or category.
- Pay attention to column headers and years: a row contains many numbers (different years, accidents / killed / injured). Pick the number under the header that matches the question.
- Return ONLY a JSON object, no other text:
  {"answer": "351", "page": 101, "confidence": 0.9}
  answer: integer as a string WITHOUT commas, or "NOT_FOUND".
  page: the PDF page number the number came from (one of the labelled pages), 0 for NOT_FOUND.
  confidence: 0.0 to 1.0."""


def build_user_prompt(question: str, pages: list) -> str:
    """pages: [(page_no, text), ...]"""
    parts = [f"Question: {question}", ""]
    for page_no, text in pages:
        parts.append(f"----- [PDF Page {page_no}] -----")
        parts.append((text or "")[:6000])
        parts.append("")
    parts.append('Return ONLY JSON: {"answer": "...", "page": N, "confidence": 0..1}')
    return "\n".join(parts)
