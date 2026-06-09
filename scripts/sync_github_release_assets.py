from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_REPO = "byteD-x/wechat-bot"
OFFICIAL_SIGNED_CHANNEL = "official_signed"
COMMUNITY_UNSIGNED_CHANNEL = "community_unsigned"
UNSIGNED_COMMUNITY_TITLE_PREFIX = "[Unsigned Community]"
UNSIGNED_COMMUNITY_NOTICE = "\n".join(
    [
        "> [!WARNING]",
        "> This is an unsigned community release. The Windows executables do not carry a trusted Authenticode signature,",
        "> so Windows SmartScreen may show an unknown-publisher warning. Verify downloaded files with SHA256SUMS.txt.",
        "",
    ]
)


class ReleaseSyncError(RuntimeError):
    pass


def validate_release_tag(tag: str) -> str:
    from scripts.validate_release_metadata import validate_tag

    return validate_tag(tag)


def expected_asset_globs(version: str | None) -> tuple[tuple[str, str], ...]:
    if version:
        return (
            ("portable", f"wechat-ai-assistant-portable-{version}-*.exe"),
            ("setup", f"wechat-ai-assistant-setup-{version}.exe"),
            ("checksums", "SHA256SUMS.txt"),
            ("update-info", "latest.yml"),
            ("setup-blockmap", f"wechat-ai-assistant-setup-{version}.exe.blockmap"),
        )
    return (
        ("portable", "wechat-ai-assistant-portable-*.exe"),
        ("setup", "wechat-ai-assistant-setup-*.exe"),
        ("checksums", "SHA256SUMS.txt"),
        ("update-info", "latest.yml"),
        ("setup-blockmap", "wechat-ai-assistant-setup-*.exe.blockmap"),
    )


def normalize_release_channel(value: str | None) -> str:
    channel = str(value or OFFICIAL_SIGNED_CHANNEL).strip().lower().replace("-", "_")
    if channel not in {OFFICIAL_SIGNED_CHANNEL, COMMUNITY_UNSIGNED_CHANNEL}:
        raise ReleaseSyncError(f"Unsupported release channel: {value}")
    return channel


def decorate_release_title(title: str, release_channel: str) -> str:
    normalized_channel = normalize_release_channel(release_channel)
    clean_title = str(title or "").strip()
    if normalized_channel != COMMUNITY_UNSIGNED_CHANNEL:
        return clean_title
    if UNSIGNED_COMMUNITY_TITLE_PREFIX.lower() in clean_title.lower():
        return clean_title
    return f"{UNSIGNED_COMMUNITY_TITLE_PREFIX} {clean_title}".strip()


def build_release_notes_text(notes_file: Path | None, release_channel: str) -> str | None:
    normalized_channel = normalize_release_channel(release_channel)
    original_notes = notes_file.read_text(encoding="utf-8").strip() if notes_file else ""
    if normalized_channel != COMMUNITY_UNSIGNED_CHANNEL:
        return original_notes or None
    if UNSIGNED_COMMUNITY_NOTICE.strip() in original_notes:
        return original_notes
    return f"{UNSIGNED_COMMUNITY_NOTICE}{original_notes}".strip()


def prepare_release_notes_file(
    notes_file: Path | None,
    release_channel: str,
    *,
    stack: ExitStack,
) -> Path | None:
    notes_text = build_release_notes_text(notes_file, release_channel)
    if notes_text is None:
        return None
    if normalize_release_channel(release_channel) != COMMUNITY_UNSIGNED_CHANNEL:
        return notes_file
    temp_dir = Path(stack.enter_context(tempfile.TemporaryDirectory()))
    prepared_notes = temp_dir / "release-notes.md"
    prepared_notes.write_text(notes_text, encoding="utf-8")
    return prepared_notes


@dataclass(frozen=True)
class LocalAsset:
    kind: str
    name: str
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class RemoteAsset:
    id: int
    name: str
    state: str
    size: int
    digest: str | None = None


@dataclass(frozen=True)
class ReleaseState:
    id: int
    tag: str
    is_draft: bool
    assets: tuple[RemoteAsset, ...]
    url: str = ""


@dataclass(frozen=True)
class SyncPlan:
    assets_to_delete: tuple[RemoteAsset, ...]
    assets_to_upload: tuple[LocalAsset, ...]
    assets_to_keep: tuple[RemoteAsset, ...]
    unexpected_assets: tuple[RemoteAsset, ...]

    @property
    def is_complete(self) -> bool:
        return not self.assets_to_delete and not self.assets_to_upload and not self.unexpected_assets


