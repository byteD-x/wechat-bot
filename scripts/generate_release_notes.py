from __future__ import annotations

import argparse
import sys
from pathlib import Path


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
