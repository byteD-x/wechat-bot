from __future__ import annotations

from pathlib import Path

from scripts.audit_release_artifacts import main, scan_path


def test_audit_blocks_update_metadata_by_default(tmp_path: Path):
    (tmp_path / "latest.yml").write_text("version: 1.6.3", encoding="utf-8")
    (tmp_path / "wechat-ai-assistant-setup-1.6.3.exe.blockmap").write_text("blockmap", encoding="utf-8")

    issues = scan_path(tmp_path)

    assert any("latest.yml" in issue for issue in issues)
    assert any("wechat-ai-assistant-setup-1.6.3.exe.blockmap" in issue for issue in issues)


def test_audit_allows_top_level_release_update_metadata_when_enabled(tmp_path: Path):
    (tmp_path / "latest.yml").write_text("version: 1.6.3", encoding="utf-8")
    (tmp_path / "wechat-ai-assistant-setup-1.6.3.exe.blockmap").write_text("blockmap", encoding="utf-8")

    assert scan_path(tmp_path, allow_release_update_metadata=True) == []


def test_audit_still_blocks_nested_or_unexpected_update_metadata(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "latest.yml").write_text("version: 1.6.3", encoding="utf-8")
    (tmp_path / "unexpected.blockmap").write_text("blockmap", encoding="utf-8")

    issues = scan_path(tmp_path, allow_release_update_metadata=True)

    assert any("nested/latest.yml" in issue for issue in issues)
    assert any("unexpected.blockmap" in issue for issue in issues)


def test_cli_allows_release_update_metadata_with_explicit_flag(tmp_path: Path):
    (tmp_path / "latest.yml").write_text("version: 1.6.3", encoding="utf-8")
    (tmp_path / "wechat-ai-assistant-setup-1.6.3.exe.blockmap").write_text("blockmap", encoding="utf-8")

    assert main(["--allow-release-update-metadata", str(tmp_path)]) == 0
