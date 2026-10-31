#!/usr/bin/env python3
"""Gemini-backed scoring entry point for Report Navigator.

Usage: python predict.py --pdf report.pdf --questions questions.jsonl --output answers.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

MAX_RUNTIME_SECONDS = 20 * 60
MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_QUESTIONS_BYTES = 5 * 1024 * 1024


def _validate_paths(pdf: Path, questions: Path, output: Path) -> None:
    if not pdf.is_file():
        raise ValueError("PDF path does not point to a readable file")
    if pdf.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 256 MiB input limit")
    with pdf.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError("Input file is not a PDF")
    if not questions.is_file():
        raise ValueError("Questions path does not point to a readable file")
    if questions.stat().st_size > MAX_QUESTIONS_BYTES:
        raise ValueError("Questions JSONL exceeds the 5 MiB input limit")
    if output.resolve() in (pdf.resolve(), questions.resolve()):
        raise ValueError("Output path must not overwrite the PDF or questions file")


def _validate_answers(answers: list, questions: list, page_count: int) -> None:
    if len(answers) != len(questions):
        raise ValueError("Inference did not produce exactly one answer per question")
    for index, (answer, question) in enumerate(zip(answers, questions), start=1):
        if not isinstance(answer, dict) or set(answer) != {
            "id", "answer", "page", "confidence"
        }:
            raise ValueError(f"Answer {index} does not match the required output schema")
        if answer["id"] != question["id"]:
            raise ValueError(f"Answer {index} does not preserve its input id")
        value = answer["answer"]
        page = answer["page"]
        if value == "NOT_FOUND":
            if page is not None:
                raise ValueError(f"Answer {index}: NOT_FOUND must have page null")
        elif not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
            raise ValueError(f"Answer {index}: answer must be digits or NOT_FOUND")
        elif isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= page_count:
            raise ValueError(f"Answer {index}: page must be a valid 1-based PDF page")
        confidence = answer["confidence"]
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError(f"Answer {index}: confidence must be finite and between 0 and 1")


def main() -> int:
    parser = argparse.ArgumentParser(description="Gemini-backed Report Navigator prediction")
    parser.add_argument("--pdf", required=True, help="Report PDF to index for this run")
    parser.add_argument("--questions", required=True, help="Input JSONL with id and question")
    parser.add_argument("--output", required=True, help="Destination answers JSONL")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    questions_path = Path(args.questions).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    temporary_output = None
    try:
        _validate_paths(pdf_path, questions_path, output_path)

        # Set the per-run data directory before importing project modules.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        questions = None
        answers = None
        with tempfile.TemporaryDirectory(prefix="report-navigator-") as work_dir:
            os.environ["REPORT_NAVIGATOR_DATA_DIR"] = work_dir
            from src.ingest.pdf_loader import open_pdf
            from src.services import batch_service, ingest_service

            questions = batch_service.load_questions(questions_path)
            with open_pdf(pdf_path) as pdf:
                if pdf.needs_pass:
                    raise ValueError("Encrypted PDFs are not supported")
                page_count = len(pdf)
            if page_count < 1:
                raise ValueError("PDF contains no pages")

            started = time.monotonic()

            def check_deadline(_fraction=None, _message=None):
                if time.monotonic() - started > MAX_RUNTIME_SECONDS:
                    raise TimeoutError("The 20-minute prediction time limit was reached")

            check_deadline()
            stats = ingest_service.ingest_pdf(pdf_path, progress=check_deadline)
            answers = batch_service.run_batch(
                stats["doc_id"], questions, progress=check_deadline)
            check_deadline()
            _validate_answers(answers, questions, page_count)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output_path.parent,
            prefix=f".{output_path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_output = Path(stream.name)
            for answer in answers:
                stream.write(json.dumps(answer, ensure_ascii=False, allow_nan=False) + "\n")
        os.replace(temporary_output, output_path)
        temporary_output = None
        print(f"Wrote {len(answers)} answer records to {output_path}")
        return 0
    except Exception as exc:
        print(f"Prediction failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