Runner = Callable[..., subprocess.CompletedProcess[str]]


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256sums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ReleaseSyncError(f"Invalid checksum line {line_number}: {raw_line!r}")
        checksum, filename = parts
        filename = filename.strip().lstrip("*")
        if len(checksum) != 64 or any(char not in "0123456789abcdefABCDEF" for char in checksum):
            raise ReleaseSyncError(f"Invalid SHA256 value on line {line_number}: {checksum}")
        if filename in checksums:
            raise ReleaseSyncError(f"Duplicate checksum entry: {filename}")
        checksums[filename] = checksum.lower()
    return checksums


def _find_single_asset(release_dir: Path, kind: str, pattern: str) -> Path:
    matches = sorted(path for path in release_dir.glob(pattern) if path.is_file())
    if not matches:
        raise ReleaseSyncError(f"Missing {kind} asset matching {pattern} in {release_dir}")
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise ReleaseSyncError(f"Expected one {kind} asset matching {pattern}, found: {names}")
    return matches[0]


def discover_local_assets(release_dir: Path, *, version: str | None = None) -> tuple[LocalAsset, ...]:
    if not release_dir.is_dir():
        raise ReleaseSyncError(f"Release directory does not exist: {release_dir}")

    assets: list[LocalAsset] = []
    selected_paths: dict[str, Path] = {}
    for kind, pattern in expected_asset_globs(version):
        selected_paths[kind] = _find_single_asset(release_dir, kind, pattern)

    checksums = parse_sha256sums(selected_paths["checksums"])
    for kind, path in selected_paths.items():
        sha256 = compute_sha256(path)
        if path.suffix.lower() == ".exe":
            expected = checksums.get(path.name)
            if expected is None:
                raise ReleaseSyncError(f"Missing checksum entry for {path.name}")
            if expected != sha256:
                raise ReleaseSyncError(f"Checksum mismatch for {path.name}: SHA256SUMS.txt has {expected}, file has {sha256}")
        stat = path.stat()
        assets.append(LocalAsset(kind=kind, name=path.name, path=path, size=stat.st_size, sha256=sha256))

    return tuple(assets)


def normalize_remote_digest(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    if lowered.startswith("sha256:"):
        return lowered.removeprefix("sha256:")
    return lowered


def remote_asset_matches(local: LocalAsset, remote: RemoteAsset) -> bool:
    return (
        remote.state == "uploaded"
        and remote.size == local.size
        and normalize_remote_digest(remote.digest) == local.sha256
    )


def _is_transient_gh_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            " eof",
            ": eof",
            "502 bad gateway",
            "503 service unavailable",
            "504 gateway timeout",
            "connection reset",
            "connection timed out",
        )
    )


def plan_asset_sync(local_assets: Sequence[LocalAsset], remote_assets: Sequence[RemoteAsset]) -> SyncPlan:
    expected_by_name = {asset.name: asset for asset in local_assets}
    remote_by_name: dict[str, list[RemoteAsset]] = {}
    for asset in remote_assets:
        remote_by_name.setdefault(asset.name, []).append(asset)

    to_delete: list[RemoteAsset] = []
    to_upload: list[LocalAsset] = []
    to_keep: list[RemoteAsset] = []
    unexpected: list[RemoteAsset] = []

    for local in local_assets:
        candidates = remote_by_name.get(local.name, [])
        matching = [asset for asset in candidates if remote_asset_matches(local, asset)]
        if len(matching) == 1 and len(candidates) == 1:
            to_keep.append(matching[0])
            continue
        to_delete.extend(candidates)
        to_upload.append(local)

    for asset in remote_assets:
        if asset.name not in expected_by_name:
            unexpected.append(asset)

    return SyncPlan(
        assets_to_delete=tuple(to_delete),
        assets_to_upload=tuple(to_upload),
        assets_to_keep=tuple(to_keep),
        unexpected_assets=tuple(unexpected),
    )


