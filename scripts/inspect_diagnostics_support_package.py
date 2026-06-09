#!/usr/bin/env python3
"""Inspect a redacted diagnostics support package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


MAX_TEXT_LENGTH = 240
MAX_LOG_ERRORS = 8

REDACTION_MARKERS = (
    "[redacted:",
    "****",
    "<redacted",
)

LOCAL_PATH_PATTERNS = (
    re.compile(r"\b[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\s\r\n]*"),
    re.compile(r"\b[A-Za-z]:/(?:[^/:\"<>|\s\r\n]+/)*[^/:\"<>|\s\r\n]*"),
    re.compile(r"(^|[\s\"'(])/(?:Users|home|var|tmp|private|mnt|Volumes|opt|etc)/[^\s\"',;)]+"),
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"\b(?:authorization\s*:\s*bearer|api[_-]?key|token|secret|password|session|oauth[_-]?session)\s*[=:]\s*[^\s,;\"']{6,}",
        re.IGNORECASE,
    ),
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:authorization\s*:\s*bearer|api[_-]?key|token|secret|password|session|oauth[_-]?session)\s*[=:]\s*[^\s,;\"']+",
    re.IGNORECASE,
)
CHAT_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:raw_content|message_content|message_text|chat_text|user_text|reply_text|last_message|latest_message)\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]+)",
    re.IGNORECASE,
)
CONTACT_PATTERN = re.compile(r"\b(?:wxid_[a-z0-9_-]+|[a-z0-9_-]+@chatroom)\b", re.IGNORECASE)

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "credential",
    "cookie",
    "session",
    "oauth",
    "authorization",
)
SAFE_SENSITIVE_KEYS = {
    "api_key_configured",
    "api_key_masked",
    "api_key_required",
    "langsmith_api_key_configured",
}
CHAT_CONTENT_KEYS = {
    "content",
    "raw_content",
    "message_content",
    "message_text",
    "chat_content",
    "chat_text",
    "user_text",
    "reply_text",
    "assistant_reply",
    "last_message",
    "latest_message",
    "message_preview",
    "messages",
    "recent_messages",
    "conversation",
    "chat_history",
    "history_messages",
    "prompt",
    "system_prompt",
}
CONTACT_KEYS = {
    "chat_id",
    "chat_ids",
    "roomid",
    "room_id",
    "wxid",
    "wx_id",
    "sender",
    "sender_id",
    "receiver",
    "receiver_id",
    "from_user",
    "to_user",
    "contact_id",
    "contact_name",
    "display_name",
    "nickname",
    "remark",
    "alias",
    "user_id",
}
PATH_KEY_PARTS = ("path", "dir", "file")


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _is_redacted_value(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in REDACTION_MARKERS)


def _normalize_key(key: str) -> str:
    return str(key or "").strip().lower()


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    if not normalized or normalized in SAFE_SENSITIVE_KEYS:
        return False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _is_chat_key(key: str) -> bool:
    return _normalize_key(key) in CHAT_CONTENT_KEYS


def _is_contact_key(key: str) -> bool:
    return _normalize_key(key) in CONTACT_KEYS


def _is_path_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(part in normalized for part in PATH_KEY_PARTS)


def _sanitize_path_segment(key: str) -> str:
    if _is_sensitive_key(key):
        return "[credential]"
    if _is_chat_key(key):
        return "[chat_content]"
    if _is_contact_key(key):
        return "[contact_identifier]"
    if _is_path_key(key):
        return "[local_path]"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(key or "field")).strip("_")
    return safe or "field"


def _truncate(text: str, limit: int = MAX_TEXT_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def sanitize_text(value: Any, *, limit: int = MAX_TEXT_LENGTH) -> str:
    text = str(value or "")
    text = SECRET_ASSIGNMENT_PATTERN.sub("[redacted: credential]", text)
    for pattern in SECRET_PATTERNS[:-1]:
        text = pattern.sub("[redacted: credential]", text)
    text = CHAT_ASSIGNMENT_PATTERN.sub("[redacted: chat content]", text)
    text = CONTACT_PATTERN.sub("[redacted: contact identifier]", text)
    text = LOCAL_PATH_PATTERNS[0].sub("[redacted: local path]", text)
    text = LOCAL_PATH_PATTERNS[1].sub("[redacted: local path]", text)
    text = LOCAL_PATH_PATTERNS[2].sub(
        lambda match: f"{match.group(1)}[redacted: local path]",
        text,
    )
    return _truncate(text.strip(), limit)


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return sanitize_text(value)


def _add_warning(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def _dict_at(parent: Any, *keys: str) -> dict[str, Any] | None:
    current = parent
    for key in keys:
        if not _is_mapping(current):
            return None
        current = current.get(key)
    return current if _is_mapping(current) else None


def _first_dict(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if _is_mapping(value):
            return value
    return None


def _first_list(*values: Any) -> list[Any] | None:
    for value in values:
        if isinstance(value, list):
            return value
    return None


def _scan_text(value: str, *, key: str = "") -> set[str]:
    if not value or _is_redacted_value(value):
        return set()

    categories: set[str] = set()
    if _is_sensitive_key(key) and value.strip():
        categories.add("credential")
    if _is_chat_key(key) and value.strip():
        categories.add("chat_content")
    if _is_contact_key(key) and value.strip():
        categories.add("contact_identifier")
    if _is_path_key(key) and value.strip():
        categories.add("local_path")
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        categories.add("credential")
    if CONTACT_PATTERN.search(value):
        categories.add("contact_identifier")
    if any(pattern.search(value) for pattern in LOCAL_PATH_PATTERNS):
        categories.add("local_path")
    if CHAT_ASSIGNMENT_PATTERN.search(value):
        categories.add("chat_content")
    return categories


def scan_sensitive_payload(payload: Any, *, source: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def visit(value: Any, path: str, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, f"{path}.{_sanitize_path_segment(child_key)}", str(child_key))
            return
        if isinstance(value, list):
            for index, child_value in enumerate(value):
                visit(child_value, f"{path}[{index}]", key)
            return
        if isinstance(value, str):
            for category in sorted(_scan_text(value, key=key)):
                findings.append(
                    {
                        "source": source,
                        "category": category,
                        "path": path,
                    }
                )

    visit(payload, "$")
    return findings


def summarize_manifest(payload: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    manifest = payload.get("manifest")
    if not _is_mapping(manifest):
        _add_warning(warnings, "manifest section is missing or invalid")
        return {"present": False}
    return {
        "present": True,
        "schema_version": _safe_value(manifest.get("schema_version")),
        "package_type": _safe_value(manifest.get("package_type")),
        "generated_at": _safe_value(manifest.get("generated_at") or payload.get("generated_at")),
        "automatic_upload": bool(manifest.get("automatic_upload")),
        "full_logs_included": bool(manifest.get("full_logs_included")),
    }


def summarize_readiness(readiness: dict[str, Any] | None, warnings: list[str]) -> dict[str, Any]:
    if not _is_mapping(readiness):
        _add_warning(warnings, "readiness section is missing or invalid")
        return {
            "present": False,
            "ready": None,
            "blocking_count": 0,
            "blocking_items": [],
            "suggested_actions": [],
        }

    checks = readiness.get("checks")
    if not isinstance(checks, list):
        _add_warning(warnings, "readiness.checks is missing or invalid")
        checks = []

    blocking_items: list[dict[str, Any]] = []
    for check in checks:
        if not _is_mapping(check):
            continue
        if check.get("status") != "failed" or check.get("blocking") is not True:
            continue
        blocking_items.append(
            {
                "key": sanitize_text(check.get("key")),
                "label": sanitize_text(check.get("label")),
                "status": sanitize_text(check.get("status")),
                "message": sanitize_text(check.get("message")),
                "hint": sanitize_text(check.get("hint")),
                "action": sanitize_text(check.get("action")),
            }
        )

    suggested_actions = []
    actions = readiness.get("suggested_actions")
    if isinstance(actions, list):
        for action in actions[:8]:
            if _is_mapping(action):
                suggested_actions.append(
                    {
                        "action": sanitize_text(action.get("action")),
                        "label": sanitize_text(action.get("label")),
                    }
                )
            else:
                suggested_actions.append({"action": sanitize_text(action), "label": ""})

    blocking_count = readiness.get("blocking_count")
    if not isinstance(blocking_count, int):
        blocking_count = len(blocking_items)

    return {
        "present": True,
        "ready": readiness.get("ready") if isinstance(readiness.get("ready"), bool) else None,
        "blocking_count": blocking_count,
        "blocking_items": blocking_items,
        "suggested_actions": suggested_actions,
    }


def summarize_update(update: dict[str, Any] | None, warnings: list[str]) -> dict[str, Any]:
    if not _is_mapping(update):
        _add_warning(warnings, "update section is missing or invalid")
        return {"present": False}

    integrity = update.get("integrity") if _is_mapping(update.get("integrity")) else {}
    checksum_verified = update.get("checksumVerified")
    if checksum_verified is None:
        checksum_verified = integrity.get("checksum_verified")

    return {
        "present": True,
        "enabled": bool(update.get("enabled")),
        "checking": bool(update.get("checking")),
        "available": bool(update.get("available")),
        "downloading": bool(update.get("downloading")),
        "ready_to_install": bool(update.get("readyToInstall")),
        "current_version": sanitize_text(update.get("currentVersion")),
        "latest_version": sanitize_text(update.get("latestVersion")),
        "downloaded_version": sanitize_text(
            update.get("downloadedVersion") or integrity.get("downloaded_version")
        ),
        "download_progress": _safe_value(update.get("downloadProgress")),
        "skipped_version": sanitize_text(update.get("skippedVersion")),
        "error": sanitize_text(update.get("error")),
        "checksum_verified": bool(checksum_verified),
    }


def summarize_logs(
    logs: list[Any] | None,
    runtime: dict[str, Any],
    snapshot: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    logs_present = isinstance(logs, list)
    if logs is None:
        _add_warning(warnings, "logs section is missing or invalid")
        logs = []

    total_sampled = len(logs)
    error_lines: list[str] = []
    for line in logs:
        text = str(line or "")
        lowered = text.lower()
        if any(marker in lowered for marker in ("error", "exception", "traceback", "failed", "critical")):
            error_lines.append(sanitize_text(text))
        if len(error_lines) >= MAX_LOG_ERRORS:
            break

    backend_errors: list[str] = []
    status = runtime.get("status") if _is_mapping(runtime.get("status")) else {}
    diagnostics = status.get("diagnostics") if _is_mapping(status.get("diagnostics")) else None
    if diagnostics:
        parts = [
            diagnostics.get("code"),
            diagnostics.get("title"),
            diagnostics.get("detail"),
            diagnostics.get("action_label"),
        ]
        summary = " | ".join(sanitize_text(part) for part in parts if str(part or "").strip())
        if summary:
            backend_errors.append(summary)
        suggestions = diagnostics.get("suggestions")
        if isinstance(suggestions, list):
            for suggestion in suggestions[:4]:
                if str(suggestion or "").strip():
                    backend_errors.append(sanitize_text(suggestion))

    collection_errors = snapshot.get("collection_errors")
    if isinstance(collection_errors, list):
        for item in collection_errors[:8]:
            if str(item or "").strip():
                backend_errors.append(sanitize_text(item))

    return {
        "present": logs_present,
        "total_sampled": total_sampled,
        "error_count": len(error_lines),
        "errors": error_lines,
        "backend_errors": backend_errors,
    }


def inspect_package(payload: dict[str, Any]) -> dict[str, Any]:
    if not _is_mapping(payload):
        raise ValueError("support package JSON must be an object")

    warnings: list[str] = []
    snapshot = payload.get("snapshot")
    if not _is_mapping(snapshot):
        _add_warning(warnings, "snapshot section is missing or invalid")
        snapshot = {}

    runtime = _dict_at(snapshot, "runtime") or {}
    readiness = _first_dict(
        _dict_at(snapshot, "runtime", "readiness"),
        snapshot.get("readiness"),
        payload.get("readiness"),
    )
    update = _first_dict(snapshot.get("update"), payload.get("update"))
    logs = _first_list(snapshot.get("logs"), payload.get("logs"))

    report: dict[str, Any] = {
        "success": True,
        "diagnostic_id": sanitize_text(payload.get("diagnostic_id")),
        "generated_at": sanitize_text(payload.get("generated_at")),
        "manifest": summarize_manifest(payload, warnings),
        "readiness": summarize_readiness(readiness, warnings),
        "update": summarize_update(update, warnings),
        "logs": summarize_logs(logs, runtime, snapshot, warnings),
        "warnings": warnings,
    }

    input_findings = scan_sensitive_payload(payload, source="input")
    output_findings = scan_sensitive_payload(report, source="output")
    redaction_passed = not input_findings and not output_findings
    report["redaction_passed"] = redaction_passed
    report["redaction"] = {
        "passed": redaction_passed,
        "input_findings_count": len(input_findings),
        "output_findings_count": len(output_findings),
        "findings": input_findings + output_findings,
    }
    return report


def inspect_support_package(path: str | Path) -> dict[str, Any]:
    package_path = Path(path)
    with package_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return inspect_package(payload)


def build_text_report(report: dict[str, Any]) -> str:
    lines = [
        "Diagnostics support package inspection",
        "-" * 46,
        f"Diagnostic ID: {report.get('diagnostic_id') or '<missing>'}",
        f"Generated at: {report.get('generated_at') or '<missing>'}",
    ]

    warnings = report.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")

    readiness = report.get("readiness") or {}
    lines.append("")
    lines.append(
        "Readiness: "
        f"ready={readiness.get('ready')} "
        f"blocking_count={readiness.get('blocking_count')}"
    )
    for item in readiness.get("blocking_items") or []:
        label = item.get("label") or item.get("key") or "<unknown>"
        message = item.get("message") or ""
        action = item.get("action") or ""
        suffix = f" action={action}" if action else ""
        lines.append(f"- {label}: {message}{suffix}")

    update = report.get("update") or {}
    lines.append("")
    if update.get("present"):
        lines.append(
            "Update: "
            f"enabled={update.get('enabled')} "
            f"available={update.get('available')} "
            f"latest={update.get('latest_version') or '<none>'} "
            f"ready_to_install={update.get('ready_to_install')} "
            f"checksum_verified={update.get('checksum_verified')}"
        )
        if update.get("error"):
            lines.append(f"- update_error: {update.get('error')}")
    else:
        lines.append("Update: <missing>")

    logs = report.get("logs") or {}
    lines.append("")
    lines.append(
        "Backend/log summary: "
        f"sampled={logs.get('total_sampled', 0)} "
        f"errors={logs.get('error_count', 0)}"
    )
    for item in logs.get("backend_errors") or []:
        lines.append(f"- backend: {item}")
    for item in logs.get("errors") or []:
        lines.append(f"- log: {item}")

    lines.append("")
    lines.append(f"Redaction passed: {bool(report.get('redaction_passed'))}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/inspect_diagnostics_support_package.py",
        description="Inspect a local diagnostics support package JSON file.",
    )
    parser.add_argument("package", help="Path to the diagnostics support package JSON file.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = inspect_support_package(args.package)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        error = {"success": False, "error": sanitize_text(exc)}
        if args.json:
            print(json.dumps(error, ensure_ascii=False, indent=2))
        else:
            print(f"Failed to inspect diagnostics support package: {error['error']}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(build_text_report(report))
    return 0 if report.get("redaction_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
