#!/usr/bin/env python3
"""Run pytest target groups with progress logs and bounded failure output."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "runtime" / "test" / "pytest-groups"
TIMEOUT_RETURN_CODE = 124


@dataclass(frozen=True)
class PytestGroup:
    name: str
    targets: tuple[str, ...]


@dataclass(frozen=True)
class GroupResult:
    name: str
    command: tuple[str, ...]
    returncode: int
    elapsed_seconds: float
    stdout_path: Path
    stderr_path: Path
    stdout_bytes: int
    stderr_bytes: int
    timed_out: bool = False
    idle_timed_out: bool = False


def _parse_group_spec(value: str) -> PytestGroup:
    name, sep, targets_text = value.partition("=")
    name = name.strip()
    targets = tuple(item.strip() for item in targets_text.split(",") if item.strip())
    if not sep or not name or not targets:
        raise argparse.ArgumentTypeError("group must use NAME=target[,target...]")
    return PytestGroup(name=name, targets=targets)


def _build_command(
    group: PytestGroup,
    pytest_args: list[str],
    *,
    python_executable: str = sys.executable,
) -> list[str]:
    command = [python_executable, "-m", "pytest", *group.targets]
    command.extend(pytest_args or ["-q"])
    return command


def _log_sizes(stdout_path: Path, stderr_path: Path) -> tuple[int, int]:
    stdout_bytes = stdout_path.stat().st_size if stdout_path.exists() else 0
    stderr_bytes = stderr_path.stat().st_size if stderr_path.exists() else 0
    return stdout_bytes, stderr_bytes


def _format_seconds(value: float) -> str:
    return f"{max(0.0, value):.1f}s"


def _read_tail_lines(path: Path, line_count: int) -> list[str]:
    if line_count <= 0 or not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-line_count:]


def _print_log_tail(
    label: str,
    path: Path,
    *,
    line_count: int,
    output: TextIO = sys.stdout,
) -> None:
    lines = _read_tail_lines(path, line_count)
    if not lines:
        return
    print(f"[pytest-groups] {label} tail ({min(line_count, len(lines))} lines):", file=output)
    for line in lines:
        print(line, file=output)


def _terminate_process_tree(process: subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    process.terminate()


def run_group(
    group: PytestGroup,
    *,
    logs_dir: Path = DEFAULT_LOG_DIR,
    pytest_args: list[str] | None = None,
    python_executable: str = sys.executable,
    cwd: Path = PROJECT_ROOT,
    timeout_seconds: float = 0.0,
    heartbeat_seconds: float = 30.0,
    idle_timeout_seconds: float = 0.0,
    tail_lines_on_failure: int = 20,
    disable_plugin_autoload: bool = False,
    output: TextIO = sys.stdout,
) -> GroupResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / f"{group.name}.stdout.log"
    stderr_path = logs_dir / f"{group.name}.stderr.log"
    command = _build_command(group, list(pytest_args or []), python_executable=python_executable)

    env = dict(os.environ)
    if disable_plugin_autoload:
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    print(f"[pytest-groups] {group.name}: {' '.join(command)}", file=output)
    start = time.monotonic()
    last_heartbeat_at = start
    last_output_at = start
    last_stdout_bytes = 0
    last_stderr_bytes = 0
    timed_out = False
    idle_timed_out = False

    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_file, stderr_path.open(
        "w",
        encoding="utf-8",
        errors="replace",
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )

        while process.poll() is None:
            now = time.monotonic()
            stdout_file.flush()
            stderr_file.flush()
            stdout_bytes, stderr_bytes = _log_sizes(stdout_path, stderr_path)
            if stdout_bytes != last_stdout_bytes or stderr_bytes != last_stderr_bytes:
                last_output_at = now
                last_stdout_bytes = stdout_bytes
                last_stderr_bytes = stderr_bytes

            idle_seconds = now - last_output_at
            if heartbeat_seconds > 0 and now - last_heartbeat_at >= heartbeat_seconds:
                elapsed = now - start
                print(
                    "[pytest-groups] "
                    f"{group.name}: elapsed={_format_seconds(elapsed)} "
                    f"pid={process.pid} stdout_bytes={stdout_bytes} stderr_bytes={stderr_bytes} "
                    f"idle={_format_seconds(idle_seconds)}",
                    file=output,
                )
                last_heartbeat_at = now

            if timeout_seconds > 0 and now - start >= timeout_seconds:
                timed_out = True
                print(
                    f"[pytest-groups] {group.name}: hard timeout after {_format_seconds(now - start)}",
                    file=output,
                )
                _terminate_process_tree(process)
                break

            if idle_timeout_seconds > 0 and idle_seconds >= idle_timeout_seconds:
                idle_timed_out = True
                print(
                    f"[pytest-groups] {group.name}: idle timeout after {_format_seconds(idle_seconds)}",
                    file=output,
                )
                _terminate_process_tree(process)
                break

            time.sleep(0.1)

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            process.wait(timeout=5)

    elapsed = time.monotonic() - start
    stdout_bytes, stderr_bytes = _log_sizes(stdout_path, stderr_path)
    returncode = TIMEOUT_RETURN_CODE if timed_out or idle_timed_out else int(process.returncode or 0)
    print(
        "[pytest-groups] "
        f"{group.name}: exit={returncode} elapsed={_format_seconds(elapsed)} "
        f"stdout_bytes={stdout_bytes} stderr_bytes={stderr_bytes}",
        file=output,
    )

    if returncode != 0 and tail_lines_on_failure > 0:
        _print_log_tail("stdout", stdout_path, line_count=tail_lines_on_failure, output=output)
        _print_log_tail("stderr", stderr_path, line_count=tail_lines_on_failure, output=output)

    return GroupResult(
        name=group.name,
        command=tuple(command),
        returncode=returncode,
        elapsed_seconds=elapsed,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        timed_out=timed_out,
        idle_timed_out=idle_timed_out,
    )


def run_groups(
    groups: list[PytestGroup],
    *,
    logs_dir: Path = DEFAULT_LOG_DIR,
    pytest_args: list[str] | None = None,
    timeout_seconds: float = 0.0,
    heartbeat_seconds: float = 30.0,
    idle_timeout_seconds: float = 0.0,
    tail_lines_on_failure: int = 20,
    disable_plugin_autoload: bool = False,
    fail_fast: bool = True,
    output: TextIO = sys.stdout,
) -> list[GroupResult]:
    results: list[GroupResult] = []
    for group in groups:
        result = run_group(
            group,
            logs_dir=logs_dir,
            pytest_args=list(pytest_args or []),
            timeout_seconds=timeout_seconds,
            heartbeat_seconds=heartbeat_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            tail_lines_on_failure=tail_lines_on_failure,
            disable_plugin_autoload=disable_plugin_autoload,
            output=output,
        )
        results.append(result)
        if fail_fast and result.returncode != 0:
            break
    return results


def _exit_code(results: list[GroupResult]) -> int:
    for result in results:
        if result.returncode != 0:
            return result.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run pytest groups with progress logs.")
    parser.add_argument(
        "--group",
        action="append",
        type=_parse_group_spec,
        required=True,
        help="Pytest group in NAME=target[,target...] format. Repeat for multiple groups.",
    )
    parser.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        help="Extra argument passed through to pytest. Repeat for multiple args.",
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help=f"Directory for per-group stdout/stderr logs. Defaults to {DEFAULT_LOG_DIR}.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=0.0,
        help="Hard timeout per group. 0 disables hard timeout.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=30.0,
        help="Seconds between progress heartbeat lines. 0 disables heartbeat.",
    )
    parser.add_argument(
        "--idle-timeout-seconds",
        type=float,
        default=0.0,
        help="Terminate a group when stdout/stderr byte counts do not change for this many seconds. 0 disables.",
    )
    parser.add_argument(
        "--tail-lines-on-failure",
        type=int,
        default=20,
        help="Print this many stdout/stderr tail lines when a group fails or times out. 0 disables.",
    )
    parser.add_argument(
        "--disable-plugin-autoload",
        action="store_true",
        help="Set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 for faster isolated runs.",
    )
    parser.add_argument(
        "--no-fail-fast",
        action="store_true",
        help="Continue running remaining groups after a group fails.",
    )
    args = parser.parse_args(argv)

    results = run_groups(
        list(args.group),
        logs_dir=args.logs_dir,
        pytest_args=list(args.pytest_arg or []),
        timeout_seconds=max(0.0, args.timeout_seconds),
        heartbeat_seconds=max(0.0, args.heartbeat_seconds),
        idle_timeout_seconds=max(0.0, args.idle_timeout_seconds),
        tail_lines_on_failure=max(0, args.tail_lines_on_failure),
        disable_plugin_autoload=bool(args.disable_plugin_autoload),
        fail_fast=not args.no_fail_fast,
    )
    return _exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
