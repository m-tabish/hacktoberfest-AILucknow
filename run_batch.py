#!/usr/bin/env python3
"""Batch runner: ingest a report PDF (if given), answer a questions .jsonl,
and write answers.jsonl in the sample submission format.

Usage:
  python run_batch.py --pdf report_A.pdf --questions questions.jsonl --out answers.jsonl
  python run_batch.py --doc-id <doc_id> --questions questions.jsonl --out answers.jsonl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.services import batch_service, ingest_service


def main() -> int:
    ap = argparse.ArgumentParser(description="Report Navigator — batch QA")
    ap.add_argument("--pdf", help="Report PDF to ingest (skips ingestion if already ready)")
    ap.add_argument("--doc-id", help="Use an already-ingested document id instead of --pdf")
    ap.add_argument("--questions", required=True, help="questions .jsonl (id, question)")
    ap.add_argument("--out", default="answers.jsonl", help="output answers .jsonl")
    ap.add_argument("--force", action="store_true", help="force re-ingestion")
    args = ap.parse_args()

    doc_id = args.doc_id
    if args.pdf:
        def progress(frac, msg):
            print(f"[{frac*100:5.1f}%] {msg}", flush=True)

        stats = ingest_service.ingest_pdf(args.pdf, progress=progress, force=args.force)
        doc_id = stats["doc_id"]
        print(f"Ingested doc_id={doc_id} pages={stats['pages']} chunks={stats['chunks']} "
              f"table_rows={stats['table_rows']} ocr_pages={stats['ocr_pages']} "
              f"faiss={stats['faiss']} reused={stats['reused']}")
    if not doc_id:
        ap.error("either --pdf or --doc-id is required")

    questions = batch_service.load_questions(args.questions)
    print(f"Answering {len(questions)} questions…")
    answers = batch_service.run_batch(doc_id, questions)
    batch_service.write_answers_jsonl(answers, args.out)
    print(f"Wrote {len(answers)} answers to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
