from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SECTION_ORDER = (
    "## Features",
    "## Improvements",
    "## Fixes",
    "## Performance",
    "## Breaking Changes",
)
PRIMARY_SECTIONS = set(SECTION_ORDER[:4])
COMMIT_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
BANNED_PHRASES = (
    "misc changes",
    "bug fixes and improvements",
    "merge release branch",
    "bump version",
    "修复若干问题",
    "若干优化",
    "一些调整",
)


def fail(message: str) -> None:
    raise SystemExit(message)


def validate_tag(tag: str) -> str:
    match = TAG_RE.fullmatch(tag)
    if not match:
        fail("Release tag must match vX.Y.Z, for example v1.4.0.")
    return ".".join(match.groups())


def load_package_version(project_root: Path) -> str:
    package_path = project_root / "package.json"
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    version = str(payload.get("version") or "").strip()
    if not VERSION_RE.fullmatch(version):
        fail("package.json version must match X.Y.Z.")
    return version


def validate_release_notes(project_root: Path, tag: str) -> None:
    notes_path = project_root / "docs" / "release_notes" / f"{tag}.md"
    if not notes_path.is_file():
        fail(f"Missing release notes file: {notes_path}")

    text = notes_path.read_text(encoding="utf-8").strip()
    expected_title = f"# {tag} 更新内容"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line != expected_title:
        fail(f"Release notes title must be '{expected_title}'.")

    if "```" in text:
        fail("Release notes should use plain language bullets, not code blocks.")

    lowered = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in lowered:
            fail(f"Release notes contain banned phrase: {phrase}")

    for line in text.splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## ") or stripped.startswith("- "):
            continue
        fail("Release notes may only contain section headings and bullet items after the title.")

    headings = [line.strip() for line in text.splitlines() if line.strip().startswith("## ")]
    if not headings:
        fail("Release notes must include at least one section heading.")

    unknown_headings = [heading for heading in headings if heading not in SECTION_ORDER]
    if unknown_headings:
        fail(f"Unknown section headings: {', '.join(unknown_headings)}")

    positions = [SECTION_ORDER.index(heading) for heading in headings]
    if positions != sorted(positions) or len(set(headings)) != len(headings):
        fail("Release note sections must follow this order without duplicates: Features, Improvements, Fixes, Performance, Breaking Changes.")

    if not any(heading in PRIMARY_SECTIONS for heading in headings):
        fail("Release notes must include at least one of: Features, Improvements, Fixes, Performance.")

    lines = text.splitlines()
    for heading in headings:
        start = lines.index(heading)
        end = next((idx for idx in range(start + 1, len(lines)) if lines[idx].strip().startswith("## ")), len(lines))
        bullet_lines = [line for line in lines[start + 1:end] if line.strip().startswith("- ")]
        if not bullet_lines:
            fail(f"Section '{heading}' must contain at least one bullet. Use '- None.' when there is no item.")

    if COMMIT_HASH_RE.search(text):
        fail("Release notes must not contain commit hashes.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate release tag, package version, and release note structure.")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. v1.4.0")
    parser.add_argument(
        "--skip-version-match",
        action="store_true",
        help="Skip checking whether package.json version matches the target tag. Useful when validating historical release notes.",
    )
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[1]
    tag = str(args.tag or "").strip()
    version = validate_tag(tag)
    if not args.skip_version_match:
        package_version = load_package_version(project_root)
        if package_version != version:
            fail(f"package.json version '{package_version}' does not match tag '{tag}'.")

    validate_release_notes(project_root, tag)
    print(f"Release metadata validated for {tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
