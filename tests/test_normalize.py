"""Unit tests for normalize + validator. Run: python -m pytest tests/test_normalize.py
(or plain `python tests/test_normalize.py`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest.normalize import (extract_numbers, normalize_label,
                                  parse_int_token, parse_number_token)
from src.qa.validator import clean_answer_value, validate_llm_result


def test_indian_grouping():
    assert parse_int_token("1,72,890") == 172890
    assert parse_int_token("4,61,312") == 461312
    assert parse_int_token("351") == 351
    assert parse_int_token("12,345") == 12345


def test_non_integers_rejected():
    assert parse_int_token("3.5") is None
    assert parse_int_token("abc") is None
    assert parse_int_token("") is None
    assert parse_number_token("3.5") == 3.5
    assert parse_number_token("-2.3") == -2.3


def test_extract_numbers():
    assert extract_numbers("Total 4,61,312 and 1,72,890 deaths") == [461312, 172890]


def test_normalize_label():
    assert normalize_label("Vadodra") == "vadodra"
    assert normalize_label("Allahabad (Prayagraj)") == "allahabad prayagraj"
    assert normalize_label("Cars, Taxis & LMVs") == "cars taxis and lmvs"


def test_clean_answer_value():
    assert clean_answer_value("1,230") == "1230"
    assert clean_answer_value("NOT_FOUND") == "NOT_FOUND"
    assert clean_answer_value("The answer is 351.") == "351"
    assert clean_answer_value("unknown") is None


def test_validate_llm_result():
    pages = {101: "Pune 1,230 accidents 351 killed", 102: "other"}
    out = validate_llm_result({"answer": "351", "page": 101, "confidence": 0.4},
                              [101, 102], pages)
    assert out == {"answer": "351", "page": 101, "confidence": 0.85}
    # wrong page gets relocated to the page containing the number
    out = validate_llm_result({"answer": "351", "page": 102, "confidence": 0.9},
                              [101, 102], pages)
    assert out["page"] == 101
    # number on no candidate page -> kept but confidence capped (LLM may have
    # computed it); page outside the candidate set -> invalid
    out = validate_llm_result({"answer": "999", "page": 101, "confidence": 0.9},
                              [101, 102], pages)
    assert out["page"] == 101 and out["confidence"] <= 0.6
    assert validate_llm_result({"answer": "999", "page": 77, "confidence": 0.9},
                                [101, 102], pages) is None
    out = validate_llm_result({"answer": "NOT_FOUND", "page": 55, "confidence": 0.7},
                              [101], pages)
    assert out["answer"] == "NOT_FOUND" and out["page"] == 0


if __name__ == "__main__":
    for name, fn in sorted(dict(globals()).items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
