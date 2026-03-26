#!/usr/bin/env python3
"""项目环境自检脚本。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.readiness import readiness_service


def _print_result(label: str, result: Optional[bool], message: str) -> str:
    if result is None:
        icon = "⏭"
    else:
        icon = "✅" if result else "❌"
    return f"{icon} {label}: {message}"


def _resolve_suggestion(check: dict) -> str:
    key = str(check.get("key") or "").strip()
    if key == "admin_permission":
        return "桌面端可直接点击“以管理员身份重新启动”，或手动使用“以管理员身份运行”重新启动应用。"
    return str(check.get("hint") or "").strip()


def build_text_report(report: dict) -> str:
    lines = [
        "",
        "微信 AI 助手环境检查",
        "-" * 50,
        "",
    ]
    issues = []
    suggestions = []

    for check in report.get("checks", []):
        status = check.get("status")
        passed = None if status == "skipped" else status == "passed"
        lines.append(
            _print_result(
                str(check.get("label") or ""),
                passed,
                str(check.get("message") or ""),
            )
        )
        if status == "failed" and check.get("blocking"):
            issues.append(str(check.get("message") or check.get("label") or ""))
            hint = _resolve_suggestion(check)
            if hint:
                suggestions.append(hint)

    lines.extend(["", "-" * 50])

    if report.get("ready"):
        lines.append("✅ 检查通过，可以继续运行项目。")
        return "\n".join(lines)

    lines.append(f"❌ 发现 {len(issues)} 个阻塞问题")
    for issue in issues:
        lines.append(f"  - {issue}")

    if suggestions:
        lines.extend(["", "建议操作:"])
        seen = set()
        for suggestion in suggestions:
            if suggestion in seen:
                continue
            seen.add(suggestion)
            lines.append(f"  - {suggestion}")

    return "\n".join(lines)


def run_check(*, json_output: bool = False, force_refresh: bool = True) -> int:
    report = readiness_service.get_report(force_refresh=force_refresh)
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(build_text_report(report))
    return 0 if report.get("ready") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/check.py",
        description="运行 readiness 环境检查。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出完整 readiness 报告。",
    )
    parser.add_argument(
        "--cached",
        action="store_true",
        help="复用短 TTL 缓存，不强制刷新 readiness 检查。",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return run_check(
        json_output=bool(args.json),
        force_refresh=not bool(args.cached),
    )


if __name__ == "__main__":
    raise SystemExit(main())
