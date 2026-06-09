from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.check_windows_release_readiness import (
    SignatureResult,
    build_report,
    check_authenticode_signature,
    check_electron_security_baseline,
    main,
)


def _write_asset(path: Path, content: bytes) -> str:
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _write_update_metadata(
    release_dir: Path,
    *,
    version: str = "1.6.3",
    metadata_version: str | None = None,
    metadata_path: str | None = None,
    include_blockmap: bool = True,
):
    setup_name = f"wechat-ai-assistant-setup-{version}.exe"
    if include_blockmap:
        (release_dir / f"{setup_name}.blockmap").write_text("blockmap", encoding="utf-8")
    (release_dir / "latest.yml").write_text(
        "\n".join(
            [
                f"version: {metadata_version or version}",
                f"path: {metadata_path or setup_name}",
                "files:",
                f"  - url: {setup_name}",
                "    sha512: fake-sha512",
                "    size: 5",
                "releaseDate: '2026-06-09T00:00:00.000Z'",
            ]
        ),
        encoding="utf-8",
    )


def _write_release_dir(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    setup_hash = _write_asset(release_dir / "wechat-ai-assistant-setup-1.6.3.exe", b"setup")
    portable_hash = _write_asset(release_dir / "wechat-ai-assistant-portable-1.6.3-x64.exe", b"portable")
    (release_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            [
                f"{setup_hash}  wechat-ai-assistant-setup-1.6.3.exe",
                f"{portable_hash}  wechat-ai-assistant-portable-1.6.3-x64.exe",
            ]
        ),
        encoding="utf-8",
    )
    _write_update_metadata(release_dir)
    return release_dir, {"setup": setup_hash, "portable": portable_hash}


def _valid_signature(path: Path) -> SignatureResult:
    return SignatureResult(
        status="passed",
        blocking=False,
        authenticode_status="Valid",
        message=f"valid: {path.name}",
        details={"artifact": path.name},
    )


def _unsigned_signature(path: Path) -> SignatureResult:
    return SignatureResult(
        status="blocking",
        blocking=True,
        authenticode_status="NotSigned",
        message=f"unsigned: {path.name}",
        details={"artifact": path.name},
    )


def _checks_by_key(report: dict):
    return {check["key"]: check for check in report["checks"]}


def _write_electron_security_baseline(repo_root: Path, *, omit_marker: str | None = None):
    files = {
        "src/main/index.js": [
            "contextIsolation: true",
            "nodeIntegration: false",
            "sandbox: true",
            "webSecurity: true",
            "setWindowOpenHandler",
            "will-navigate",
            "will-redirect",
        ],
        "src/preload/index.js": [
            "contextBridge.exposeInMainWorld('electronAPI'",
            "ipcRenderer.invoke('backend:request'",
            "ipcRenderer.invoke('knowledge-base:select-file'",
            "ipcRenderer.invoke('export-diagnostics-snapshot'",
        ],
        "src/main/ipc.js": [
            "assertTrustedRendererSender",
            "handleTrusted",
            "ALLOWED_BACKEND_PATHS",
            "ALLOWED_BACKEND_PATH_PATTERNS",
            "endpoint_not_allowed",
            "payload_too_large",
            "payload_not_allowed_for_get",
            "knowledge-base:select-file",
            "source_file: `.../${name}`",
        ],
        "src/main/diagnostics-snapshot.js": [
            "[redacted: sensitive value]",
            "[redacted: chat content]",
            "[redacted: contact identifier]",
            "[redacted: local path]",
            "redacted_categories",
            "privacy_notice",
        ],
    }
    for relative_path, markers in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(marker for marker in markers if marker != omit_marker),
            encoding="utf-8",
        )


def test_release_readiness_passes_for_named_signed_artifacts(tmp_path: Path):
    release_dir, hashes = _write_release_dir(tmp_path)

    report = build_report(release_dir=release_dir, version="1.6.3", signature_checker=_valid_signature)
    checks = _checks_by_key(report)

    assert report["ready"] is True
    assert report["status"] == "passed"
    assert report["blocking_count"] == 0
    assert checks["release_executables"]["status"] == "passed"
    assert checks["sha256sums"]["status"] == "passed"
    assert checks["release_update_metadata"]["status"] == "passed"
    assert checks["authenticode_signatures"]["status"] == "passed"
    assert checks["electron_security_baseline"]["status"] == "passed"
    assert [artifact["kind"] for artifact in report["artifacts"]] == ["setup", "portable"]
    assert {artifact["sha256"] for artifact in report["artifacts"]} == set(hashes.values())
    assert any(step["id"] == "verify_config_retention" for step in report["installation_upgrade_drill"])
    assert any("/api/ping" in step["description"] or "/api/readiness" in step["description"] for step in report["installation_upgrade_drill"])


