"""Batch service: many questions -> answers.jsonl in the sample format."""
from __future__ import annotations

import json
from pathlib import Path

from src import db
from src.qa.answerer import answer_question


def run_batch(doc_id: str, questions: list, progress=None) -> list:
    """questions: [{'id':..., 'question':...}] -> [submission dicts]."""
    conn = db.connect()
    try:
        db.init_db(conn)
        out = []
        for i, q in enumerate(questions):
            if progress:
                progress(i / max(len(questions), 1), f"{q.get('id')} — {q.get('question','')[:60]}")
            ans = answer_question(conn, doc_id, q["question"], qid=q.get("id"))
            out.append(ans.to_submission_dict())
        if progress:
            progress(1.0, "Done")
        return out
    finally:
        conn.close()


def load_questions(path: str | Path) -> list:
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                questions.append({"id": d.get("id"), "question": d.get("question", "")})
    return questions


def write_answers_jsonl(answers: list, path: str | Path) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for a in answers:
            f.write(json.dumps(a) + "\n")
    return str(path)
