from __future__ import annotations

import argparse
import sys
from pathlib import Path


FORBIDDEN_SEGMENTS = {
    "chat_exports",
    "logs",
    "runtime",
    "vector_db",
    "win-unpacked",
}

FORBIDDEN_NAMES = {
    "api_keys.py",
    "app_config.json",
    "app-update.yml",
    "builder-debug.yml",
    "config_override.json",
    "chat_history.jsonl",
    "latest.yml",
    "provider_credentials.json",
    "oauth_creds.json",
    "google_accounts.json",
    ".credentials.json",
    "managed-settings.json",
}

FORBIDDEN_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
    ".blockmap",
    ".msi",
)


def normalize_path(value: Path) -> str:
    return value.as_posix().lower()


def scan_path(root: Path) -> list[str]:
    issues: list[str] = []
    for item in root.rglob("*"):
        normalized = normalize_path(item.relative_to(root))
        segments = set(part for part in normalized.split("/") if part)

        if segments & FORBIDDEN_SEGMENTS:
            issues.append(f"{root}: forbidden runtime path -> {normalized}")
            continue

        if item.name.lower() in FORBIDDEN_NAMES:
            issues.append(f"{root}: forbidden runtime file -> {normalized}")
            continue

        if item.is_file() and normalized.endswith(FORBIDDEN_SUFFIXES):
            issues.append(f"{root}: forbidden packaged artifact -> {normalized}")

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit packaged artifacts for forbidden runtime data.")
    parser.add_argument("paths", nargs="+", help="Artifact directories to scan")
    args = parser.parse_args(argv)

    issues: list[str] = []
    for raw_path in args.paths:
        path = Path(raw_path).resolve()
        if not path.exists():
            issues.append(f"missing artifact path -> {path}")
            continue
        issues.extend(scan_path(path))

    if issues:
        print("Artifact audit failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Artifact audit passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
