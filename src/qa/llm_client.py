"""LLM client via stdlib urllib — any OpenAI-compatible endpoint.

No `openai` package dependency. If LLM_API_KEY is empty, is_configured() is
False and callers must use their non-LLM paths (cell_lookup / abstain /
fallback). Failures return None, never raise.
"""
from __future__ import annotations

import json
import re
import urllib.request

from src import config


def is_configured() -> bool:
    return bool(config.LLM_API_KEY)


def chat(messages: list, temperature: float = 0.0) -> str | None:
    if not is_configured():
        return None
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        f"{config.LLM_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LLM_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def complete_json(system: str, user: str) -> dict | None:
    """Chat and parse a JSON object out of the reply (tolerant of fences)."""
    content = chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    if not content:
        return None
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except Exception:
        return None
