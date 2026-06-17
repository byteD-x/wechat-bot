#!/usr/bin/env python3
"""Run the local RAG evaluation demo used for interviews and regression checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "tests" / "fixtures" / "evals" / "rag_cases.json"
REPORT = PROJECT_ROOT / "data" / "evals" / "rag-smoke-report.json"


def main() -> int:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "run.py"),
        "eval",
        "--dataset",
        str(DATASET),
        "--preset",
        "rag-smoke",
        "--report",
        str(REPORT),
    ]
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    if completed.returncode != 0:
        return completed.returncode

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    summary = dict(payload.get("summary") or {})
    print("")
    print("RAG evaluation demo")
    print("-" * 50)
    print(f"cases: {summary.get('total_cases', 0)}")
    print(f"passed: {summary.get('passed')}")
    print(f"citation_accuracy: {summary.get('citation_accuracy')} ({summary.get('citation_eval_cases')} cases)")
    print(f"context_recall: {summary.get('context_recall')} ({summary.get('context_recall_eval_cases')} cases)")
    print(f"faithfulness: {summary.get('faithfulness')} ({summary.get('faithfulness_eval_cases')} cases)")
    print(
        "answer_citation_binding: "
        f"{summary.get('answer_citation_binding')} ({summary.get('answer_citation_binding_eval_cases')} cases)"
    )
    print(f"refusal_accuracy: {summary.get('refusal_accuracy')} ({summary.get('refusal_eval_cases')} cases)")
    print(f"report: {REPORT.relative_to(PROJECT_ROOT)}")
    return 0 if summary.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