def test_release_readiness_version_filter_allows_legal_history(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    _write_asset(release_dir / "wechat-ai-assistant-setup-1.6.2.exe", b"old setup")
    _write_asset(release_dir / "wechat-ai-assistant-portable-1.6.2-x64.exe", b"old portable")

    report = build_report(release_dir=release_dir, version="1.6.3", signature_checker=_valid_signature)
    checks = _checks_by_key(report)

    assert report["ready"] is True
    assert checks["release_executables"]["status"] == "passed"
    assert checks["release_executables"]["details"]["ignored_versioned_executables"] == [
        "wechat-ai-assistant-portable-1.6.2-x64.exe",
        "wechat-ai-assistant-setup-1.6.2.exe",
    ]
    assert checks["sha256sums"]["details"]["scope"] == "target version 1.6.3"


def test_release_readiness_blocks_when_artifacts_are_missing(tmp_path: Path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()

    report = build_report(release_dir=release_dir, signature_checker=_valid_signature)
    checks = _checks_by_key(report)

    assert report["ready"] is False
    assert checks["release_executables"]["blocking"] is True
    assert "No .exe artifacts" in checks["release_executables"]["message"]
    assert checks["authenticode_signatures"]["blocking"] is True
    assert "No release executables" in checks["authenticode_signatures"]["message"]


def test_release_readiness_blocks_unexpected_exe_names(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    _write_asset(release_dir / "wechat-ai-assistant-installer-1.6.3-x64.exe", b"msi")

    report = build_report(release_dir=release_dir, version="1.6.3", signature_checker=_valid_signature)
    executable_check = _checks_by_key(report)["release_executables"]

    assert report["ready"] is False
    assert executable_check["blocking"] is True
    assert "Unexpected release executable names" in executable_check["message"]


def test_release_readiness_requires_sha256sums_file(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    (release_dir / "SHA256SUMS.txt").unlink()

    report = build_report(release_dir=release_dir, signature_checker=_valid_signature)
    checksum_check = _checks_by_key(report)["sha256sums"]

    assert report["ready"] is False
    assert checksum_check["blocking"] is True
    assert "Missing SHA256SUMS.txt" in checksum_check["message"]
    assert "Missing checksum entry" in checksum_check["message"]


def test_release_readiness_requires_latest_yml(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    (release_dir / "latest.yml").unlink()

    report = build_report(release_dir=release_dir, version="1.6.3", signature_checker=_valid_signature)
    metadata_check = _checks_by_key(report)["release_update_metadata"]

    assert report["ready"] is False
    assert metadata_check["blocking"] is True
    assert "Missing latest.yml" in metadata_check["message"]


def test_release_readiness_blocks_latest_yml_version_mismatch(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    _write_update_metadata(release_dir, version="1.6.3", metadata_version="1.6.2")

    report = build_report(release_dir=release_dir, version="1.6.3", signature_checker=_valid_signature)
    metadata_check = _checks_by_key(report)["release_update_metadata"]

    assert report["ready"] is False
    assert metadata_check["blocking"] is True
    assert "latest.yml version must be 1.6.3" in metadata_check["message"]


def test_release_readiness_requires_setup_blockmap(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    (release_dir / "wechat-ai-assistant-setup-1.6.3.exe.blockmap").unlink()

    report = build_report(release_dir=release_dir, version="1.6.3", signature_checker=_valid_signature)
    metadata_check = _checks_by_key(report)["release_update_metadata"]

    assert report["ready"] is False
    assert metadata_check["blocking"] is True
    assert "Missing setup blockmap" in metadata_check["message"]


def test_release_readiness_blocks_checksum_mismatch(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    (release_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            [
                f"{'0' * 64}  wechat-ai-assistant-setup-1.6.3.exe",
                f"{'1' * 64}  wechat-ai-assistant-portable-1.6.3-x64.exe",
            ]
        ),
        encoding="utf-8",
    )

    report = build_report(release_dir=release_dir, signature_checker=_valid_signature)
    checksum_check = _checks_by_key(report)["sha256sums"]

    assert report["ready"] is False
    assert checksum_check["blocking"] is True
    assert "Checksum mismatch" in checksum_check["message"]


def test_release_readiness_blocks_unsigned_authenticode(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)

    report = build_report(release_dir=release_dir, signature_checker=_unsigned_signature)
    signature_check = _checks_by_key(report)["authenticode_signatures"]

    assert report["ready"] is False
    assert signature_check["blocking"] is True
    assert "unsigned: wechat-ai-assistant-setup-1.6.3.exe" in signature_check["message"]
    assert "unsigned: wechat-ai-assistant-portable-1.6.3-x64.exe" in signature_check["message"]


def test_release_readiness_allows_unsigned_community_release_with_warning(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)

    report = build_report(
        release_dir=release_dir,
        signature_checker=_unsigned_signature,
        allow_unsigned_community=True,
    )
    signature_check = _checks_by_key(report)["authenticode_signatures"]

    assert report["ready"] is True
    assert report["status"] == "passed"
    assert report["blocking_count"] == 0
    assert report["release_channel"] == "community_unsigned"
    assert report["unsigned_community_release"] is True
    assert signature_check["status"] == "warning"
    assert signature_check["blocking"] is False
    assert signature_check["details"]["allow_unsigned_community"] is True
    assert "Unsigned community release allowed" in signature_check["message"]
    assert report["warnings"] == [signature_check["message"]]


def test_authenticode_check_is_blocking_outside_windows(tmp_path: Path):
    path = tmp_path / "wechat-ai-assistant-setup-1.6.3.exe"
    path.write_bytes(b"setup")

    result = check_authenticode_signature(path, system="Linux")

    assert result.blocking is True
    assert result.status == "blocking"
    assert result.authenticode_status == "not_checked"
    assert "Windows" in result.message


def test_authenticode_check_only_accepts_valid_status(tmp_path: Path):
    path = tmp_path / "wechat-ai-assistant-setup-1.6.3.exe"
    path.write_bytes(b"setup")

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"Status": "NotSigned", "StatusMessage": "not signed"}),
            stderr="",
        )

    result = check_authenticode_signature(path, runner=runner, system="Windows")

    assert result.blocking is True
    assert result.authenticode_status == "NotSigned"
    assert "not valid" in result.message


def test_authenticode_check_passes_target_path_to_powershell_runner(tmp_path: Path):
    path = tmp_path / "wechat-ai-assistant-setup-1.6.3.exe"
    path.write_bytes(b"setup")
    commands: list[list[str]] = []

    def runner(*args, **kwargs):
        command = args[0]
        commands.append(command)
        assert command[-1] == str(path)
        assert "param([Parameter(Mandatory=$true)][string]$target)" in command[-2]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps({"Status": "Valid", "StatusMessage": ""}),
            stderr="",
        )

    result = check_authenticode_signature(path, runner=runner, system="Windows")

    assert result.blocking is False
    assert result.status == "passed"
    assert result.authenticode_status == "Valid"
    assert len(commands) == 1


def test_electron_security_baseline_passes_when_markers_are_present(tmp_path: Path):
    _write_electron_security_baseline(tmp_path)

    result = check_electron_security_baseline(tmp_path)

    assert result.blocking is False
    assert result.status == "passed"
    assert all(file_result["status"] == "passed" for file_result in result.details["files"])


def test_electron_security_baseline_blocks_when_ipc_allowlist_marker_is_missing(tmp_path: Path):
    _write_electron_security_baseline(tmp_path, omit_marker="ALLOWED_BACKEND_PATHS")

    result = check_electron_security_baseline(tmp_path)

    assert result.blocking is True
    assert result.status == "blocking"
    assert "src/main/ipc.js missing markers" in result.message
    assert "ALLOWED_BACKEND_PATHS" in result.message


def test_cli_json_output_returns_blocking_exit_code(tmp_path: Path, capsys):
    release_dir = tmp_path / "release"
    release_dir.mkdir()

    result = main(["--release-dir", str(release_dir), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert payload["ready"] is False
    assert payload["status"] == "blocking"
    assert payload["blocking_count"] >= 1
    assert any(step["id"] == "collect_old_setup" for step in payload["installation_upgrade_drill"])


def test_cli_allows_unsigned_community_release_with_json_report(tmp_path: Path, capsys, monkeypatch):
    release_dir, _ = _write_release_dir(tmp_path)

    monkeypatch.setattr(
        "scripts.check_windows_release_readiness.check_authenticode_signature",
        _unsigned_signature,
    )
    result = main(["--release-dir", str(release_dir), "--allow-unsigned-community", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["ready"] is True
    assert payload["release_channel"] == "community_unsigned"
    assert payload["warnings"]
