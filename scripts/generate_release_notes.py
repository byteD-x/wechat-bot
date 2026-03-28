from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\([^)]+\))?(?P<breaking>!)?:\s*(?P<subject>.+)$"
)


@dataclass(frozen=True)
class CommitEntry:
    full_sha: str
    short_sha: str
    subject: str


def classify_commit(subject: str) -> tuple[str, str, bool]:
    text = str(subject or "").strip()
    match = _CONVENTIONAL_COMMIT_PATTERN.match(text)
    if not match:
        return "other", text, False

    commit_type = match.group("type").lower()
    is_breaking = bool(match.group("breaking"))
    normalized_subject = match.group("subject").strip()
    return commit_type, normalized_subject, is_breaking


def build_compare_url(repository_url: str, previous_tag: str, current_tag: str) -> str:
    base_url = str(repository_url or "").strip().removesuffix(".git").rstrip("/")
    return f"{base_url}/compare/{previous_tag}...{current_tag}"


def _render_commit_group(commits: Iterable[CommitEntry]) -> list[str]:
    lines: list[str] = []
    for commit in commits:
        commit_type, normalized_subject, _ = classify_commit(commit.subject)
        _ = commit_type
        lines.append(f"- {normalized_subject} (`{commit.short_sha}`)")
    if not lines:
        lines.append("- 无")
    return lines


def render_release_notes(
    *,
    current_tag: str,
    previous_tag: str,
    repository_url: str,
    commits: list[CommitEntry],
) -> str:
    feature_commits: list[CommitEntry] = []
    fix_commits: list[CommitEntry] = []
    other_commits: list[CommitEntry] = []

    for commit in commits:
        commit_type, _, _ = classify_commit(commit.subject)
        if commit_type == "feat":
            feature_commits.append(commit)
        elif commit_type == "fix":
            fix_commits.append(commit)
        else:
            other_commits.append(commit)

    lines: list[str] = [f"# {current_tag} 更新说明", ""]
    if previous_tag:
        compare_url = build_compare_url(repository_url, previous_tag, current_tag)
        lines.extend(
            [
                f"Compare 链接: [`{previous_tag}...{current_tag}`]({compare_url})",
                "",
            ]
        )
    else:
        lines.extend(["这是首个正式版本。", ""])

    lines.extend(["### 功能新增", *_render_commit_group(feature_commits), ""])
    lines.extend(["### 问题修复", *_render_commit_group(fix_commits), ""])
    lines.extend(["### 其他变更", *_render_commit_group(other_commits), ""])

    lines.append("## 原始提交列表")
    if commits:
        for commit in commits:
            lines.append(f"- `{commit.short_sha}` {commit.subject}")
    else:
        lines.append("- 无")

    return "\n".join(lines).strip()


def load_release_notes(project_root: Path, tag: str) -> str:
    notes_path = project_root / "docs" / "release_notes" / f"{tag}.md"
    if not notes_path.is_file():
        raise SystemExit(f"Missing release notes file: {notes_path}")
    return notes_path.read_text(encoding="utf-8").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load manual GitHub Release notes for a tag.")
    parser.add_argument("--current-tag", required=True, help="Current release tag, e.g. v1.4.0")
    parser.add_argument("--output", help="Write release notes to a file instead of stdout")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[1]
    tag = str(args.current_tag or "").strip()
    if not tag:
        raise SystemExit("current tag is required")

    notes = load_release_notes(project_root, tag)
    if args.output:
        Path(args.output).write_text(notes, encoding="utf-8")
    else:
        print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
