"""Number parsing and label/text normalisation.

The reports use Indian digit grouping (1,72,890). Stripping ALL commas handles
both Indian and Western grouping, which is all we need for integer counts.
"""
from __future__ import annotations

import re

_INT_TOKEN_RE = re.compile(r"^-?\d{1,3}(?:,\d{2,3})*$|^-?\d+$")
_NUM_TOKEN_RE = re.compile(r"^-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?$|^-?\d+(?:\.\d+)?$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def parse_int_token(token: str):
    """Return int for an integer-like token ('1,72,890' -> 172890), else None."""
    if token is None:
        return None
    t = str(token).strip().strip(".,;:")
    if not t:
        return None
    # a trailing '.' from sentence punctuation is ok, an internal one is a decimal
    if _INT_TOKEN_RE.match(t):
        try:
            return int(t.replace(",", ""))
        except ValueError:
            return None
    return None


def parse_number_token(token: str):
    """Return int/float for a numeric token, else None."""
    if token is None:
        return None
    t = str(token).strip().strip(".,;:")
    if not t or not _NUM_TOKEN_RE.match(t):
        return None
    try:
        v = float(t.replace(",", ""))
    except ValueError:
        return None
    return int(v) if v == int(v) else v


def extract_numbers(text: str) -> list:
    """All integer values in a text, in order, commas stripped."""
    out = []
    for tok in re.findall(r"-?\d{1,3}(?:,\d{2,3})+|-?\d+", text or ""):
        v = parse_int_token(tok)
        if v is not None:
            out.append(v)
    return out


def strip_commas_from_number_str(s: str) -> str:
    return str(s).replace(",", "").strip()


def normalize_label(s: str) -> str:
    """Lowercase, '&'->'and', punctuation stripped, spaces collapsed."""
    t = (s or "").lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def tokenize(text: str) -> list:
    """Lowercase alphanumeric tokens (len>=2) for BM25 / matching."""
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


def clean_text(text: str) -> str:
    t = (text or "").replace("\x00", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
