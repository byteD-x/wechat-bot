from pathlib import Path

import pytest

from backend.core.data_controls import DataControlService


def test_data_controls_build_plan_and_clear(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True)
    (data_root / "chat_memory.db").write_text("memory", encoding="utf-8")
    (data_root / "chat_memory.db-wal").write_text("memory-wal", encoding="utf-8")
    (data_root / "chat_memory.db-shm").write_text("memory-shm", encoding="utf-8")
    (data_root / "usage_history.db").write_text("usage", encoding="utf-8")
    (data_root / "chat_exports").mkdir(parents=True)
    (data_root / "chat_exports" / "a.txt").write_text("export", encoding="utf-8")

    service = DataControlService(data_root=data_root)
    preview = service.clear(["memory", "usage", "export_rag"], apply=False)
    assert preview["success"] is True
    assert preview["dry_run"] is True
    memory_paths = {
        item["relative_path"]
        for item in preview["targets"]
        if item.get("scope") == "memory"
    }
    assert "chat_memory.db" in memory_paths
    assert "chat_memory.db-wal" in memory_paths
    assert "chat_memory.db-shm" in memory_paths
    assert preview["existing_target_count"] >= 5
    assert preview["reclaimable_bytes"] > 0

    apply_result = service.clear(["memory", "usage", "export_rag"], apply=True)
    assert apply_result["success"] is True
    assert apply_result["dry_run"] is False
    assert apply_result["deleted_count"] >= 5
    assert apply_result["reclaimed_bytes"] > 0
    assert not (data_root / "chat_memory.db").exists()
    assert not (data_root / "chat_memory.db-wal").exists()
    assert not (data_root / "chat_memory.db-shm").exists()
    assert not (data_root / "usage_history.db").exists()
    assert not (data_root / "chat_exports").exists()


def test_data_controls_rejects_unknown_scope(tmp_path: Path):
    service = DataControlService(data_root=tmp_path / "data")
    try:
        service.build_clear_plan(["unknown_scope"])
        raised = False
    except ValueError:
        raised = True
    assert raised is True


def test_data_controls_apply_requires_explicit_scopes(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True)
    service = DataControlService(data_root=data_root)

    with pytest.raises(ValueError, match="scopes is required"):
        service.clear(None, apply=True)

    with pytest.raises(ValueError, match="scopes cannot be empty"):
        service.clear([], apply=True)


def test_data_controls_respects_configured_runtime_paths(tmp_path: Path):
    project_root = tmp_path / "project"
    data_root = project_root / "data"
    data_root.mkdir(parents=True)
    custom_memory = data_root / "memory" / "custom_memory.db"
    custom_memory.parent.mkdir(parents=True)
    custom_memory.write_text("memory", encoding="utf-8")
    custom_export_dir = data_root / "exports" / "chat_records"
    custom_export_dir.mkdir(parents=True)
    (custom_export_dir / "room.txt").write_text("export", encoding="utf-8")
    (data_root / "export_rag_manifest.json").write_text("{}", encoding="utf-8")

    service = DataControlService(
        data_root=data_root,
        bot_config={
            "memory_db_path": "data/memory/custom_memory.db",
            "export_rag_dir": "data/exports/chat_records",
        },
    )
    plan = service.build_clear_plan(["memory", "export_rag"])
    targets = {item["scope"]: [] for item in plan["targets"]}
    for item in plan["targets"]:
        targets[item["scope"]].append(item["relative_path"])

    assert "memory/custom_memory.db" in targets["memory"]
    assert "memory/custom_memory.db-wal" in targets["memory"]
    assert "memory/custom_memory.db-shm" in targets["memory"]
    assert "exports/chat_records" in targets["export_rag"]


def test_data_controls_flags_targets_outside_data_root(tmp_path: Path):
    project_root = tmp_path / "project"
    data_root = project_root / "data"
    data_root.mkdir(parents=True)
    external_memory = tmp_path / "external-memory.db"
    external_memory.write_text("memory", encoding="utf-8")

    service = DataControlService(
        data_root=data_root,
        bot_config={
            "memory_db_path": str(external_memory),
        },
    )
    plan = service.build_clear_plan(["memory"])

    assert plan["success"] is True
    unsupported_paths = {
        str(item.get("path") or "").strip()
        for item in plan["unsupported_targets"]
        if item.get("scope") == "memory"
    }
    expected_paths = {
        str(external_memory.resolve()),
        str((external_memory.parent / f"{external_memory.name}-wal").resolve()),
        str((external_memory.parent / f"{external_memory.name}-shm").resolve()),
    }
    assert expected_paths.issubset(unsupported_paths)
    assert plan["unsupported_target_count"] >= 3

    with pytest.raises(ValueError, match="outside data root"):
        service.clear(["memory"], apply=True)
