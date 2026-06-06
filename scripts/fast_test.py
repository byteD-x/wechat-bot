#!/usr/bin/env python3
"""Run focused test suites with minimal pytest plugin loading.

The normal CI command still runs the full pytest environment. This script is a
local feedback shortcut for AI/RAG changes where auto-loading unrelated pytest
plugins can dominate startup time or hang in some Windows environments.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class FastSuite:
    description: str
    targets: tuple[str, ...]
    plugins: tuple[str, ...] = ()


SUITES: dict[str, FastSuite] = {
    "ai-rag": FastSuite(
        description="RAG citation binding, retrieval metadata, and safety guard checks.",
        targets=("tests/test_rag_citations.py",),
        plugins=("pytest_asyncio.plugin",),
    ),
    "agent-runtime": FastSuite(
        description="Agent runtime context assembly and retriever integration checks.",
        targets=(
            "tests/test_agent_runtime.py::test_agent_runtime_prepare_request_aggregates_context",
            "tests/test_agent_runtime.py::test_agent_runtime_uses_cross_encoder_reranker_when_available",
        ),
        plugins=("pytest_asyncio.plugin",),
    ),
    "eval": FastSuite(
        description="Deterministic offline eval metrics and threshold checks.",
        targets=("tests/test_eval_runner.py",),
    ),
    "knowledge-base": FastSuite(
        description="Knowledge base ingestion, chunk metadata, and rebuild checks.",
        targets=("tests/test_knowledge_base.py",),
        plugins=("pytest_asyncio.plugin",),
    ),
    "tool-workflow": FastSuite(
        description="Controlled tool workflow retries, trace, and guardrail checks.",
        targets=("tests/test_tool_workflow.py",),
        plugins=("pytest_asyncio.plugin",),
    ),
}


def _build_command(suite: FastSuite, extra_args: list[str]) -> list[str]:
    command = [sys.executable, "-m", "pytest"]
    for plugin in suite.plugins:
        command.extend(["-p", plugin])
    command.extend(suite.targets)
    command.extend(extra_args or ["-q"])
    return command


def _run_suite(name: str, suite: FastSuite, extra_args: list[str]) -> int:
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    command = _build_command(suite, extra_args)
    print(f"[fast-test] {name}: {suite.description}")
    print("[fast-test] " + " ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)
    return int(completed.returncode)


def _list_suites() -> int:
    for name, suite in SUITES.items():
        targets = ", ".join(suite.targets)
        print(f"{name}: {suite.description} ({targets})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run focused fast test suites.")
    parser.add_argument(
        "suites",
        nargs="*",
        help="Suite names to run. Defaults to all suites.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available fast suites.",
    )
    parser.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        help="Extra argument passed through to pytest. Repeat for multiple args.",
    )
    args = parser.parse_args(argv)

    if args.list:
        return _list_suites()

    selected = list(args.suites or SUITES)
    unknown = [name for name in selected if name not in SUITES]
    if unknown:
        print(f"Unknown fast suite: {', '.join(unknown)}", file=sys.stderr)
        return 2

    exit_code = 0
    for name in selected:
        suite_code = _run_suite(name, SUITES[name], list(args.pytest_arg or []))
        if suite_code != 0:
            exit_code = suite_code
            break
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
