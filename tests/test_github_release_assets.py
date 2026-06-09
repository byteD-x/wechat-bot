from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sync_github_release_assets import (
    COMMUNITY_UNSIGNED_CHANNEL,
    LocalAsset,
    OFFICIAL_SIGNED_CHANNEL,
    ReleaseSyncError,
    RemoteAsset,
    SyncPlan,
    build_release_notes_text,
    decorate_release_title,
    discover_local_assets,
    normalize_remote_digest,
    normalize_release_channel,
    parse_sha256sums,
    plan_asset_sync,
    render_report,
    remote_asset_matches,
)


def _write_asset(path: Path, content: bytes) -> str:
    path.write_bytes(content)
    import hashlib

    return hashlib.sha256(content).hexdigest()


def _local_asset(kind: str, name: str, size: int, sha256: str) -> LocalAsset:
    return LocalAsset(
        kind=kind,
        name=name,
        path=Path("release") / name,
        size=size,
        sha256=sha256,
    )


def _write_release_dir(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    portable_hash = _write_asset(
        release_dir / "wechat-ai-assistant-portable-1.6.3-x64.exe",
        b"portable",
    )
    setup_hash = _write_asset(release_dir / "wechat-ai-assistant-setup-1.6.3.exe", b"setup")
    update_info_hash = _write_asset(
        release_dir / "latest.yml",
        b"path: wechat-ai-assistant-setup-1.6.3.exe\n",
    )
    blockmap_hash = _write_asset(
        release_dir / "wechat-ai-assistant-setup-1.6.3.exe.blockmap",
        b"blockmap",
    )
    (release_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            [
                f"{portable_hash}  wechat-ai-assistant-portable-1.6.3-x64.exe",
                f"{setup_hash}  wechat-ai-assistant-setup-1.6.3.exe",
            ]
        ),
        encoding="utf-8",
    )
    return release_dir, {
        "portable": portable_hash,
        "setup": setup_hash,
        "update-info": update_info_hash,
        "setup-blockmap": blockmap_hash,
    }


def test_parse_sha256sums_rejects_invalid_lines(tmp_path: Path):
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text("not-a-checksum file.exe\n", encoding="utf-8")

    with pytest.raises(ReleaseSyncError, match="Invalid SHA256"):
        parse_sha256sums(sums)


