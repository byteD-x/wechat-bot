"""Optional file-system watcher for configuration hot reload."""

from __future__ import annotations

import logging
import os
import time
from typing import Iterable, Optional, Set

logger = logging.getLogger(__name__)


class ConfigReloadWatcher:
    """Watch config files and debounce reload notifications."""

    def __init__(
        self,
        paths: Iterable[str],
        *,
        debounce_ms: int = 500,
        preferred_mode: str = "auto",
    ) -> None:
        self._watch_paths: Set[str] = set()
        self._watch_file_paths: Set[str] = set()
        self._watch_target_dirs: Set[str] = set()
        self._watch_dirs: Set[str] = set()
        self._debounce_sec = max(0.0, int(debounce_ms) / 1000.0)
        self._preferred_mode = str(preferred_mode or "auto").strip().lower() or "auto"
        self._observer = None
        self._dirty = False
        self._last_event_ts = 0.0
        self._mode = "polling"
        self._set_paths(paths)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def debounce_ms(self) -> int:
        return int(round(self._debounce_sec * 1000))

    def _set_paths(self, paths: Iterable[str]) -> None:
        normalized_paths = {
            os.path.abspath(str(path))
            for path in (paths or [])
            if str(path or "").strip()
        }
        self._watch_paths = normalized_paths
        self._watch_file_paths = {
            path for path in normalized_paths
            if not os.path.isdir(path)
        }
        self._watch_target_dirs = {
            path for path in normalized_paths
            if os.path.isdir(path)
        }
        watch_dirs: Set[str] = set(self._watch_target_dirs)
        watch_dirs.update(
            os.path.dirname(path) or os.getcwd()
            for path in self._watch_file_paths
            if os.path.isdir(os.path.dirname(path) or os.getcwd())
        )
        self._watch_dirs = watch_dirs

    def start(self) -> None:
        self.stop()
        preferred = self._preferred_mode
        if preferred in {"auto", "watchdog"}:
            try:
                from watchdog.events import FileSystemEventHandler
                from watchdog.observers import Observer
            except Exception:
                if preferred == "watchdog":
                    logger.warning(
                        "watchdog unavailable, config reload watcher falls back to polling"
                    )
            else:
                watcher = self

                class _EventHandler(FileSystemEventHandler):
                    def on_any_event(self, event):  # type: ignore[override]
                        if getattr(event, "is_directory", False):
                            return
                        watcher.notify_path_changed(getattr(event, "src_path", ""))
                        watcher.notify_path_changed(getattr(event, "dest_path", ""))

                observer = Observer()
                handler = _EventHandler()
                for watch_dir in sorted(self._watch_dirs):
                    observer.schedule(handler, watch_dir, recursive=False)
                observer.daemon = True
                observer.start()
                self._observer = observer
                self._mode = "watchdog"
                return

        self._mode = "polling"

    def update(
        self,
        *,
        paths: Optional[Iterable[str]] = None,
        debounce_ms: Optional[int] = None,
        preferred_mode: Optional[str] = None,
    ) -> None:
        should_restart = False
        if paths is not None:
            normalized = {
                os.path.abspath(str(path))
                for path in paths
                if str(path or "").strip()
            }
            if normalized != self._watch_paths:
                self._set_paths(paths)
                should_restart = True
        if debounce_ms is not None:
            new_debounce = max(0.0, int(debounce_ms) / 1000.0)
            if new_debounce != self._debounce_sec:
                self._debounce_sec = new_debounce
        if preferred_mode is not None:
            normalized_mode = str(preferred_mode or "auto").strip().lower() or "auto"
            if normalized_mode != self._preferred_mode:
                self._preferred_mode = normalized_mode
                should_restart = True
        if should_restart:
            self.start()

    def stop(self) -> None:
        observer = self._observer
        self._observer = None
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=1.0)
            except Exception:
                pass
        self._mode = "polling"

    def notify_path_changed(self, path: str) -> bool:
        normalized = os.path.abspath(str(path or ""))
        matched = normalized in self._watch_file_paths
        if not matched:
            for watch_dir in self._watch_target_dirs:
                if normalized == watch_dir or normalized.startswith(f"{watch_dir}{os.sep}"):
                    matched = True
                    break
        if not matched:
            return False
        self._dirty = True
        self._last_event_ts = time.monotonic()
        return True

    def consume_change(self, now: Optional[float] = None) -> bool:
        if not self._dirty:
            return False
        current = time.monotonic() if now is None else float(now)
        if current - self._last_event_ts < self._debounce_sec:
            return False
        self._dirty = False
        return True

    def get_status(self) -> dict:
        return {
            "mode": self._mode,
            "preferred_mode": self._preferred_mode,
            "debounce_ms": self.debounce_ms,
            "watch_paths": sorted(self._watch_paths),
            "watch_file_paths": sorted(self._watch_file_paths),
            "watch_target_dirs": sorted(self._watch_target_dirs),
        }
