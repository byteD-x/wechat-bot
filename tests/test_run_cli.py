import argparse
import json

import run


def test_build_parser_supports_check_json_and_backup_restore():
    parser = run.build_parser()

    check_args = parser.parse_args(["check", "--json", "--cached"])
    assert check_args.command == "check"
    assert check_args.json is True
    assert check_args.cached is True

    backup_args = parser.parse_args(
        ["backup", "restore", "--backup-id", "backup-1", "--apply", "--json"]
    )
    assert backup_args.command == "backup"
    assert backup_args.backup_command == "restore"
    assert backup_args.backup_id == "backup-1"
    assert backup_args.apply is True
    assert backup_args.json is True

    verify_args = parser.parse_args(["backup", "verify", "--backup-id", "backup-1", "--json"])
    assert verify_args.command == "backup"
    assert verify_args.backup_command == "verify"
    assert verify_args.backup_id == "backup-1"
    assert verify_args.json is True

    cleanup_args = parser.parse_args(
        ["backup", "cleanup", "--keep-quick", "4", "--keep-full", "2", "--apply", "--json"]
    )
    assert cleanup_args.command == "backup"
    assert cleanup_args.backup_command == "cleanup"
    assert cleanup_args.keep_quick == 4
    assert cleanup_args.keep_full == 2
    assert cleanup_args.apply is True
    assert cleanup_args.json is True


def test_cmd_check_forwards_json_and_cache_flags(monkeypatch):
    captured = {}

    def fake_run_check(*, json_output: bool, force_refresh: bool) -> int:
        captured["json_output"] = json_output
        captured["force_refresh"] = force_refresh
        return 7

    monkeypatch.setattr("scripts.check.run_check", fake_run_check)

    result = run.cmd_check(argparse.Namespace(json=True, cached=True))

    assert result == 7
    assert captured == {
        "json_output": True,
        "force_refresh": False,
    }


def test_cmd_backup_restore_dry_run_json(monkeypatch, capsys):
    class FakeBackupService:
        def build_restore_plan(self, backup_ref: str) -> dict:
            assert backup_ref == "backup-1"
            return {
                "backup": {"id": backup_ref},
                "included_files": ["app_config.json"],
                "missing_files": [],
                "invalid_files": [],
                "valid": True,
            }

    monkeypatch.setattr(run, "_build_backup_service", lambda: FakeBackupService())

    result = run.cmd_backup_restore(
        argparse.Namespace(backup_id="backup-1", apply=False, json=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["success"] is True
    assert payload["dry_run"] is True
    assert payload["backup"]["id"] == "backup-1"
    assert payload["included_files"] == ["app_config.json"]


def test_cmd_backup_verify_json_reports_checksum_mismatch(monkeypatch, capsys):
    class FakeBackupService:
        def verify_backup(self, backup_ref: str) -> dict:
            assert backup_ref == "backup-3"
            return {
                "backup": {"id": backup_ref},
                "included_files": ["chat_memory.db"],
                "missing_files": [],
                "invalid_files": [],
                "checksum_missing_files": [],
                "checksum_mismatches": [
                    {
                        "path": "chat_memory.db",
                        "expected": "abc",
                        "actual": "def",
                    }
                ],
                "valid": False,
            }

    monkeypatch.setattr(run, "_build_backup_service", lambda: FakeBackupService())

    result = run.cmd_backup_verify(
        argparse.Namespace(backup_id="backup-3", json=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["success"] is False
    assert payload["checksum_mismatches"][0]["path"] == "chat_memory.db"


def test_cmd_backup_verify_json_reports_missing_backup(monkeypatch, capsys):
    class FakeBackupService:
        def verify_backup(self, backup_ref: str) -> dict:
            raise FileNotFoundError(f"backup not found: {backup_ref}")

    monkeypatch.setattr(run, "_build_backup_service", lambda: FakeBackupService())

    result = run.cmd_backup_verify(
        argparse.Namespace(backup_id="missing-backup", json=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["success"] is False
    assert "backup not found" in payload["message"]


def test_cmd_backup_restore_apply_creates_pre_restore_snapshot(monkeypatch):
    events = []
    saved_payloads = []

    class FakeBackupService:
        def build_restore_plan(self, backup_ref: str) -> dict:
            events.append(("plan", backup_ref))
            return {
                "backup": {"id": backup_ref},
                "included_files": ["app_config.json"],
                "missing_files": [],
                "invalid_files": [],
                "valid": True,
            }

        def create_backup(self, mode: str, *, label: str = "") -> dict:
            events.append(("create_backup", mode, label))
            return {"id": "pre-restore-cli", "mode": mode}

        def apply_restore(self, backup_ref: str) -> dict:
            events.append(("apply_restore", backup_ref))
            return {"success": True, "restored_count": 1}

        def save_restore_result(self, payload: dict) -> None:
            saved_payloads.append(payload)

    monkeypatch.setattr(run, "_build_backup_service", lambda: FakeBackupService())

    result = run.cmd_backup_restore(
        argparse.Namespace(backup_id="backup-2", apply=True, json=False)
    )

    assert result == 0
    assert events == [
        ("plan", "backup-2"),
        ("create_backup", "quick", "pre-restore-cli"),
        ("apply_restore", "backup-2"),
    ]
    assert saved_payloads and saved_payloads[0]["success"] is True
    assert saved_payloads[0]["pre_restore_backup"]["id"] == "pre-restore-cli"


def test_cmd_backup_cleanup_dry_run_json(monkeypatch, capsys):
    class FakeBackupService:
        def cleanup_backups(self, *, keep_quick: int, keep_full: int, apply: bool) -> dict:
            assert keep_quick == 4
            assert keep_full == 2
            assert apply is False
            return {
                "success": True,
                "dry_run": True,
                "keep_policy": {"keep_quick": keep_quick, "keep_full": keep_full},
                "delete_candidates": [{"id": "quick-1", "mode": "quick"}],
                "preserved_backups": [],
                "candidate_count": 1,
                "deleted_count": 0,
                "reclaimable_bytes": 1024,
                "reclaimed_bytes": 0,
            }

    monkeypatch.setattr(run, "_build_backup_service", lambda: FakeBackupService())

    result = run.cmd_backup_cleanup(
        argparse.Namespace(keep_quick=4, keep_full=2, apply=False, json=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["success"] is True
    assert payload["dry_run"] is True
    assert payload["candidate_count"] == 1
    assert payload["delete_candidates"][0]["id"] == "quick-1"


def test_cmd_backup_cleanup_apply_json(monkeypatch, capsys):
    class FakeBackupService:
        def cleanup_backups(self, *, keep_quick: int, keep_full: int, apply: bool) -> dict:
            assert keep_quick == 5
            assert keep_full == 3
            assert apply is True
            return {
                "success": True,
                "dry_run": False,
                "keep_policy": {"keep_quick": keep_quick, "keep_full": keep_full},
                "delete_candidates": [{"id": "quick-2", "mode": "quick"}],
                "deleted_backups": [{"id": "quick-2", "mode": "quick"}],
                "preserved_backups": [],
                "candidate_count": 1,
                "deleted_count": 1,
                "reclaimable_bytes": 1024,
                "reclaimed_bytes": 1024,
            }

    monkeypatch.setattr(run, "_build_backup_service", lambda: FakeBackupService())

    result = run.cmd_backup_cleanup(
        argparse.Namespace(keep_quick=5, keep_full=3, apply=True, json=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["success"] is True
    assert payload["dry_run"] is False
    assert payload["deleted_count"] == 1
    assert payload["deleted_backups"][0]["id"] == "quick-2"
