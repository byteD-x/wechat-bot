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

    token = os.environ.get("WECHAT_BOT_API_TOKEN", "").strip()
    if not token:
        try:
            import secrets

            token = secrets.token_hex(24)
        except Exception:
            token = ""
        if token:
            os.environ["WECHAT_BOT_API_TOKEN"] = token

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


def cmd_backup_list(args: argparse.Namespace) -> int:
    service = _build_backup_service()
    payload = service.list_backups(limit=max(1, int(getattr(args, "limit", 20) or 20)))
    if bool(getattr(args, "json", False)):
        return _print_json(payload)

    backups = list(payload.get("backups") or [])
    summary = dict(payload.get("summary") or {})

    print("工作区备份列表")
    print("-" * 50)
    if not backups:
        print("当前没有可用备份。")
    else:
        for item in backups:
            print(
                f"[{str(item.get('mode') or '').upper() or 'UNKNOWN'}] "
                f"{str(item.get('id') or '-')}"
            )
            print(
                f"  创建时间: {_format_timestamp(item.get('created_at'))} | "
                f"大小: {_format_size(item.get('size_bytes'))} | "
                f"文件数: {len(list(item.get('included_files') or []))}"
            )
            if item.get("label"):
                print(f"  标签: {item.get('label')}")
            print(f"  路径: {item.get('path')}")

    print()
    print("摘要")
    print(
        f"- 最近 quick: {_format_timestamp(summary.get('latest_quick_backup_at'))}\n"
        f"- 最近 full: {_format_timestamp(summary.get('latest_full_backup_at'))}\n"
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

    print(f"已创建 {backup.get('mode')} 备份: {backup.get('id')}")
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
    }
    if bool(getattr(args, "json", False)):
        return _print_json_result(payload, success=bool(verification.get("valid")))

    print(f"备份校验完成: {verification.get('backup', {}).get('id', backup_ref)}")
    print(f"校验结果: {'通过' if verification.get('valid') else '失败'}")
    print(f"文件数: {len(list(verification.get('included_files') or []))}")
    if verification.get("missing_files"):
        print(f"缺失文件: {', '.join(verification.get('missing_files') or [])}")
    if verification.get("invalid_files"):
        print(f"非法路径: {', '.join(verification.get('invalid_files') or [])}")
    if verification.get("checksum_missing_files"):
        print(f"缺少校验和: {', '.join(verification.get('checksum_missing_files') or [])}")
    if verification.get("checksum_mismatches"):
        mismatch_paths = [item.get("path") for item in verification.get("checksum_mismatches") or [] if item.get("path")]
        print(f"校验和不匹配: {', '.join(mismatch_paths)}")
    return 0 if verification.get("valid") else 1


def cmd_backup_restore(args: argparse.Namespace) -> int:
    service = _build_backup_service()
    backup_ref = str(getattr(args, "backup_id", "") or "").strip()
    if not backup_ref:
        raise ValueError("backup_id is required")

    apply_restore = bool(getattr(args, "apply", False))
    warning = "CLI 恢复不会自动停止桌面端或机器人进程；执行 --apply 前请确认应用已停止。"
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
        if bool(getattr(args, "json", False)):
            return _print_json_result(payload, success=bool(plan.get("valid")))
        print(f"恢复预检完成: {plan.get('backup', {}).get('id', backup_ref)}")
        print(f"可恢复: {'是' if plan.get('valid') else '否'}")
        print(f"文件数: {len(list(plan.get('included_files') or []))}")
        if plan.get("missing_files"):
            print(f"缺失文件: {', '.join(plan.get('missing_files') or [])}")
        if plan.get("invalid_files"):
            print(f"非法路径: {', '.join(plan.get('invalid_files') or [])}")
        if plan.get("checksum_missing_files"):
            print(f"缺少校验和: {', '.join(plan.get('checksum_missing_files') or [])}")
        if plan.get("checksum_mismatches"):
            mismatch_paths = [item.get("path") for item in plan.get("checksum_mismatches") or [] if item.get("path")]
            print(f"校验和不匹配: {', '.join(mismatch_paths)}")
        print(warning)
        return 0 if plan.get("valid") else 1

    pre_restore_backup = None
    try:
        if not plan.get("valid"):
            payload = _build_restore_payload(plan, dry_run=False, warning=warning)
            if bool(getattr(args, "json", False)):
                _print_json(payload)
            else:
                print("恢复已中止，备份预检未通过。")
                if plan.get("missing_files"):
                    print(f"缺失文件: {', '.join(plan.get('missing_files') or [])}")
                if plan.get("invalid_files"):
                    print(f"非法路径: {', '.join(plan.get('invalid_files') or [])}")
                if plan.get("checksum_missing_files"):
                    print(f"缺少校验和: {', '.join(plan.get('checksum_missing_files') or [])}")
                if plan.get("checksum_mismatches"):
                    mismatch_paths = [item.get("path") for item in plan.get("checksum_mismatches") or [] if item.get("path")]
                    print(f"校验和不匹配: {', '.join(mismatch_paths)}")
            return 1

        pre_restore_backup = service.create_backup("quick", label="pre-restore-cli")
        restore_result = service.apply_restore(backup_ref)
        payload = _build_restore_payload(plan, dry_run=False, warning=warning)
        payload.update(
            {
                "success": True,
                "pre_restore_backup": pre_restore_backup,
                "restore": restore_result,
            }
        )
        service.save_restore_result(payload)
        if bool(getattr(args, "json", False)):
            return _print_json(payload)

        print(f"恢复完成: {plan.get('backup', {}).get('id', backup_ref)}")
        print(f"恢复文件数: {restore_result.get('restored_count', 0)}")
        print(f"恢复前快照: {pre_restore_backup.get('id')}")
        print(warning)
        return 0
    except Exception as exc:
        payload = _build_restore_payload(plan, dry_run=False, warning=warning)
        payload.update(
            {
                "success": False,
                "message": str(exc),
                "pre_restore_backup": pre_restore_backup,
            }
        )
        service.save_restore_result(payload)
        if bool(getattr(args, "json", False)):
            _print_json(payload)
        else:
            print(f"恢复失败: {exc}")
            if pre_restore_backup:
                print(f"已保留恢复前快照: {pre_restore_backup.get('id')}")
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
    print("工作区备份清理")
    print("-" * 50)
    print(
        f"模式: {'正式清理' if apply_cleanup else 'Dry Run 预览'}\n"
        f"保留策略: quick {keep_policy.get('keep_quick', keep_quick)} / "
        f"full {keep_policy.get('keep_full', keep_full)}"
    )
    if protected_ids:
        print(f"保护备份: {', '.join(protected_ids)}")

    if apply_cleanup:
        print(
            f"已删除 {result.get('deleted_count', 0)} 份备份，"
            f"释放空间 {_format_size(result.get('reclaimed_bytes'))}"
        )
    else:
        print(
            f"候选备份 {result.get('candidate_count', 0)} 份，"
            f"预计释放 {_format_size(result.get('reclaimable_bytes'))}"
        )

    if not selected_entries:
        print("没有符合条件的旧备份。")
        return 0

    print()
    for entry in selected_entries:
        print(
            f"[{str(entry.get('mode') or '').upper() or 'UNKNOWN'}] "
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
