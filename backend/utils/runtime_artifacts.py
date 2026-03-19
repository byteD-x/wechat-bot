"""Helpers for keeping runtime-generated artifacts under data/runtime."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.shared_config import ensure_data_root, get_project_root

PROJECT_ROOT = get_project_root()
RUNTIME_ROOT = ensure_data_root() / "runtime"
WCFERRY_DIR = RUNTIME_ROOT / "wcferry"
CHROMA_DIR = RUNTIME_ROOT / "chroma"
LOCK_DIR = RUNTIME_ROOT / "locks"
TEST_DIR = RUNTIME_ROOT / "test"
COVERAGE_DIR = TEST_DIR / "coverage"
PYTEST_CACHE_DIR = TEST_DIR / "pytest_cache"


def ensure_runtime_directories() -> None:
    for path in (
        RUNTIME_ROOT,
        WCFERRY_DIR,
        CHROMA_DIR,
        LOCK_DIR,
        TEST_DIR,
        COVERAGE_DIR,
        PYTEST_CACHE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def runtime_path(*parts: str) -> str:
    ensure_runtime_directories()
    path = RUNTIME_ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@contextmanager
def chdir_temporarily(path: str | Path) -> Iterator[None]:
    ensure_runtime_directories()
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    previous = Path.cwd()
    os.chdir(target)
    try:
        yield
    finally:
        os.chdir(previous)


def relocate_known_root_artifacts() -> None:
    ensure_runtime_directories()
    targets = {
        "injector.log": WCFERRY_DIR / "injector.log",
        ".ctx.lock": LOCK_DIR / ".ctx.lock",
        ".coverage": COVERAGE_DIR / ".coverage",
    }
    for name, destination in targets.items():
        source = PROJECT_ROOT / name
        if not source.exists() or source.resolve() == destination.resolve():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            source.replace(destination)
        except OSError:
            # Some third-party libraries keep the file handle open while the
            # process is alive. In that case, leave the file in place and let
            # startup/shutdown try again later.
            continue


def configure_runtime_environment() -> None:
    ensure_runtime_directories()
    os.environ.setdefault("COVERAGE_FILE", str(COVERAGE_DIR / ".coverage"))