def test_discover_local_assets_requires_checksums_for_executables(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    (release_dir / "SHA256SUMS.txt").write_text("", encoding="utf-8")

    with pytest.raises(ReleaseSyncError, match="Missing checksum entry"):
        discover_local_assets(release_dir)


def test_discover_local_assets_finds_expected_release_files(tmp_path: Path):
    release_dir, hashes = _write_release_dir(tmp_path)

    assets = discover_local_assets(release_dir)

    assert [asset.kind for asset in assets] == [
        "portable",
        "setup",
        "checksums",
        "update-info",
        "setup-blockmap",
    ]
    assert assets[0].name == "wechat-ai-assistant-portable-1.6.3-x64.exe"
    assert assets[0].sha256 == hashes["portable"]
    assert assets[1].name == "wechat-ai-assistant-setup-1.6.3.exe"
    assert assets[1].sha256 == hashes["setup"]
    assert assets[3].name == "latest.yml"
    assert assets[3].sha256 == hashes["update-info"]
    assert assets[4].name == "wechat-ai-assistant-setup-1.6.3.exe.blockmap"
    assert assets[4].sha256 == hashes["setup-blockmap"]


def test_release_channel_helpers_keep_official_title_and_notes(tmp_path: Path):
    notes = tmp_path / "notes.md"
    notes.write_text("# v1.6.3 更新内容\n\n## Features\n\n- Stable release", encoding="utf-8")

    assert normalize_release_channel(None) == OFFICIAL_SIGNED_CHANNEL
    assert normalize_release_channel("official-signed") == OFFICIAL_SIGNED_CHANNEL
    assert decorate_release_title("v1.6.3", OFFICIAL_SIGNED_CHANNEL) == "v1.6.3"
    assert build_release_notes_text(notes, OFFICIAL_SIGNED_CHANNEL) == notes.read_text(encoding="utf-8")


def test_release_channel_helpers_mark_unsigned_community_notes(tmp_path: Path):
    notes = tmp_path / "notes.md"
    notes.write_text("# v1.6.3 更新内容\n\n## Features\n\n- Community release", encoding="utf-8")

    title = decorate_release_title("v1.6.3", COMMUNITY_UNSIGNED_CHANNEL)
    notes_text = build_release_notes_text(notes, COMMUNITY_UNSIGNED_CHANNEL)

    assert title == "[Unsigned Community] v1.6.3"
    assert notes_text is not None
    assert "unsigned community release" in notes_text
    assert "Windows SmartScreen" in notes_text
    assert "# v1.6.3 更新内容" in notes_text


def test_render_report_includes_unsigned_community_channel_marker():
    local = _local_asset("setup", "wechat-ai-assistant-setup-1.6.3.exe", 5, "c" * 64)
    plan = SyncPlan(assets_to_delete=(), assets_to_upload=(local,), assets_to_keep=(), unexpected_assets=())

    report = render_report(
        tag="v1.6.3",
        repo="byteD-x/wechat-bot",
        release=None,
        local_assets=[local],
        plan=plan,
        dry_run=True,
        release_channel=COMMUNITY_UNSIGNED_CHANNEL,
        title="[Unsigned Community] v1.6.3",
    )

    assert report["release_channel"] == COMMUNITY_UNSIGNED_CHANNEL
    assert report["unsigned_community_release"] is True
    assert report["title"] == "[Unsigned Community] v1.6.3"


def test_release_workflow_keeps_unsigned_community_as_explicit_opt_in():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert 'default: "official_signed"' in workflow
    assert "- community_unsigned" in workflow
    assert '$channel = "official_signed"' in workflow
    assert "if: env.RELEASE_CHANNEL == 'official_signed'" in workflow
    assert '$env:RELEASE_CHANNEL -eq "community_unsigned"' in workflow
    assert "--allow-unsigned-community" in workflow
    assert '--release-channel "$env:RELEASE_CHANNEL"' in workflow


def test_discover_local_assets_uses_tag_version_when_history_exists(tmp_path: Path):
    release_dir, _ = _write_release_dir(tmp_path)
    _write_asset(release_dir / "wechat-ai-assistant-portable-1.6.2-x64.exe", b"old portable")
    _write_asset(release_dir / "wechat-ai-assistant-setup-1.6.2.exe", b"old setup")
    _write_asset(release_dir / "wechat-ai-assistant-setup-1.6.2.exe.blockmap", b"old blockmap")

    assets = discover_local_assets(release_dir, version="1.6.3")

    assert [asset.name for asset in assets] == [
        "wechat-ai-assistant-portable-1.6.3-x64.exe",
        "wechat-ai-assistant-setup-1.6.3.exe",
        "SHA256SUMS.txt",
        "latest.yml",
        "wechat-ai-assistant-setup-1.6.3.exe.blockmap",
    ]


def test_remote_asset_matches_requires_uploaded_size_and_digest():
    local = LocalAsset(
        kind="setup",
        name="wechat-ai-assistant-setup-1.6.3.exe",
        path=Path("release/wechat-ai-assistant-setup-1.6.3.exe"),
        size=5,
        sha256="a" * 64,
    )

    assert normalize_remote_digest(f"sha256:{'A' * 64}") == "a" * 64
    assert remote_asset_matches(
        local,
        RemoteAsset(id=1, name=local.name, state="uploaded", size=5, digest=f"sha256:{'a' * 64}"),
    )
    assert not remote_asset_matches(
        local,
        RemoteAsset(id=2, name=local.name, state="starter", size=5, digest=None),
    )
    assert not remote_asset_matches(
        local,
        RemoteAsset(id=3, name=local.name, state="uploaded", size=4, digest=f"sha256:{'a' * 64}"),
    )
    assert not remote_asset_matches(
        local,
        RemoteAsset(id=4, name=local.name, state="uploaded", size=5, digest=None),
    )


def test_plan_asset_sync_deletes_bad_managed_assets_and_uploads_missing():
    portable = _local_asset("portable", "wechat-ai-assistant-portable-1.6.3-x64.exe", 8, "b" * 64)
    setup = _local_asset("setup", "wechat-ai-assistant-setup-1.6.3.exe", 5, "c" * 64)
    checksum = _local_asset("checksums", "SHA256SUMS.txt", 120, "d" * 64)
    update_info = _local_asset("update-info", "latest.yml", 42, "e" * 64)
    blockmap = _local_asset(
        "setup-blockmap",
        "wechat-ai-assistant-setup-1.6.3.exe.blockmap",
        16,
        "f" * 64,
    )

    plan = plan_asset_sync(
        [portable, setup, checksum, update_info, blockmap],
        [
            RemoteAsset(id=10, name=portable.name, state="starter", size=8, digest=None),
            RemoteAsset(
                id=11,
                name=checksum.name,
                state="uploaded",
                size=120,
                digest=f"sha256:{'d' * 64}",
            ),
            RemoteAsset(
                id=12,
                name=update_info.name,
                state="uploaded",
                size=42,
                digest=f"sha256:{'e' * 64}",
            ),
            RemoteAsset(
                id=13,
                name="wechat-ai-assistant-setup-1.6.2.exe.blockmap",
                state="uploaded",
                size=15,
                digest=f"sha256:{'a' * 64}",
            ),
        ],
    )

    assert [asset.id for asset in plan.assets_to_delete] == [10]
    assert [asset.name for asset in plan.assets_to_upload] == [portable.name, setup.name, blockmap.name]
    assert [asset.name for asset in plan.assets_to_keep] == [checksum.name, update_info.name]
    assert [asset.name for asset in plan.unexpected_assets] == [
        "wechat-ai-assistant-setup-1.6.2.exe.blockmap"
    ]
    assert not plan.is_complete


def test_plan_asset_sync_blocks_unexpected_assets_even_when_expected_assets_match():
    portable = _local_asset("portable", "wechat-ai-assistant-portable-1.6.3-x64.exe", 8, "b" * 64)
    setup = _local_asset("setup", "wechat-ai-assistant-setup-1.6.3.exe", 5, "c" * 64)
    checksum = _local_asset("checksums", "SHA256SUMS.txt", 120, "d" * 64)
    update_info = _local_asset("update-info", "latest.yml", 42, "e" * 64)
    blockmap = _local_asset(
        "setup-blockmap",
        "wechat-ai-assistant-setup-1.6.3.exe.blockmap",
        16,
        "f" * 64,
    )

    plan = plan_asset_sync(
        [portable, setup, checksum, update_info, blockmap],
        [
            RemoteAsset(
                id=10,
                name=portable.name,
                state="uploaded",
                size=8,
                digest=f"sha256:{'b' * 64}",
            ),
            RemoteAsset(
                id=11,
                name=setup.name,
                state="uploaded",
                size=5,
                digest=f"sha256:{'c' * 64}",
            ),
            RemoteAsset(
                id=12,
                name=checksum.name,
                state="uploaded",
                size=120,
                digest=f"sha256:{'d' * 64}",
            ),
            RemoteAsset(
                id=13,
                name=update_info.name,
                state="uploaded",
                size=42,
                digest=f"sha256:{'e' * 64}",
            ),
            RemoteAsset(
                id=14,
                name=blockmap.name,
                state="uploaded",
                size=16,
                digest=f"sha256:{'f' * 64}",
            ),
            RemoteAsset(
                id=15,
                name="wechat-ai-assistant-setup-1.6.2.exe.blockmap",
                state="uploaded",
                size=15,
                digest=f"sha256:{'a' * 64}",
            ),
        ],
    )

    assert not plan.assets_to_delete
    assert not plan.assets_to_upload
    assert [asset.name for asset in plan.assets_to_keep] == [
        portable.name,
        setup.name,
        checksum.name,
        update_info.name,
        blockmap.name,
    ]
    assert [asset.name for asset in plan.unexpected_assets] == [
        "wechat-ai-assistant-setup-1.6.2.exe.blockmap"
    ]
    assert not plan.is_complete
