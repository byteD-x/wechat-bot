from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path


def _load_runner_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "quality" / "run_pytest_groups.py"
    spec = importlib.util.spec_from_file_location("run_pytest_groups", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner_module()


def _write_test_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "sample_test.py"
    path.write_text(content, encoding="utf-8")
    return path


def test_pytest_group_runner_heartbeat_reports_log_progress(tmp_path):
    target = _write_test_file(
        tmp_path,
        """
import time


def test_slow_output():
    print("runner-progress", flush=True)
    time.sleep(0.35)
""",
    )
    output = io.StringIO()

    result = RUNNER.run_group(
        RUNNER.PytestGroup("progress", (str(target),)),
        logs_dir=tmp_path / "logs",
        pytest_args=["-s", "-q"],
        cwd=tmp_path,
        heartbeat_seconds=0.05,
        idle_timeout_seconds=0,
        disable_plugin_autoload=True,
        output=output,
    )

    assert result.returncode == 0
    text = output.getvalue()
    assert "stdout_bytes=" in text
    assert "stderr_bytes=" in text
    assert "idle=" in text
    assert "runner-progress" in result.stdout_path.read_text(encoding="utf-8")


def test_pytest_group_runner_idle_timeout_stops_silent_group(tmp_path):
    target = _write_test_file(
        tmp_path,
        """
import time


def test_silent_hang():
    time.sleep(10)
""",
    )
    output = io.StringIO()

    result = RUNNER.run_group(
        RUNNER.PytestGroup("idle", (str(target),)),
        logs_dir=tmp_path / "logs",
        pytest_args=["-q"],
        cwd=tmp_path,
        heartbeat_seconds=0.05,
        idle_timeout_seconds=0.3,
        tail_lines_on_failure=0,
        disable_plugin_autoload=True,
        output=output,
    )

    assert result.returncode == RUNNER.TIMEOUT_RETURN_CODE
    assert result.idle_timed_out is True
    assert "idle timeout after" in output.getvalue()


def test_pytest_group_runner_failure_prints_limited_log_tail(tmp_path):
    target = _write_test_file(
        tmp_path,
        r'''
import sys


def test_failure_tail():
    sys.stderr.write("err-a\nerr-b\nerr-c\n")
    sys.stderr.flush()
    assert False, "tail boom"
''',
    )
    output = io.StringIO()

    result = RUNNER.run_group(
        RUNNER.PytestGroup("failure", (str(target),)),
        logs_dir=tmp_path / "logs",
        pytest_args=["-s", "-q"],
        cwd=tmp_path,
        heartbeat_seconds=0,
        idle_timeout_seconds=0,
        tail_lines_on_failure=2,
        disable_plugin_autoload=True,
        output=output,
    )

    text = output.getvalue()
    assert result.returncode != 0
    assert "[pytest-groups] stderr tail (2 lines):" in text
    assert "err-b" in text
    assert "err-c" in text
    assert "err-a" not in text