class GhClient:
    def __init__(
        self,
        *,
        repo: str,
        runner: Runner = subprocess.run,
        timeout: int = 900,
    ) -> None:
        self.repo = repo
        self.runner = runner
        self.timeout = timeout

    def _run(self, args: Sequence[str], *, capture_json: bool = False, retries: int = 0) -> Any:
        command = ["gh", *args]
        attempts = retries + 1
        for attempt in range(1, attempts + 1):
            completed = self.runner(
                command,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
            )
            if completed.returncode == 0:
                if capture_json:
                    return json.loads(completed.stdout or "null")
                return completed.stdout
            message = (completed.stderr or completed.stdout or "").strip()
            if attempt < attempts and _is_transient_gh_error(message):
                continue
            raise ReleaseSyncError(f"Command failed: {' '.join(command)}\n{message}")
        raise ReleaseSyncError(f"Command failed: {' '.join(command)}")

    def view_release(self, tag: str) -> ReleaseState | None:
        args = [
            "release",
            "view",
            tag,
            "--repo",
            self.repo,
            "--json",
            "databaseId,tagName,url,isDraft,assets",
        ]
        try:
            payload = self._run(args, capture_json=True, retries=2)
        except ReleaseSyncError as exc:
            if "not found" in str(exc).lower() or "could not find release" in str(exc).lower():
                return None
            raise

        release_id = int(payload["databaseId"])
        assets = tuple(self.list_assets(release_id))
        return ReleaseState(
            id=release_id,
            tag=str(payload["tagName"]),
            is_draft=bool(payload["isDraft"]),
            url=str(payload.get("url") or ""),
            assets=assets,
        )

    def list_assets(self, release_id: int) -> tuple[RemoteAsset, ...]:
        endpoint = f"repos/{self.repo}/releases/{release_id}/assets"
        payload = self._run(["api", endpoint, "--paginate"], capture_json=True, retries=2)
        return tuple(
            RemoteAsset(
                id=int(item["id"]),
                name=str(item["name"]),
                state=str(item.get("state") or ""),
                size=int(item.get("size") or 0),
                digest=item.get("digest"),
            )
            for item in payload
        )

    def create_draft(self, *, tag: str, title: str, notes_file: Path | None) -> None:
        args = ["release", "create", tag, "--repo", self.repo, "--verify-tag", "--draft", "--title", title]
        if notes_file:
            args.extend(["--notes-file", str(notes_file)])
        self._run(args)

    def edit_release(self, *, tag: str, title: str, notes_file: Path | None, keep_draft: bool) -> None:
        args = ["release", "edit", tag, "--repo", self.repo, "--title", title]
        if notes_file:
            args.extend(["--notes-file", str(notes_file)])
        if keep_draft:
            args.append("--draft")
        self._run(args)

    def delete_asset(self, asset: RemoteAsset) -> None:
        self._run(["api", "--method", "DELETE", f"repos/{self.repo}/releases/assets/{asset.id}", "--silent"])

    def upload_asset(self, *, tag: str, asset: LocalAsset) -> None:
        self._run(["release", "upload", tag, str(asset.path), "--repo", self.repo])

    def publish_release(self, *, tag: str, title: str, notes_file: Path | None) -> None:
        args = ["release", "edit", tag, "--repo", self.repo, "--draft=false", "--title", title]
        if notes_file:
            args.extend(["--notes-file", str(notes_file)])
        self._run(args)


def _asset_payload(asset: LocalAsset | RemoteAsset) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": asset.name, "size": asset.size}
    if isinstance(asset, LocalAsset):
        payload["sha256"] = asset.sha256
        try:
            payload["path"] = str(asset.path.relative_to(PROJECT_ROOT))
        except ValueError:
            payload["path"] = asset.name
        payload["kind"] = asset.kind
    else:
        payload["id"] = asset.id
        payload["state"] = asset.state
        payload["digest"] = asset.digest
    return payload


def render_report(
    *,
    tag: str,
    repo: str,
    release: ReleaseState | None,
    local_assets: Sequence[LocalAsset],
    plan: SyncPlan,
    dry_run: bool,
    release_channel: str,
    title: str,
) -> dict[str, Any]:
    return {
        "tag": tag,
        "repo": repo,
        "mode": "dry-run" if dry_run else "apply",
        "release_channel": release_channel,
        "title": title,
        "unsigned_community_release": release_channel == COMMUNITY_UNSIGNED_CHANNEL,
        "release": None
        if release is None
        else {
            "id": release.id,
            "tag": release.tag,
            "is_draft": release.is_draft,
            "url": release.url,
        },
        "local_assets": [_asset_payload(asset) for asset in local_assets],
        "keep": [_asset_payload(asset) for asset in plan.assets_to_keep],
        "delete": [_asset_payload(asset) for asset in plan.assets_to_delete],
        "upload": [_asset_payload(asset) for asset in plan.assets_to_upload],
        "unexpected": [_asset_payload(asset) for asset in plan.unexpected_assets],
        "complete": plan.is_complete,
    }


