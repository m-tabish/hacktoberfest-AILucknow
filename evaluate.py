#!/usr/bin/env python3
"""Score answers.jsonl against gold questions_with_answers.jsonl.

Metrics: exact-match %, page accuracy % (predicted page in gold_pages),
NOT_FOUND precision / recall.

Usage:
  python evaluate.py --answers answers.jsonl --gold questions_with_answers.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_jsonl(path) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compute_metrics(answers: list, gold: list) -> dict:
    pred = {a["id"]: a for a in answers}
    n = len(gold)
    exact = 0
    page_ok = 0
    page_scored = 0
    tp = fp = fn = 0
    for g in gold:
        p = pred.get(g["id"])
        if p is None:
            continue
        gold_ans = str(g["answer"])
        pred_ans = str(p["answer"])
        if pred_ans == gold_ans:
            exact += 1
        if gold_ans == "NOT_FOUND":
            if pred_ans == "NOT_FOUND":
                tp += 1
            else:
                fn += 1
        else:
            if pred_ans == "NOT_FOUND":
                fp += 1
            page_scored += 1
            if int(p.get("page") or 0) in (g.get("gold_pages") or []):
                page_ok += 1
    return {
        "n": n,
        "answered": len(pred),
        "exact_match_pct": round(100 * exact / n, 1) if n else 0.0,
        "page_accuracy_pct": round(100 * page_ok / page_scored, 1) if page_scored else 0.0,
        "not_found_precision": round(tp / (tp + fp), 3) if (tp + fp) else 0.0,
        "not_found_recall": round(tp / (tp + fn), 3) if (tp + fn) else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Report Navigator — evaluation")
    ap.add_argument("--answers", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--out", help="optional path to write metrics JSON")
    args = ap.parse_args()
    metrics = compute_metrics(load_jsonl(args.answers), load_jsonl(args.gold))
    print(json.dumps(metrics, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
