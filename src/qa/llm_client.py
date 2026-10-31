"""LLM client via stdlib urllib — any OpenAI-compatible endpoint.

No `openai` package dependency. If LLM_API_KEY is empty, is_configured() is
False and callers must use their non-LLM paths (cell_lookup / abstain /
fallback). Failures return None, never raise.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from src import config

logger = logging.getLogger(__name__)
last_error = ""


def is_configured() -> bool:
    return bool(config.LLM_API_KEY)


def chat(messages: list, temperature: float = 0.0, trace: dict | None = None) -> str | None:
    global last_error
    last_error = ""
    if not is_configured():
        last_error = "LLM_API_KEY is empty."
        return None
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if trace is not None:
        trace.update({
            "endpoint": f"{config.LLM_BASE_URL}/chat/completions",
            "request": payload,
            "status": "sending",
        })
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
            raw_body = resp.read().decode("utf-8", errors="replace")
            if trace is not None:
                trace.update({"status": resp.status, "response": raw_body})
            data = json.loads(raw_body)
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return content
        # Some OpenAI-compatible providers return content as typed text parts.
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        last_error = "Gemini returned an unsupported response format."
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        # Provider error payloads are useful for diagnosis; never echo credentials.
        body = body.replace(config.LLM_API_KEY, "<redacted>")
        if trace is not None:
            trace.update({"status": exc.code, "response": body})
        last_error = f"Gemini API returned HTTP {exc.code}: {(body or str(exc.reason))[:1000]}"
    except (urllib.error.URLError, TimeoutError) as exc:
        if trace is not None:
            trace.update({"status": "error", "error": str(exc)})
        last_error = f"Could not reach Gemini API: {exc}"
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        if trace is not None:
            trace.update({"status": "error", "error": str(exc)})
        last_error = f"Gemini returned an invalid response: {exc}"
    except Exception as exc:
        if trace is not None:
            trace.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        last_error = f"Gemini request failed: {type(exc).__name__}: {exc}"
    if last_error:
        logger.warning("%s", last_error)
    return None


def complete_json(system: str, user: str, trace: dict | None = None) -> dict | None:
    """Chat and parse a JSON object out of the reply (tolerant of fences)."""
    global last_error
    content = chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], trace=trace)
    if not content:
        return None
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        last_error = "Gemini responded, but did not return a JSON object."
        return None
    try:
        out = json.loads(m.group(0))
        if isinstance(out, dict):
            return out
        last_error = "Gemini returned JSON, but it was not an object."
    except json.JSONDecodeError as exc:
        last_error = f"Gemini returned malformed JSON: {exc.msg}."
        return None
    return None