def sync_release_assets(
    *,
    tag: str,
    repo: str,
    release_dir: Path,
    notes_file: Path | None,
    title: str,
    apply: bool,
    publish: bool,
    timeout: int,
    release_channel: str = OFFICIAL_SIGNED_CHANNEL,
) -> dict[str, Any]:
    version = validate_release_tag(tag)
    if notes_file is not None and not notes_file.is_file():
        raise ReleaseSyncError(f"Release notes file does not exist: {notes_file}")
    normalized_channel = normalize_release_channel(release_channel)
    release_title = decorate_release_title(title, normalized_channel)

    local_assets = discover_local_assets(release_dir, version=version)
    client = GhClient(repo=repo, timeout=timeout)
    release = client.view_release(tag)

    with ExitStack() as stack:
        prepared_notes_file = prepare_release_notes_file(notes_file, normalized_channel, stack=stack)
        if release is None:
            empty_plan = SyncPlan(assets_to_delete=(), assets_to_upload=local_assets, assets_to_keep=(), unexpected_assets=())
            if not apply:
                return render_report(
                    tag=tag,
                    repo=repo,
                    release=None,
                    local_assets=local_assets,
                    plan=empty_plan,
                    dry_run=True,
                    release_channel=normalized_channel,
                    title=release_title,
                )
            client.create_draft(tag=tag, title=release_title, notes_file=prepared_notes_file)
            release = client.view_release(tag)
            if release is None:
                raise ReleaseSyncError(f"Release was created but cannot be loaded: {tag}")
        elif apply:
            if not release.is_draft and not plan_asset_sync(local_assets, release.assets).is_complete:
                raise ReleaseSyncError("Refusing to modify an already published release with incomplete assets.")
            client.edit_release(tag=tag, title=release_title, notes_file=prepared_notes_file, keep_draft=release.is_draft)
            release = client.view_release(tag)
            if release is None:
                raise ReleaseSyncError(f"Release disappeared while editing: {tag}")

        plan = plan_asset_sync(local_assets, release.assets)
        if apply and plan.unexpected_assets:
            names = ", ".join(asset.name for asset in plan.unexpected_assets)
            raise ReleaseSyncError(f"Refusing to publish with unexpected release assets: {names}")
        if not apply:
            return render_report(
                tag=tag,
                repo=repo,
                release=release,
                local_assets=local_assets,
                plan=plan,
                dry_run=True,
                release_channel=normalized_channel,
                title=release_title,
            )

        for asset in plan.assets_to_delete:
            client.delete_asset(asset)

        for asset in plan.assets_to_upload:
            client.upload_asset(tag=tag, asset=asset)
            refreshed = client.view_release(tag)
            if refreshed is None:
                raise ReleaseSyncError(f"Release disappeared after uploading {asset.name}: {tag}")
            upload_plan = plan_asset_sync(local_assets, refreshed.assets)
            if any(item.name == asset.name for item in upload_plan.assets_to_upload):
                raise ReleaseSyncError(f"Uploaded asset did not pass state/size/digest verification: {asset.name}")

        release = client.view_release(tag)
        if release is None:
            raise ReleaseSyncError(f"Release disappeared before final verification: {tag}")
        final_plan = plan_asset_sync(local_assets, release.assets)
        if not final_plan.is_complete:
            raise ReleaseSyncError("Release assets are still incomplete after sync; keeping release as draft.")

        if publish and release.is_draft:
            client.publish_release(tag=tag, title=release_title, notes_file=prepared_notes_file)
            release = client.view_release(tag)

        return render_report(
            tag=tag,
            repo=repo,
            release=release,
            local_assets=local_assets,
            plan=final_plan,
            dry_run=False,
            release_channel=normalized_channel,
            title=release_title,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely sync local Windows release assets to a GitHub draft release.")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. v1.6.3")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repository, default: {DEFAULT_REPO}")
    parser.add_argument("--release-dir", default="release", help="Directory containing release assets")
    parser.add_argument("--notes-file", help="Release notes file to apply to the draft")
    parser.add_argument("--title", help="Release title, default: tag")
    parser.add_argument(
        "--release-channel",
        choices=[OFFICIAL_SIGNED_CHANNEL, COMMUNITY_UNSIGNED_CHANNEL],
        default=OFFICIAL_SIGNED_CHANNEL,
        help="Release channel marker. community_unsigned clearly labels the release as unsigned.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply delete/upload/edit actions. Default is dry-run.")
    parser.add_argument("--publish", action="store_true", help="Publish the draft after all assets are verified.")
    parser.add_argument("--timeout", type=int, default=900, help="Per-gh-command timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON report")
    args = parser.parse_args(argv)

    tag = str(args.tag).strip()
    title = str(args.title or tag).strip()
    notes_file = Path(args.notes_file).resolve() if args.notes_file else None
    try:
        report = sync_release_assets(
            tag=tag,
            repo=str(args.repo).strip(),
            release_dir=Path(args.release_dir).resolve(),
            notes_file=notes_file,
            title=title,
            apply=bool(args.apply),
            publish=bool(args.publish),
            timeout=int(args.timeout),
            release_channel=str(args.release_channel),
        )
    except ReleaseSyncError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not args.apply:
            print("Dry-run only. Re-run with --apply to modify the GitHub Release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
