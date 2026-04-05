#!/usr/bin/env python3
"""
Unified project entrypoint.

Examples:
    python run.py
    python run.py start
    python run.py setup
    python run.py check
    python run.py web
    python run.py eval --dataset tests/fixtures/evals/smoke_cases.json --preset default --report data/evals/smoke-report.json
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import sys
from datetime import datetime

from backend.core.workspace_backup import (
    DEFAULT_KEEP_FULL_BACKUPS,
    DEFAULT_KEEP_QUICK_BACKUPS,
)
from backend.utils.runtime_artifacts import (
    configure_runtime_environment,
    relocate_known_root_artifacts,
)


def _install_thread_exception_filter() -> None:
    try:
        import threading
        import traceback

        original = getattr(threading, "excepthook", None)

        def _hook(args):  # type: ignore[no-untyped-def]
            exc = getattr(args, "exc_value", None)
            exc_type = getattr(args, "exc_type", None)
            tb = getattr(args, "exc_traceback", None)

            if exc is not None:
                name = exc.__class__.__name__
                module = exc.__class__.__module__ or ""
                if name == "ConnectionRefused" and module.startswith("pynng."):
                    try:
                        sys.stderr.write(
                            "[wcferry] Connection refused. Confirm WeChat is running, logged in, and wcferry is healthy.\n"
                        )
                        sys.stderr.flush()
                    except Exception:
                        pass
                    return

            if callable(original):
                try:
                    return original(args)
                except Exception:
                    pass

            traceback.print_exception(exc_type, exc, tb)

        threading.excepthook = _hook  # type: ignore[assignment]
    except Exception:
        pass


if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.dont_write_bytecode = True

_install_thread_exception_filter()
configure_runtime_environment()
relocate_known_root_artifacts()


def print_banner() -> None:
    print()
    print("=" * 64)
    print("WeChat AI Assistant")
    print("=" * 64)
    print()


def cmd_start(_args: argparse.Namespace) -> None:
    print_banner()
    print("Starting bot core...\n")

    import asyncio

    from backend.main import main as backend_main

    asyncio.run(backend_main())


def cmd_setup(_args: argparse.Namespace) -> int:
    from scripts.setup_wizard import main as setup_main

    setup_main()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from scripts.check import run_check

    return run_check(
        json_output=bool(getattr(args, "json", False)),
        force_refresh=not bool(getattr(args, "cached", False)),
    )


def cmd_web(args: argparse.Namespace) -> int:
    print_banner()

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 5000)
    debug = bool(getattr(args, "debug", False))

    explicit_token = os.environ.get("WECHAT_BOT_API_TOKEN", "").strip()
    explicit_sse_ticket = os.environ.get("WECHAT_BOT_SSE_TICKET", "").strip()

    def _is_loopback_host(value: str) -> bool:
        normalized = str(value or "").strip().lower().rstrip(".")
        if normalized == "localhost":
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    if not _is_loopback_host(host) and not explicit_token:
        print("Refusing to bind non-loopback host without explicit WECHAT_BOT_API_TOKEN.")
        print("Set WECHAT_BOT_API_TOKEN before running `python run.py web --host ...`.")
        return 1

    token = explicit_token
    if not token:
        try:
            import secrets

            token = secrets.token_hex(24)
        except Exception:
            token = ""
    if not token:
        print("Failed to initialize WECHAT_BOT_API_TOKEN. Refusing to start in insecure mode.")
        return 1
    os.environ["WECHAT_BOT_API_TOKEN"] = token

    sse_ticket = explicit_sse_ticket
    if not sse_ticket:
        try:
            import secrets

            sse_ticket = secrets.token_hex(24)
        except Exception:
            sse_ticket = ""
    if not sse_ticket:
        print("Failed to initialize WECHAT_BOT_SSE_TICKET. Refusing to start in insecure mode.")
        return 1
    os.environ["WECHAT_BOT_SSE_TICKET"] = sse_ticket

    print("Starting Web API...")
    print(f"URL: http://{host}:{port}")
    if token:
        print("Local API token is configured and hidden for safety.")
    if debug:
        print("Debug mode is enabled.")
    print("Press Ctrl+C to stop.\n")

    from backend.api import run_server

    run_server(host=host, port=port, debug=debug)
    return 0


def _print_json(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _print_json_result(payload: dict, *, success: bool) -> int:
    _print_json(payload)
    return 0 if success else 1


def _format_timestamp(value: object) -> str:
    try:
        stamp = int(value or 0)
    except (TypeError, ValueError):
        return "-"
    if stamp <= 0:
        return "-"
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S")


def _format_size(size_bytes: object) -> str:
    try:
        size = float(size_bytes or 0)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def _build_backup_service():
    from backend.core.workspace_backup import WorkspaceBackupService

    return WorkspaceBackupService()


def _is_local_runtime_service_running(*, host: str = "127.0.0.1", port: int = 5000, timeout: float = 0.4) -> bool:
    token = str(os.environ.get("WECHAT_BOT_API_TOKEN") or "").strip()
    headers = {"X-Api-Token": token} if token else {}
    conn = None
    try:
        conn = http.client.HTTPConnection(host, int(port), timeout=timeout)
        conn.request("GET", "/api/ping", headers=headers)
        response = conn.getresponse()
        body = response.read()
        if response.status != 200:
            return False
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            return False
        return bool(payload.get("success")) and bool(payload.get("service_running"))
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _format_backup_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized == "quick":
        return "quick"
    if normalized == "full":
        return "full"
    return normalized or "unknown"


def _join_backup_paths(values) -> str:
    items = [str(value or "").strip() for value in list(values or []) if str(value or "").strip()]
    return ", ".join(items)


def _print_backup_entry(item: dict) -> None:
    print(f"[{_format_backup_mode(item.get('mode')).upper()}] {str(item.get('id') or '-')}")
    print(
        f"  创建时间: {_format_timestamp(item.get('created_at'))} | "
        f"大小: {_format_size(item.get('size_bytes'))} | "
        f"文件数: {len(list(item.get('included_files') or []))}"
    )
    if item.get("label"):
        print(f"  标签: {item.get('label')}")
    print(f"  路径: {item.get('path')}")


def _print_backup_validation_summary(title: str, payload: dict, backup_ref: str) -> None:
    backup = dict(payload.get("backup") or {})
    print(f"{title}: {backup.get('id', backup_ref)}")
    print(f"校验结果: {'通过' if payload.get('valid') else '失败'}")
    print(f"包含文件: {len(list(payload.get('included_files') or []))}")

    missing_files = _join_backup_paths(payload.get("missing_files"))
    if missing_files:
        print(f"缺失文件: {missing_files}")

    invalid_files = _join_backup_paths(payload.get("invalid_files"))
    if invalid_files:
        print(f"无效文件: {invalid_files}")

    checksum_missing_files = _join_backup_paths(payload.get("checksum_missing_files"))
    if checksum_missing_files:
        print(f"缺少校验和: {checksum_missing_files}")

    mismatch_paths = _join_backup_paths(
        item.get("path")
        for item in list(payload.get("checksum_mismatches") or [])
        if isinstance(item, dict) and item.get("path")
    )
    if mismatch_paths:
        print(f"校验和不匹配: {mismatch_paths}")


def cmd_backup_list(args: argparse.Namespace) -> int:
    service = _build_backup_service()
    payload = service.list_backups(limit=max(1, int(getattr(args, "limit", 20) or 20)))
    if bool(getattr(args, "json", False)):
        return _print_json(payload)

    backups = list(payload.get("backups") or [])
    summary = dict(payload.get("summary") or {})

    print("Workspace backups")
    print("-" * 50)
    if not backups:
        print("No backups found.")
    else:
        for item in backups:
            _print_backup_entry(item)

    print()
    print("Summary")
    print(
        f"- 最近 quick 备份: {_format_timestamp(summary.get('latest_quick_backup_at'))}\n"
        f"- 最近 full 备份: {_format_timestamp(summary.get('latest_full_backup_at'))}\n"
        f"- 最新备份大小: {_format_size(summary.get('latest_backup_size_bytes'))}"
    )
    return 0


def cmd_backup_create(args: argparse.Namespace) -> int:
    service = _build_backup_service()
    backup = service.create_backup(
        str(getattr(args, "mode", "") or "").strip().lower(),
        label=str(getattr(args, "label", "") or "").strip(),
    )
    payload = {
        "success": True,
        "backup": backup,
    }
    if bool(getattr(args, "json", False)):
        return _print_json(payload)

    print(f"已创建 {_format_backup_mode(backup.get('mode'))} 备份: {backup.get('id')}")
    print(f"路径: {backup.get('path')}")
    print(f"大小: {_format_size(backup.get('size_bytes'))}")
    print(f"文件数: {len(list(backup.get('included_files') or []))}")
    return 0


def _build_restore_payload(plan: dict, *, dry_run: bool, warning: str = "") -> dict:
    payload = {
        "success": bool(plan.get("valid")),
        "dry_run": dry_run,
        "backup": plan.get("backup"),
        "included_files": list(plan.get("included_files") or []),
        "missing_files": list(plan.get("missing_files") or []),
        "invalid_files": list(plan.get("invalid_files") or []),
        "checksum_missing_files": list(plan.get("checksum_missing_files") or []),
        "checksum_mismatches": list(plan.get("checksum_mismatches") or []),
    }
    if warning:
        payload["warning"] = warning
    return payload


def cmd_backup_verify(args: argparse.Namespace) -> int:
    service = _build_backup_service()
    backup_ref = str(getattr(args, "backup_id", "") or "").strip()
    if not backup_ref:
        raise ValueError("backup_id is required")

    try:
        verification = service.verify_backup(backup_ref)
    except Exception as exc:
        payload = {
            "success": False,
            "backup": None,
            "included_files": [],
            "missing_files": [],
            "invalid_files": [],
            "checksum_missing_files": [],
            "checksum_mismatches": [],
            "message": str(exc),
        }
        if bool(getattr(args, "json", False)):
            return _print_json_result(payload, success=False)
        print(f"备份校验失败: {exc}")
        return 1

    payload = {
        "success": bool(verification.get("valid")),
        "backup": verification.get("backup"),
        "included_files": list(verification.get("included_files") or []),
        "missing_files": list(verification.get("missing_files") or []),
        "invalid_files": list(verification.get("invalid_files") or []),
        "checksum_missing_files": list(verification.get("checksum_missing_files") or []),
        "checksum_mismatches": list(verification.get("checksum_mismatches") or []),
        "valid": bool(verification.get("valid")),
    }
    if bool(getattr(args, "json", False)):
        return _print_json_result(payload, success=bool(verification.get("valid")))

    _print_backup_validation_summary("备份校验", payload, backup_ref)
    return 0 if verification.get("valid") else 1


def cmd_backup_restore(args: argparse.Namespace) -> int:
    service = _build_backup_service()
    backup_ref = str(getattr(args, "backup_id", "") or "").strip()
    if not backup_ref:
        raise ValueError("backup_id is required")

    apply_restore = bool(getattr(args, "apply", False))
    allow_running_service = bool(getattr(args, "allow_running_service", False))
    warning = "CLI 默认仅预览恢复计划，不会写入工作区；如需执行恢复，请显式传入 --apply。"
    if apply_restore and not allow_running_service and _is_local_runtime_service_running():
        block_message = (
            "检测到本地运行中的服务实例。为避免运行时热恢复，请先停止服务；"
            "如确认风险可控，再追加 --allow-running-service。"
        )
        payload = {
            "success": False,
            "dry_run": False,
            "backup": None,
            "included_files": [],
            "missing_files": [],
            "invalid_files": [],
            "checksum_missing_files": [],
            "checksum_mismatches": [],
            "warning": warning,
            "message": block_message,
        }
        if bool(getattr(args, "json", False)):
            return _print_json_result(payload, success=False)
        print(block_message)
        print(warning)
        return 1

    try:
        plan = service.build_restore_plan(backup_ref)
    except Exception as exc:
        payload = {
            "success": False,
            "dry_run": not apply_restore,
            "backup": None,
            "included_files": [],
            "missing_files": [],
            "invalid_files": [],
            "checksum_missing_files": [],
            "checksum_mismatches": [],
            "warning": warning,
            "message": str(exc),
        }
        if bool(getattr(args, "json", False)):
            return _print_json_result(payload, success=False)
        print(f"恢复预检失败: {exc}")
        print(warning)
        return 1

    if not apply_restore:
        payload = _build_restore_payload(plan, dry_run=True, warning=warning)
        payload["valid"] = bool(plan.get("valid"))
        if bool(getattr(args, "json", False)):
            return _print_json_result(payload, success=bool(plan.get("valid")))
        _print_backup_validation_summary("恢复预检", payload, backup_ref)
        print(warning)
        return 0 if plan.get("valid") else 1

    pre_restore_backup = None
    try:
        if not plan.get("valid"):
            payload = _build_restore_payload(plan, dry_run=False, warning=warning)
            payload["valid"] = False
            if bool(getattr(args, "json", False)):
                _print_json(payload)
            else:
                print("恢复计划未通过校验，已拒绝执行。")
                _print_backup_validation_summary("恢复预检", payload, backup_ref)
            return 1

        pre_restore_backup = service.create_backup("quick", label="pre-restore-cli")
        restore_result = service.apply_restore(backup_ref)
        payload = _build_restore_payload(plan, dry_run=False, warning=warning)
        payload.update(
            {
                "success": True,
                "valid": True,
                "pre_restore_backup": pre_restore_backup,
                "restore": restore_result,
            }
        )
        service.save_restore_result(payload)
        if bool(getattr(args, "json", False)):
            return _print_json(payload)

        print(f"恢复来源: {plan.get('backup', {}).get('id', backup_ref)}")
        print(f"已恢复文件: {restore_result.get('restored_count', 0)}")
        print(f"回滚快照: {pre_restore_backup.get('id')}")
        print(warning)
        return 0
    except Exception as exc:
        rollback_result = None
        rollback_error = ""
        rollback_backup_id = ""
        if isinstance(pre_restore_backup, dict):
            rollback_backup_id = str(pre_restore_backup.get("id") or "").strip()
        if rollback_backup_id:
            try:
                rollback_result = service.apply_restore(rollback_backup_id)
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)
        payload = _build_restore_payload(plan, dry_run=False, warning=warning)
        payload.update(
            {
                "success": False,
                "valid": bool(plan.get("valid")),
                "message": str(exc),
                "pre_restore_backup": pre_restore_backup,
                "rollback": rollback_result,
                "rollback_error": rollback_error,
            }
        )
        service.save_restore_result(payload)
        if bool(getattr(args, "json", False)):
            _print_json(payload)
        else:
            print(f"恢复失败: {exc}")
            if pre_restore_backup:
                print(f"已保留预恢复快照: {pre_restore_backup.get('id')}")
                if rollback_result and rollback_result.get("success"):
                    print(f"已使用预恢复快照回滚: {rollback_backup_id}")
                elif rollback_backup_id and rollback_error:
                    print(f"回滚失败: {rollback_error}")
            print(warning)
        return 1


def cmd_backup_cleanup(args: argparse.Namespace) -> int:
    service = _build_backup_service()
    apply_cleanup = bool(getattr(args, "apply", False))
    keep_quick = getattr(args, "keep_quick", DEFAULT_KEEP_QUICK_BACKUPS)
    keep_full = getattr(args, "keep_full", DEFAULT_KEEP_FULL_BACKUPS)

    try:
        result = service.cleanup_backups(
            keep_quick=keep_quick,
            keep_full=keep_full,
            apply=apply_cleanup,
        )
    except Exception as exc:
        payload = {
            "success": False,
            "dry_run": not apply_cleanup,
            "delete_candidates": [],
            "deleted_backups": [],
            "candidate_count": 0,
            "deleted_count": 0,
            "reclaimable_bytes": 0,
            "reclaimed_bytes": 0,
            "message": str(exc),
        }
        if bool(getattr(args, "json", False)):
            return _print_json_result(payload, success=False)
        print(f"备份清理失败: {exc}")
        return 1

    if bool(getattr(args, "json", False)):
        return _print_json_result(result, success=True)

    keep_policy = dict(result.get("keep_policy") or {})
    protected_ids = list(result.get("protected_backup_ids") or [])
    selected_entries = (
        list(result.get("deleted_backups") or [])
        if apply_cleanup
        else list(result.get("delete_candidates") or [])
    )
    print("Workspace backup cleanup")
    print("-" * 50)
    print(
        f"Mode: {'apply' if apply_cleanup else 'dry_run'}\n"
        f"Keep policy: quick {keep_policy.get('keep_quick', keep_quick)} / "
        f"full {keep_policy.get('keep_full', keep_full)}"
    )
    if protected_ids:
        print(f"受保护备份: {', '.join(protected_ids)}")

    if apply_cleanup:
        print(
            f"Deleted: {result.get('deleted_count', 0)} backups, "
            f"reclaimed {_format_size(result.get('reclaimed_bytes'))}"
        )
    else:
        print(
            f"Candidates: {result.get('candidate_count', 0)} backups, "
            f"reclaimable {_format_size(result.get('reclaimable_bytes'))}"
        )

    if not selected_entries:
        print("No backups matched the cleanup policy.")
        return 0

    print()
    for entry in selected_entries:
        print(
            f"[{_format_backup_mode(entry.get('mode')).upper()}] "
            f"{entry.get('id')} / {_format_timestamp(entry.get('created_at'))} / "
            f"{_format_size(entry.get('size_bytes'))}"
        )
    return 0


def cmd_backup_help(args: argparse.Namespace) -> int:
    backup_parser = getattr(args, "backup_parser", None)
    if backup_parser is not None:
        backup_parser.print_help()
    return 1


def cmd_eval(args: argparse.Namespace) -> int:
    from backend.core.eval_runner import evaluate_dataset, write_eval_report

    dataset_path = args.dataset
    preset = str(args.preset or "default").strip() or "default"
    report_path = args.report

    report = evaluate_dataset(dataset_path, preset=preset)
    write_eval_report(report, report_path)

    summary = report.get("summary") or {}
    regressions = list(report.get("regressions") or [])

    print(f"Eval report written to: {report_path}")
    print(
        "Summary: "
        f"cases={summary.get('total_cases', 0)}, "
        f"empty_reply_rate={summary.get('empty_reply_rate', 0)}, "
        f"short_reply_rate={summary.get('short_reply_rate', 0)}, "
        f"retrieval_hit_rate={summary.get('retrieval_hit_rate', 0)}, "
        f"manual_feedback_hit_rate={summary.get('manual_feedback_hit_rate', 0)}, "
        f"runtime_exception_count={summary.get('runtime_exception_count', 0)}"
    )

    if regressions:
        print("Regressions:")
        for item in regressions:
            print(
                f"- {item.get('metric')}: {item.get('reason')} "
                f"(actual={item.get('actual')}, threshold={item.get('threshold')})"
            )
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    from backend.core.config_cli import build_config_parser

    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Unified management entrypoint for the WeChat AI Assistant project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run.py start\n"
            "  python run.py setup\n"
            "  python run.py check\n"
            "  python run.py check --json\n"
            "  python run.py web\n"
            "  python run.py backup list --json\n"
            "  python run.py backup create --mode quick --label nightly\n"
            "  python run.py backup verify --backup-id <backup-id> --json\n"
            "  python run.py backup cleanup --keep-quick 5 --keep-full 3\n"
            "  python run.py eval --dataset tests/fixtures/evals/smoke_cases.json "
            "--preset default --report data/evals/smoke-report.json\n"
        ),
    )

    subparsers = parser.add_subparsers(
        title="commands",
        dest="command",
        metavar="<command>",
    )

    parser_start = subparsers.add_parser(
        "start",
        help="start the bot runtime",
        description="Start the WeChat AI bot runtime.",
    )
    parser_start.set_defaults(func=cmd_start)

    parser_setup = subparsers.add_parser(
        "setup",
        help="run the setup wizard",
        description="Run the interactive setup wizard.",
    )
    parser_setup.set_defaults(func=cmd_setup)

    parser_check = subparsers.add_parser(
        "check",
        help="run environment checks",
        description="Run environment and dependency checks.",
    )
    parser_check.add_argument(
        "--json",
        action="store_true",
        help="Output the full readiness report as JSON.",
    )
    parser_check.add_argument(
        "--cached",
        action="store_true",
        help="Reuse the short-lived readiness cache instead of forcing a refresh.",
    )
    parser_check.set_defaults(func=cmd_check)

    parser_web = subparsers.add_parser(
        "web",
        help="start the Web API",
        description="Start the local Web API service.",
    )
    parser_web.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind. Defaults to 127.0.0.1.",
    )
    parser_web.add_argument(
        "--port",
        "-p",
        type=int,
        default=5000,
        help="Port to bind. Defaults to 5000.",
    )
    parser_web.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode.",
    )
    parser_web.set_defaults(func=cmd_web)

    parser_eval = subparsers.add_parser(
        "eval",
        help="run offline eval",
        description="Run deterministic offline replay evaluation.",
    )
    parser_eval.add_argument(
        "--dataset",
        required=True,
        help="Path to the eval dataset JSON file.",
    )
    parser_eval.add_argument(
        "--preset",
        default="default",
        help="Preset name to record in the report.",
    )
    parser_eval.add_argument(
        "--report",
        required=True,
        help="Output path for the generated report JSON.",
    )
    parser_eval.set_defaults(func=cmd_eval)

    parser_backup = subparsers.add_parser(
        "backup",
        help="manage workspace backups",
        description="List, create, clean up, preview, or restore workspace backups.",
    )
    backup_subparsers = parser_backup.add_subparsers(
        dest="backup_command",
        metavar="<backup-command>",
    )
    backup_subparsers.required = True
    parser_backup.set_defaults(func=cmd_backup_help, backup_parser=parser_backup)

    parser_backup_list = backup_subparsers.add_parser(
        "list",
        help="list workspace backups",
        description="List workspace backups with summary information.",
    )
    parser_backup_list.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of backups to return. Defaults to 20.",
    )
    parser_backup_list.add_argument(
        "--json",
        action="store_true",
        help="Output the backup list as JSON.",
    )
    parser_backup_list.set_defaults(func=cmd_backup_list)

    parser_backup_create = backup_subparsers.add_parser(
        "create",
        help="create a workspace backup",
        description="Create a quick or full workspace backup.",
    )
    parser_backup_create.add_argument(
        "--mode",
        choices=("quick", "full"),
        default="quick",
        help="Backup mode. Defaults to quick.",
    )
    parser_backup_create.add_argument(
        "--label",
        default="",
        help="Optional label to include in the backup id.",
    )
    parser_backup_create.add_argument(
        "--json",
        action="store_true",
        help="Output the created backup entry as JSON.",
    )
    parser_backup_create.set_defaults(func=cmd_backup_create)

    parser_backup_verify = backup_subparsers.add_parser(
        "verify",
        help="verify backup integrity",
        description="Verify backup files, paths, and checksums.",
    )
    parser_backup_verify.add_argument(
        "--backup-id",
        required=True,
        help="Backup id to verify.",
    )
    parser_backup_verify.add_argument(
        "--json",
        action="store_true",
        help="Output the verification result as JSON.",
    )
    parser_backup_verify.set_defaults(func=cmd_backup_verify)

    parser_backup_restore = backup_subparsers.add_parser(
        "restore",
        help="preview or apply a backup restore",
        description="Preview a restore plan by default, or apply it with --apply.",
    )
    parser_backup_restore.add_argument(
        "--backup-id",
        required=True,
        help="Backup id to preview or restore.",
    )
    parser_backup_restore.add_argument(
        "--apply",
        action="store_true",
        help="Apply the restore after the plan passes validation.",
    )
    parser_backup_restore.add_argument(
        "--json",
        action="store_true",
        help="Output the restore plan or result as JSON.",
    )
    parser_backup_restore.add_argument(
        "--allow-running-service",
        action="store_true",
        help="Allow --apply even when local runtime service appears to be running.",
    )
    parser_backup_restore.set_defaults(func=cmd_backup_restore)

    parser_backup_cleanup = backup_subparsers.add_parser(
        "cleanup",
        help="preview or delete old workspace backups",
        description="Preview backup cleanup by default, or delete candidates with --apply.",
    )
    parser_backup_cleanup.add_argument(
        "--keep-quick",
        type=int,
        default=DEFAULT_KEEP_QUICK_BACKUPS,
        help=f"How many quick backups to retain. Defaults to {DEFAULT_KEEP_QUICK_BACKUPS}.",
    )
    parser_backup_cleanup.add_argument(
        "--keep-full",
        type=int,
        default=DEFAULT_KEEP_FULL_BACKUPS,
        help=f"How many full backups to retain. Defaults to {DEFAULT_KEEP_FULL_BACKUPS}.",
    )
    parser_backup_cleanup.add_argument(
        "--apply",
        action="store_true",
        help="Delete the cleanup candidates instead of only previewing them.",
    )
    parser_backup_cleanup.add_argument(
        "--json",
        action="store_true",
        help="Output the cleanup preview or result as JSON.",
    )
    parser_backup_cleanup.set_defaults(func=cmd_backup_cleanup)

    build_config_parser(subparsers)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        args.func = cmd_start

    try:
        result = args.func(args)
        if isinstance(result, int):
            sys.exit(result)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
