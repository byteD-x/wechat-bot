from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RELEASE_TYPE_ORDER = ("feat", "fix", "docs", "refactor", "test", "chore", "build", "ci", "other")
RELEASE_TYPE_LABELS = {
    "feat": "功能新增",
    "fix": "问题修复",
    "docs": "文档更新",
    "refactor": "代码重构",
    "test": "测试改进",
    "chore": "杂项维护",
    "build": "构建与发布",
    "ci": "CI/CD",
    "other": "其他变更",
}
CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|docs|refactor|test|chore|build|ci)(?:\([^)]+\))?(?P<breaking>!)?:\s*(?P<subject>.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CommitEntry:
    full_sha: str
    short_sha: str
    subject: str


def run_git(args: Iterable[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


def load_repository_url(project_root: Path) -> str:
    package_path = project_root / "package.json"
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    repository = payload.get("repository")
    raw_url = repository if isinstance(repository, str) else (repository or {}).get("url", "")
    normalized = str(raw_url or "").strip().removeprefix("git+")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@github.com:"):
        normalized = f"https://github.com/{normalized.split(':', 1)[1]}"
    return normalized


def list_release_tags(current_tag: str) -> list[str]:
    tags = [
        tag.strip()
        for tag in run_git(["tag", "--sort=-creatordate"]).splitlines()
        if tag.strip()
    ]
    return [tag for tag in tags if tag != current_tag]


def resolve_previous_tag(current_tag: str) -> str:
    for tag in list_release_tags(current_tag):
        if tag.lower().startswith("v"):
            return tag
    return ""


def list_commits(previous_tag: str, current_tag: str) -> list[CommitEntry]:
    if previous_tag:
        target = f"{previous_tag}..{current_tag}"
        args = ["log", "--format=%H%x1f%h%x1f%s", target]
    else:
        args = ["log", "--format=%H%x1f%h%x1f%s", current_tag]

    output = run_git(args)
    commits: list[CommitEntry] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        full_sha, short_sha, subject = line.split("\x1f", 2)
        commits.append(CommitEntry(full_sha=full_sha, short_sha=short_sha, subject=subject.strip()))
    return commits


def classify_commit(subject: str) -> tuple[str, str, bool]:
    match = CONVENTIONAL_RE.match(subject.strip())
    if not match:
        return "other", subject.strip(), False
    commit_type = match.group("type").lower()
    clean_subject = match.group("subject").strip()
    breaking = bool(match.group("breaking"))
    return commit_type, clean_subject, breaking


def group_commits(commits: Iterable[CommitEntry]) -> dict[str, list[tuple[CommitEntry, str, bool]]]:
    grouped = {key: [] for key in RELEASE_TYPE_ORDER}
    for commit in commits:
        commit_type, clean_subject, breaking = classify_commit(commit.subject)
        grouped.setdefault(commit_type, []).append((commit, clean_subject, breaking))
    return grouped


def build_compare_url(repository_url: str, previous_tag: str, current_tag: str) -> str:
    if not repository_url or not previous_tag:
        return ""
    return f"{repository_url}/compare/{previous_tag}...{current_tag}"


def render_release_notes(current_tag: str, previous_tag: str, repository_url: str, commits: list[CommitEntry]) -> str:
    grouped = group_commits(commits)
    lines = [f"# {current_tag} 更新说明", ""]
    lines.append("本次更新聚焦于稳定性、可观测性和桌面端使用体验，重点减少误配置带来的行为漂移，并让问题定位和复盘更直接。")
    lines.append("")

    section_specs = [
        ("功能与体验", ("feat", "refactor")),
        ("稳定性与修复", ("fix",)),
        ("工程与质量", ("ci", "build", "test", "docs", "chore")),
    ]

    rendered_any = False
    for title, kinds in section_specs:
        items: list[str] = []
        for kind in kinds:
            for _, clean_subject, breaking in grouped.get(kind, []):
                suffix = "（含破坏性调整）" if breaking else ""
                items.append(f"- {clean_subject}{suffix}")
        if not items:
            continue
        rendered_any = True
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(items[:8])
        lines.append("")

    if not rendered_any:
        lines.append("## 本次更新")
        lines.append("")
        lines.append("- 优化了应用的整体稳定性与日常使用体验。")
        lines.append("")

    lines.append("## 升级建议")
    lines.append("")
    lines.append("- 桌面端用户更新后建议先检查一次设置页与消息详情里的 Prompt 配置，确认自定义规则符合当前使用习惯。")
    lines.append("- 如你依赖成本分析或回复复盘，请在“成本管理”页确认筛选条件、导出内容和建议动作是否符合预期。")
    lines.append("- 若本次更新涉及桌面端安装包替换，建议完成更新后重启应用一次，以确保主进程与后端组件使用同一版本。")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate GitHub Release notes from commits since the previous tag.")
    parser.add_argument("--current-tag", required=True, help="Current release tag, e.g. v1.2.0")
    parser.add_argument("--output", help="Write release notes to a file instead of stdout")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[1]
    current_tag = str(args.current_tag or "").strip()
    if not current_tag:
        raise SystemExit("current tag is required")

    previous_tag = resolve_previous_tag(current_tag)
    repository_url = load_repository_url(project_root)
    commits = list_commits(previous_tag, current_tag)
    notes = render_release_notes(current_tag, previous_tag, repository_url, commits)

    if args.output:
        Path(args.output).write_text(notes, encoding="utf-8")
    else:
        print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
