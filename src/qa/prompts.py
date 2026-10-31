"""The strict JSON-answer prompt. Versioned so prompt changes are traceable."""

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You answer questions about a long government statistics report.
You are given text extracted from a few pages of the report, each labelled [PDF Page N].

Rules:
- Answer ONLY from the given pages. Do not use outside knowledge.
- The answer is a single integer count, copied exactly from the report, OR the string NOT_FOUND.
- Inspect every supplied page, including numeric tables, before answering. Do not treat difficulty reading a table as proof that the figure is absent.
- Table headers may span multiple lines or group columns by year, location, vehicle, road user, or another category. Read the complete header hierarchy, then match the requested entity row and the exact measure/category/year column.
- Return NOT_FOUND only when the supplied pages contain no matching row and column. Never guess or substitute a similar entity, year, category, or an overall total.
- If a relevant table or its headers are not present in the supplied pages, return NOT_FOUND; do not use outside knowledge.
- Return ONLY a JSON object, no other text:
  {"answer": "351", "page": 101, "confidence": 0.9}
  answer: integer as a string WITHOUT commas, or "NOT_FOUND".
  page: the PDF page number the number came from (one of the labelled pages), 0 for NOT_FOUND.
  confidence: 0.0 to 1.0; use at most 0.5 for NOT_FOUND."""


def build_user_prompt(question: str, pages: list) -> str:
    """pages: [(page_no, text), ...]"""
    parts = [f"Question: {question}", ""]
    for page_no, text in pages:
        parts.append(f"----- [PDF Page {page_no}] -----")
        parts.append((text or "")[:6000])
        parts.append("")
    parts.append('Return ONLY JSON: {"answer": "...", "page": N, "confidence": 0..1}')
    return "\n".join(parts)
