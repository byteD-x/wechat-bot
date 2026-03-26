import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.workspace_backup import WorkspaceBackupService


def _write_backup_fixture(
    backup_root: Path,
    *,
    backup_id: str,
    mode: str,
    created_at: int,
    payload_name: str = "app_config.json",
) -> None:
    destination = backup_root / backup_id
    destination.mkdir(parents=True, exist_ok=True)
    (destination / payload_name).write_text(f"{backup_id}-payload", encoding="utf-8")
    (destination / "backup_manifest.json").write_text(
        json.dumps(
            {
                "backup_id": backup_id,
                "app_version": "9.9.9",
                "schema_version": 1,
                "mode": mode,
                "created_at": created_at,
                "included_files": [payload_name],
                "checksum_summary": {},
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def test_workspace_backup_service_creates_manifest_and_restores_files(tmp_path: Path):
    project_root = tmp_path / "project"
    data_root = project_root / "data"
    data_root.mkdir(parents=True)
    app_config_path = project_root / "app_config.json"
    config_override_path = data_root / "config_override.json"
    api_keys_path = data_root / "api_keys.py"
    prompt_overrides_path = project_root / "prompt_overrides.py"

    (project_root / "package.json").write_text(
        json.dumps({"version": "9.9.9"}, ensure_ascii=False),
        encoding="utf-8",
    )
    app_config_path.write_text(json.dumps({"bot": {"enabled": True}}), encoding="utf-8")
    config_override_path.write_text(json.dumps({"bot": {"alias": "v1"}}), encoding="utf-8")
    api_keys_path.write_text("API_KEYS = {'default': 'sk-v1'}\n", encoding="utf-8")
    prompt_overrides_path.write_text("PROMPT_OVERRIDES = {'Alice': 'v1'}\n", encoding="utf-8")
    (data_root / "chat_memory.db").write_text("memory-v1", encoding="utf-8")
    (data_root / "reply_quality_history.db").write_text("quality-v1", encoding="utf-8")
    (data_root / "chat_exports").mkdir()
    (data_root / "chat_exports" / "room-a.txt").write_text("export-v1", encoding="utf-8")

    with (
        patch("backend.core.workspace_backup.get_app_config_path", return_value=str(app_config_path)),
        patch("backend.core.workspace_backup.get_project_root", return_value=project_root),
    ):
        service = WorkspaceBackupService(data_root=data_root)
        quick = service.create_backup("quick", label="nightly")
        full = service.create_backup("full")

        quick_manifest = json.loads((Path(quick["path"]) / "backup_manifest.json").read_text(encoding="utf-8"))
        full_manifest = json.loads((Path(full["path"]) / "backup_manifest.json").read_text(encoding="utf-8"))

        assert quick_manifest["mode"] == "quick"
        assert "app_config.json" in quick_manifest["included_files"]
        assert "data/config_override.json" in quick_manifest["included_files"]
        assert "data/api_keys.py" in quick_manifest["included_files"]
        assert "prompt_overrides.py" in quick_manifest["included_files"]
        assert full_manifest["mode"] == "full"
        assert "chat_exports/room-a.txt" in full_manifest["included_files"]

        app_config_path.write_text(json.dumps({"bot": {"enabled": False}}), encoding="utf-8")
        config_override_path.write_text(json.dumps({"bot": {"alias": "v2"}}), encoding="utf-8")
        api_keys_path.write_text("API_KEYS = {'default': 'sk-v2'}\n", encoding="utf-8")
        prompt_overrides_path.write_text("PROMPT_OVERRIDES = {'Alice': 'v2'}\n", encoding="utf-8")
        (data_root / "chat_memory.db").write_text("memory-v2", encoding="utf-8")

        plan = service.build_restore_plan(quick["id"])
        assert plan["valid"] is True

        restore_result = service.apply_restore(quick["id"])
        assert restore_result["success"] is True
        assert json.loads(app_config_path.read_text(encoding="utf-8"))["bot"]["enabled"] is True
        assert json.loads(config_override_path.read_text(encoding="utf-8"))["bot"]["alias"] == "v1"
        assert "sk-v1" in api_keys_path.read_text(encoding="utf-8")
        assert "v1" in prompt_overrides_path.read_text(encoding="utf-8")
        assert (data_root / "chat_memory.db").read_text(encoding="utf-8") == "memory-v1"

        listing = service.list_backups(limit=5)
        assert listing["success"] is True
        assert len(listing["backups"]) >= 2


def test_workspace_backup_service_rejects_restore_paths_outside_workspace(tmp_path: Path):
    project_root = tmp_path / "project"
    data_root = project_root / "data"
    data_root.mkdir(parents=True)
    backup_root = data_root / "backups" / "workspace"
    malicious_backup = backup_root / "external-backup"
    malicious_backup.mkdir(parents=True)

    (project_root / "package.json").write_text(
        json.dumps({"version": "9.9.9"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (malicious_backup / "backup_manifest.json").write_text(
        json.dumps(
            {
                "backup_id": "external-backup",
                "app_version": "9.9.9",
                "schema_version": 1,
                "mode": "quick",
                "created_at": 1,
                "included_files": ["../escape.txt"],
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    with patch("backend.core.workspace_backup.get_project_root", return_value=project_root):
        service = WorkspaceBackupService(data_root=data_root)
        plan = service.build_restore_plan("external-backup")

    assert plan["valid"] is False
    assert plan["invalid_files"] == ["../escape.txt"]

    with patch("backend.core.workspace_backup.get_project_root", return_value=project_root):
        with pytest.raises(ValueError, match="unsupported paths"):
            service.apply_restore("external-backup")


def test_workspace_backup_service_rejects_checksum_mismatch(tmp_path: Path):
    project_root = tmp_path / "project"
    data_root = project_root / "data"
    data_root.mkdir(parents=True)
    app_config_path = project_root / "app_config.json"

    (project_root / "package.json").write_text(
        json.dumps({"version": "9.9.9"}, ensure_ascii=False),
        encoding="utf-8",
    )
    app_config_path.write_text(json.dumps({"bot": {"enabled": True}}), encoding="utf-8")
    (data_root / "chat_memory.db").write_text("memory-v1", encoding="utf-8")

    with (
        patch("backend.core.workspace_backup.get_app_config_path", return_value=str(app_config_path)),
        patch("backend.core.workspace_backup.get_project_root", return_value=project_root),
    ):
        service = WorkspaceBackupService(data_root=data_root)
        backup = service.create_backup("quick")
        backup_root = Path(backup["path"])
        (backup_root / "chat_memory.db").write_text("tampered", encoding="utf-8")

        verification = service.verify_backup(backup["id"])
        plan = service.build_restore_plan(backup["id"])

        assert verification["valid"] is False
        assert plan["valid"] is False
        assert verification["checksum_mismatches"][0]["path"] == "chat_memory.db"

        with pytest.raises(ValueError, match="checksum verification failed"):
            service.apply_restore(backup["id"])


def test_workspace_backup_cleanup_plan_respects_retention_and_restore_anchor(tmp_path: Path):
    data_root = tmp_path / "data"
    backup_root = data_root / "backups" / "workspace"
    backup_root.mkdir(parents=True)

    _write_backup_fixture(backup_root, backup_id="quick-1", mode="quick", created_at=1)
    _write_backup_fixture(backup_root, backup_id="quick-2", mode="quick", created_at=2)
    _write_backup_fixture(backup_root, backup_id="quick-3", mode="quick", created_at=3)
    _write_backup_fixture(backup_root, backup_id="quick-4", mode="quick", created_at=4)
    _write_backup_fixture(backup_root, backup_id="full-1", mode="full", created_at=11)
    _write_backup_fixture(backup_root, backup_id="full-2", mode="full", created_at=12)
    (backup_root / "last_restore_result.json").write_text(
        json.dumps(
            {
                "success": True,
                "pre_restore_backup": {"id": "quick-1"},
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    service = WorkspaceBackupService(data_root=data_root)
    plan = service.build_cleanup_plan(keep_quick=1, keep_full=1)

    assert plan["candidate_count"] == 3
    assert plan["protected_backup_ids"] == ["quick-1"]
    assert [item["id"] for item in plan["delete_candidates"]] == ["full-1", "quick-3", "quick-2"]
    preserved = {item["id"]: item["cleanup_reason"] for item in plan["preserved_backups"]}
    assert preserved["quick-4"] == "keep_latest_quick"
    assert preserved["full-2"] == "keep_latest_full"
    assert preserved["quick-1"] == "protected_restore_anchor"


def test_workspace_backup_cleanup_apply_deletes_only_candidates(tmp_path: Path):
    data_root = tmp_path / "data"
    backup_root = data_root / "backups" / "workspace"
    backup_root.mkdir(parents=True)

    _write_backup_fixture(backup_root, backup_id="quick-1", mode="quick", created_at=1)
    _write_backup_fixture(backup_root, backup_id="quick-2", mode="quick", created_at=2)
    _write_backup_fixture(backup_root, backup_id="quick-3", mode="quick", created_at=3)

    service = WorkspaceBackupService(data_root=data_root)
    result = service.cleanup_backups(keep_quick=1, keep_full=0, protect_restore_anchor=False, apply=True, list_limit=10)

    assert result["dry_run"] is False
    assert result["deleted_count"] == 2
    assert [item["id"] for item in result["deleted_backups"]] == ["quick-2", "quick-1"]
    assert [item["id"] for item in result["backups"]] == ["quick-3"]
    assert not (backup_root / "quick-1").exists()
    assert not (backup_root / "quick-2").exists()
    assert (backup_root / "quick-3").exists()
