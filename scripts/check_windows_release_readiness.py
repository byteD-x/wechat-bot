from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


SETUP_RE = re.compile(r"^wechat-ai-assistant-setup-(?P<version>\d+\.\d+\.\d+)\.exe$")
PORTABLE_RE = re.compile(r"^wechat-ai-assistant-portable-(?P<version>\d+\.\d+\.\d+)-x64\.exe$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
CHECKSUM_FILE_NAME = "SHA256SUMS.txt"
UPDATE_METADATA_FILE_NAME = "latest.yml"
OFFICIAL_SIGNED_CHANNEL = "official_signed"
COMMUNITY_UNSIGNED_CHANNEL = "community_unsigned"
REPO_ROOT = Path(__file__).resolve().parents[1]

ELECTRON_SECURITY_BASELINE = (
    {
        "file": "src/main/index.js",
        "label": "BrowserWindow hardening and navigation boundary",
        "markers": (
            "contextIsolation: true",
            "nodeIntegration: false",
            "sandbox: true",
            "webSecurity: true",
            "setWindowOpenHandler",
            "will-navigate",
            "will-redirect",
        ),
    },
    {
        "file": "src/preload/index.js",
        "label": "Preload exposes a narrow contextBridge API",
        "markers": (
            "contextBridge.exposeInMainWorld('electronAPI'",
            "ipcRenderer.invoke('backend:request'",
            "ipcRenderer.invoke('knowledge-base:select-file'",
            "ipcRenderer.invoke('export-diagnostics-snapshot'",
        ),
    },
    {
        "file": "src/main/ipc.js",
        "label": "IPC sender checks and backend request allowlist",
        "markers": (
            "assertTrustedRendererSender",
            "handleTrusted",
            "ALLOWED_BACKEND_PATHS",
            "ALLOWED_BACKEND_PATH_PATTERNS",
            "endpoint_not_allowed",
            "payload_too_large",
            "payload_not_allowed_for_get",
            "knowledge-base:select-file",
            "source_file: `.../${name}`",
        ),
    },
    {
        "file": "src/main/diagnostics-snapshot.js",
        "label": "Diagnostics support package redaction boundary",
        "markers": (
            "[redacted: sensitive value]",
            "[redacted: chat content]",
            "[redacted: contact identifier]",
            "[redacted: local path]",
            "redacted_categories",
            "privacy_notice",
        ),
    },
)


@dataclass(frozen=True)
class ReleaseExecutable:
    kind: str
    name: str
    path: Path
    version: str
    sha256: str
    size: int


@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    status: str
    blocking: bool
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class SignatureResult:
    status: str
    blocking: bool
    authenticode_status: str
    message: str
    details: dict[str, Any]


SignatureChecker = Callable[[Path], SignatureResult]
Runner = Callable[..., subprocess.CompletedProcess[str]]


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256sums(path: Path) -> tuple[dict[str, str], list[str]]:
    checksums: dict[str, str] = {}
    issues: list[str] = []
    if not path.is_file():
        return checksums, [f"Missing {CHECKSUM_FILE_NAME}"]

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            issues.append(f"Invalid checksum line {line_number}: {raw_line!r}")
            continue
        checksum, filename = parts
        filename = filename.strip().lstrip("*")
        if not SHA256_RE.fullmatch(checksum):
            issues.append(f"Invalid SHA256 value on line {line_number}: {checksum}")
            continue
        if filename in checksums:
            issues.append(f"Duplicate checksum entry: {filename}")
            continue
        checksums[filename] = checksum.lower()

    return checksums, issues


def _split_yaml_key_value(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip()


def _parse_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_latest_yml(path: Path) -> tuple[dict[str, Any], list[str]]:
    metadata: dict[str, Any] = {"files": []}
    issues: list[str] = []
    if not path.is_file():
        return metadata, [f"Missing {UPDATE_METADATA_FILE_NAME}"]

    current_section: str | None = None
    current_file: dict[str, str] | None = None
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0:
            current_section = None
            current_file = None
            parsed = _split_yaml_key_value(line)
            if parsed is None:
                issues.append(f"Invalid latest.yml line {line_number}: {raw_line!r}")
                continue
            key, value = parsed
            if key == "files":
                current_section = "files"
                metadata["files"] = []
            else:
                metadata[key] = _parse_yaml_scalar(value)
            continue

        if current_section != "files":
            continue

        file_line = raw_line.lstrip(" ")
        if file_line.startswith("- "):
            current_file = {}
            metadata["files"].append(current_file)
            item_line = file_line[2:].strip()
            if item_line:
                parsed = _split_yaml_key_value(item_line)
                if parsed is None:
                    issues.append(f"Invalid latest.yml files entry on line {line_number}: {raw_line!r}")
                    continue
                key, value = parsed
                current_file[key] = _parse_yaml_scalar(value)
            continue

        if current_file is None:
            issues.append(f"Invalid latest.yml files entry on line {line_number}: {raw_line!r}")
            continue

        parsed = _split_yaml_key_value(file_line)
        if parsed is None:
            issues.append(f"Invalid latest.yml files entry on line {line_number}: {raw_line!r}")
            continue
        key, value = parsed
        current_file[key] = _parse_yaml_scalar(value)

    return metadata, issues


def _classify_executable(path: Path) -> tuple[str, str] | None:
    setup_match = SETUP_RE.fullmatch(path.name)
    if setup_match:
        return "setup", setup_match.group("version")
    portable_match = PORTABLE_RE.fullmatch(path.name)
    if portable_match:
        return "portable", portable_match.group("version")
    return None


def _make_check(key: str, label: str, issues: Sequence[str], details: dict[str, Any], success_message: str) -> CheckResult:
    if issues:
        return CheckResult(
            key=key,
            label=label,
            status="blocking",
            blocking=True,
            message="; ".join(issues),
            details=details,
        )
    return CheckResult(
        key=key,
        label=label,
        status="passed",
        blocking=False,
        message=success_message,
        details=details,
    )


def discover_release_executables(release_dir: Path, *, version: str | None = None) -> tuple[list[ReleaseExecutable], CheckResult]:
    issues: list[str] = []
    details: dict[str, Any] = {
        "release_dir": str(release_dir),
        "expected": [
            "wechat-ai-assistant-setup-<version>.exe",
            "wechat-ai-assistant-portable-<version>-x64.exe",
        ],
        "target_version": version,
        "all_executables": [],
        "ignored_versioned_executables": [],
        "unexpected_executables": [],
    }

    if not release_dir.is_dir():
        issues.append(f"Release directory does not exist: {release_dir}")
        return [], _make_check("release_executables", "Release executables", issues, details, "Release executables found.")

    all_executables = sorted(path for path in release_dir.glob("*.exe") if path.is_file())
    details["all_executables"] = [path.name for path in all_executables]
    if not all_executables:
        issues.append(f"No .exe artifacts found in {release_dir}")

    candidates: dict[str, list[tuple[Path, str]]] = {"setup": [], "portable": []}
    unexpected: list[str] = []
    for path in all_executables:
        classified = _classify_executable(path)
        if classified is None:
            unexpected.append(path.name)
            continue
        kind, artifact_version = classified
        if version is not None and artifact_version != version:
            details["ignored_versioned_executables"].append(path.name)
            continue
        candidates[kind].append((path, artifact_version))

    details["unexpected_executables"] = unexpected
    if unexpected:
        issues.append(f"Unexpected release executable names: {', '.join(unexpected)}")

    selected: list[ReleaseExecutable] = []
    for kind in ("setup", "portable"):
        matches = candidates[kind]
        if not matches:
            suffix = f" for version {version}" if version else ""
            issues.append(f"Missing {kind} executable{suffix}")
            continue
        if len(matches) > 1:
            issues.append(f"Expected one {kind} executable, found: {', '.join(path.name for path, _ in matches)}")
            continue
        path, artifact_version = matches[0]
        selected.append(
            ReleaseExecutable(
                kind=kind,
                name=path.name,
                path=path,
                version=artifact_version,
                sha256=compute_sha256(path),
                size=path.stat().st_size,
            )
        )

    selected_versions = sorted({artifact.version for artifact in selected})
    details["selected"] = [
        {
            "kind": artifact.kind,
            "name": artifact.name,
            "version": artifact.version,
            "size": artifact.size,
            "sha256": artifact.sha256,
        }
        for artifact in selected
    ]
    details["selected_versions"] = selected_versions
    if len(selected) == 2 and len(selected_versions) != 1:
        issues.append(f"Setup and portable versions do not match: {', '.join(selected_versions)}")

    return selected, _make_check(
        "release_executables",
        "Release executables",
        issues,
        details,
        "Setup and portable executables match the expected Windows release names.",
    )


def check_sha256sums(
    release_dir: Path,
    executables: Sequence[ReleaseExecutable],
    *,
    version: str | None = None,
) -> CheckResult:
    checksums_path = release_dir / CHECKSUM_FILE_NAME
    checksums, issues = parse_sha256sums(checksums_path)
    if version:
        release_exe_names = sorted(artifact.name for artifact in executables)
        checksum_scope = f"target version {version}"
    else:
        release_exe_names = sorted(path.name for path in release_dir.glob("*.exe") if path.is_file()) if release_dir.is_dir() else []
        checksum_scope = "all release executables"
    details: dict[str, Any] = {
        "path": str(checksums_path),
        "scope": checksum_scope,
        "release_executables": release_exe_names,
        "covered_executables": sorted(name for name in release_exe_names if name in checksums),
        "extra_entries": sorted(name for name in checksums if name not in release_exe_names),
    }

    for name in release_exe_names:
        if name not in checksums:
            issues.append(f"Missing checksum entry for {name}")

    for artifact in executables:
        expected = checksums.get(artifact.name)
        if expected is None:
            continue
        if expected != artifact.sha256:
            issues.append(f"Checksum mismatch for {artifact.name}: {CHECKSUM_FILE_NAME} has {expected}, file has {artifact.sha256}")

    return _make_check(
        "sha256sums",
        "SHA256SUMS coverage",
        issues,
        details,
        "SHA256SUMS.txt exists and covers all release executables.",
    )


def check_release_update_metadata(
    release_dir: Path,
    executables: Sequence[ReleaseExecutable],
    *,
    version: str | None = None,
) -> CheckResult:
    issues: list[str] = []
    latest_yml_path = release_dir / UPDATE_METADATA_FILE_NAME
    setup_artifact = next((artifact for artifact in executables if artifact.kind == "setup"), None)
    target_version = version or (setup_artifact.version if setup_artifact else None)
    expected_setup_name = f"wechat-ai-assistant-setup-{target_version}.exe" if target_version else None
    expected_blockmap_name = f"{expected_setup_name}.blockmap" if expected_setup_name else None
    expected_blockmap_path = release_dir / expected_blockmap_name if expected_blockmap_name else None

    metadata, parse_issues = parse_latest_yml(latest_yml_path)
    issues.extend(parse_issues)
    metadata_files = metadata.get("files")
    if not isinstance(metadata_files, list):
        metadata_files = []

    details: dict[str, Any] = {
        "path": str(latest_yml_path),
        "target_version": target_version,
        "expected_setup": expected_setup_name,
        "expected_blockmap": expected_blockmap_name,
        "metadata_version": metadata.get("version"),
        "metadata_path": metadata.get("path"),
        "metadata_files": metadata_files,
        "blockmap_exists": bool(expected_blockmap_path and expected_blockmap_path.is_file()),
    }

    if expected_setup_name is None:
        issues.append("No setup executable available for release update metadata validation.")
    else:
        metadata_version = str(metadata.get("version") or "").strip()
        if target_version and metadata_version != target_version:
            issues.append(f"latest.yml version must be {target_version}, found {metadata_version or '<missing>'}")

        metadata_path = str(metadata.get("path") or "").strip()
        if metadata_path != expected_setup_name:
            issues.append(f"latest.yml path must be {expected_setup_name}, found {metadata_path or '<missing>'}")

        matching_file = None
        for item in metadata_files:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("url") or item.get("path") or "").strip()
            if file_name == expected_setup_name:
                matching_file = item
                break
        if matching_file is None:
            issues.append(f"latest.yml files must include {expected_setup_name}")
        elif not str(matching_file.get("sha512") or "").strip():
            issues.append(f"latest.yml files entry for {expected_setup_name} must include sha512")

        if expected_blockmap_path is None or not expected_blockmap_path.is_file():
            issues.append(f"Missing setup blockmap: {expected_blockmap_name}")

    return _make_check(
        "release_update_metadata",
        "Electron updater metadata",
        issues,
        details,
        "latest.yml points at the setup installer and the setup blockmap is present.",
    )


def check_authenticode_signature(path: Path, *, runner: Runner = subprocess.run, system: str | None = None) -> SignatureResult:
    current_system = system or platform.system()
    if current_system != "Windows":
        return SignatureResult(
            status="blocking",
            blocking=True,
            authenticode_status="not_checked",
            message="Authenticode signature can only be verified on Windows with Get-AuthenticodeSignature.",
            details={"artifact": path.name, "system": current_system},
        )

    script = """
& {
param([Parameter(Mandatory=$true)][string]$target)
$ErrorActionPreference = 'Stop'
$sig = Get-AuthenticodeSignature -LiteralPath $target
[pscustomobject]@{
  Status = $sig.Status.ToString()
  StatusMessage = [string]$sig.StatusMessage
  SignerCertificateSubject = if ($sig.SignerCertificate) { [string]$sig.SignerCertificate.Subject } else { '' }
  SignerCertificateThumbprint = if ($sig.SignerCertificate) { [string]$sig.SignerCertificate.Thumbprint } else { '' }
} | ConvertTo-Json -Compress
}
""".strip()
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
        str(path),
    ]
    try:
        completed = runner(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SignatureResult(
            status="blocking",
            blocking=True,
            authenticode_status="check_failed",
            message=f"Authenticode signature check failed for {path.name}: {exc}",
            details={"artifact": path.name},
        )

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip() or "PowerShell signature check failed."
        return SignatureResult(
            status="blocking",
            blocking=True,
            authenticode_status="check_failed",
            message=f"Authenticode signature check failed for {path.name}: {message}",
            details={"artifact": path.name},
        )

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        return SignatureResult(
            status="blocking",
            blocking=True,
            authenticode_status="parse_failed",
            message=f"Cannot parse Authenticode signature output for {path.name}: {exc}",
            details={"artifact": path.name, "stdout": completed.stdout},
        )

    authenticode_status = str(payload.get("Status") or "").strip()
    details = {
        "artifact": path.name,
        "authenticode_status": authenticode_status,
        "status_message": str(payload.get("StatusMessage") or ""),
        "signer_subject": str(payload.get("SignerCertificateSubject") or ""),
        "signer_thumbprint": str(payload.get("SignerCertificateThumbprint") or ""),
    }
    if authenticode_status == "Valid":
        return SignatureResult(
            status="passed",
            blocking=False,
            authenticode_status=authenticode_status,
            message=f"Authenticode signature is valid for {path.name}.",
            details=details,
        )
    return SignatureResult(
        status="blocking",
        blocking=True,
        authenticode_status=authenticode_status or "unknown",
        message=f"Authenticode signature is not valid for {path.name}: {authenticode_status or 'unknown'}",
        details=details,
    )


def check_signatures(
    executables: Sequence[ReleaseExecutable],
    signature_checker: SignatureChecker | None = None,
    *,
    allow_unsigned_community: bool = False,
) -> CheckResult:
    checker = signature_checker or (lambda path: check_authenticode_signature(path))
    issues: list[str] = []
    results: list[dict[str, Any]] = []

    if not executables:
        issues.append("No release executables available for Authenticode verification.")

    for artifact in executables:
        result = checker(artifact.path)
        results.append(
            {
                "artifact": artifact.name,
                "status": result.status,
                "blocking": result.blocking,
                "authenticode_status": result.authenticode_status,
                "message": result.message,
                "details": result.details,
            }
        )
        if result.blocking:
            issues.append(result.message)

    details = {
        "results": results,
        "allow_unsigned_community": allow_unsigned_community,
    }
    if issues and allow_unsigned_community and executables:
        return CheckResult(
            "authenticode_signatures",
            "Authenticode signatures",
            "warning",
            False,
            "Unsigned community release allowed without valid Authenticode signatures: " + "; ".join(issues),
            details,
        )

    return _make_check(
        "authenticode_signatures",
        "Authenticode signatures",
        issues,
        details,
        "Authenticode signatures are valid for all release executables.",
    )


def check_electron_security_baseline(repo_root: Path = REPO_ROOT) -> CheckResult:
    issues: list[str] = []
    file_results: list[dict[str, Any]] = []

    for spec in ELECTRON_SECURITY_BASELINE:
        relative_file = str(spec["file"])
        path = repo_root / relative_file
        missing_markers: list[str] = []
        if not path.is_file():
            issues.append(f"Missing security baseline file: {relative_file}")
            file_results.append(
                {
                    "file": relative_file,
                    "label": spec["label"],
                    "status": "missing_file",
                    "missing_markers": list(spec["markers"]),
                }
            )
            continue

        content = path.read_text(encoding="utf-8")
        for marker in spec["markers"]:
            if marker not in content:
                missing_markers.append(marker)
        if missing_markers:
            issues.append(f"{relative_file} missing markers: {', '.join(missing_markers)}")

        file_results.append(
            {
                "file": relative_file,
                "label": spec["label"],
                "status": "passed" if not missing_markers else "missing_markers",
                "missing_markers": missing_markers,
            }
        )

    return _make_check(
        "electron_security_baseline",
        "Electron security and IPC baseline",
        issues,
        {"repo_root": str(repo_root), "files": file_results},
        "Electron BrowserWindow, preload, IPC allowlist, and diagnostics redaction baseline markers are present.",
    )


def build_installation_upgrade_drill(version: str | None, setup_name: str | None) -> list[dict[str, str]]:
    new_setup = setup_name or "wechat-ai-assistant-setup-<new-version>.exe"
    target_version = version or "<new-version>"
    return [
        {
            "id": "collect_old_setup",
            "blocking": "manual",
            "description": "Prepare the previous released setup.exe from GitHub Releases, for example wechat-ai-assistant-setup-<old-version>.exe.",
            "evidence": "Old installer path and version recorded in the release checklist.",
        },
        {
            "id": "collect_new_setup",
            "blocking": "manual",
            "description": f"Use the newly built setup installer {new_setup} for version {target_version}.",
            "evidence": "New installer path recorded and covered by SHA256SUMS.txt.",
        },
        {
            "id": "install_old_version",
            "blocking": "manual",
            "description": "Install the previous version on a clean Windows 10/11 VM with the supported WeChat 3.9.12.51 environment.",
            "evidence": "Old version launches and shows baseline status before upgrade.",
        },
        {
            "id": "seed_user_config",
            "blocking": "manual",
            "description": "Create or edit userData/data/app_config.json with a harmless marker value before upgrade.",
            "evidence": "Pre-upgrade app_config.json path, timestamp, and marker value recorded.",
        },
        {
            "id": "run_upgrade",
            "blocking": "manual",
            "description": f"Run {new_setup} over the existing installation and allow the installer to restart the app.",
            "evidence": "Installer exit result and upgraded app version recorded.",
        },
        {
            "id": "verify_config_retention",
            "blocking": "manual",
            "description": "Verify userData/data/app_config.json still exists and the marker value is retained after upgrade.",
            "evidence": "Post-upgrade app_config.json path, timestamp, and marker value recorded.",
        },
        {
            "id": "verify_runtime_readiness",
            "blocking": "manual",
            "description": "Start the upgraded app and verify GET /api/ping or GET /api/readiness returns a healthy response for the intended environment.",
            "evidence": "HTTP status, response body summary, and logs recorded.",
        },
        {
            "id": "rollback_note",
            "blocking": "manual",
            "description": "Record rollback steps or snapshot restore evidence if any upgrade step fails.",
            "evidence": "Rollback path and retained diagnostic notes recorded.",
        },
    ]


def build_report(
    *,
    release_dir: Path,
    version: str | None = None,
    signature_checker: SignatureChecker | None = None,
    repo_root: Path = REPO_ROOT,
    allow_unsigned_community: bool = False,
) -> dict[str, Any]:
    executables, executables_check = discover_release_executables(release_dir, version=version)
    checksum_check = check_sha256sums(release_dir, executables, version=version)
    update_metadata_check = check_release_update_metadata(release_dir, executables, version=version)
    signature_check = check_signatures(
        executables,
        signature_checker=signature_checker,
        allow_unsigned_community=allow_unsigned_community,
    )
    electron_security_check = check_electron_security_baseline(repo_root)
    checks = [executables_check, checksum_check, update_metadata_check, signature_check, electron_security_check]
    blocking_checks = [check for check in checks if check.blocking]
    release_channel = COMMUNITY_UNSIGNED_CHANNEL if allow_unsigned_community else OFFICIAL_SIGNED_CHANNEL
    warnings = [check.message for check in checks if check.status == "warning"]
    setup_name = next((artifact.name for artifact in executables if artifact.kind == "setup"), None)
    selected_version = version or next((artifact.version for artifact in executables if artifact.kind == "setup"), None)

    return {
        "success": True,
        "ready": not blocking_checks,
        "status": "passed" if not blocking_checks else "blocking",
        "blocking_count": len(blocking_checks),
        "release_channel": release_channel,
        "unsigned_community_release": allow_unsigned_community,
        "warnings": warnings,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "release_dir": str(release_dir),
        "target_version": version,
        "artifacts": [
            {
                "kind": artifact.kind,
                "name": artifact.name,
                "path": str(artifact.path),
                "version": artifact.version,
                "size": artifact.size,
                "sha256": artifact.sha256,
            }
            for artifact in executables
        ],
        "checks": [
            {
                "key": check.key,
                "label": check.label,
                "status": check.status,
                "blocking": check.blocking,
                "message": check.message,
                "details": check.details,
            }
            for check in checks
        ],
        "installation_upgrade_drill": build_installation_upgrade_drill(selected_version, setup_name),
    }


def render_text_report(report: dict[str, Any]) -> str:
    lines = [
        f"Windows release readiness: {report['status']}",
        f"Release channel: {report.get('release_channel', OFFICIAL_SIGNED_CHANNEL)}",
        f"Release directory: {report['release_dir']}",
        f"Blocking checks: {report['blocking_count']}",
        "",
        "Checks:",
    ]
    for check in report["checks"]:
        marker = "WARNING" if check["status"] == "warning" else ("BLOCKING" if check["blocking"] else "PASS")
        lines.append(f"- [{marker}] {check['label']}: {check['message']}")
    if report.get("warnings"):
        lines.extend(["", "Warnings:"])
        for warning in report["warnings"]:
            lines.append(f"- {warning}")
    lines.extend(["", "Installation upgrade drill:"])
    for index, step in enumerate(report["installation_upgrade_drill"], start=1):
        lines.append(f"{index}. {step['description']}")
        lines.append(f"   Evidence: {step['evidence']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Windows release artifacts before publishing.")
    parser.add_argument("--release-dir", default="release", help="Directory containing setup, portable, and SHA256SUMS.txt")
    parser.add_argument("--version", help="Expected release version, for example 1.6.3")
    parser.add_argument(
        "--allow-unsigned-community",
        action="store_true",
        help="Allow a clearly labeled unsigned community release while keeping the default official release gate signed-only.",
    )
    parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON report")
    args = parser.parse_args(argv)

    report = build_report(
        release_dir=Path(args.release_dir).resolve(),
        version=str(args.version).strip() if args.version else None,
        allow_unsigned_community=bool(args.allow_unsigned_community),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text_report(report))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
