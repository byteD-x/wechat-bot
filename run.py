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
            print(
                f"[{str(item.get('mode') or '').upper() or 'UNKNOWN'}] "
                f"{str(item.get('id') or '-')}"
            )
            print(
                f"  闂傚倸鍊风粈渚€骞夐敍鍕殰婵°倕鍟伴惌娆撴煙鐎电啸缁惧彞绮欓弻鐔煎箲閹伴潧娈紓渚囧亜缁夊綊寮诲☉銏╂晝闁挎繂妫涢ˇ銊╂⒑? {_format_timestamp(item.get('created_at'))} | "
                f"濠电姷鏁告慨浼村垂瑜版帗鍋夐柕蹇嬪€曠粈鍐┿亜韫囨挻鍣芥俊? {_format_size(item.get('size_bytes'))} | "
                f"闂傚倸鍊风粈渚€骞栭锕€纾圭紒瀣紩濞差亝鏅查柛娑变簼閻庡姊洪棃娑氱疄闁稿﹥娲熷? {len(list(item.get('included_files') or []))}"
            )
            if item.get("label"):
                print(f"  闂傚倸鍊风粈渚€骞栭銈囩煋闁哄鍤氬ú顏勎╅柍鍝勶攻閺? {item.get('label')}")
            print(f"  闂傚倷娴囧畷鍨叏瀹曞洦濯伴柨鏇炲€搁崹鍌炴煙濞堝灝鏋熸い? {item.get('path')}")

    print()
    print("Summary")
    print(
        f"- 闂傚倸鍊风粈渚€骞栭锔藉亱闁告劦鍠栫壕濠氭煙閹规劦鍤欑紒?quick: {_format_timestamp(summary.get('latest_quick_backup_at'))}\n"
        f"- 闂傚倸鍊风粈渚€骞栭锔藉亱闁告劦鍠栫壕濠氭煙閹规劦鍤欑紒?full: {_format_timestamp(summary.get('latest_full_backup_at'))}\n"
        f"- 闂傚倸鍊风粈渚€骞栭锔藉亱闁告劦鍠栫壕濠氭煙閸撗呭笡闁绘挻鐩弻娑氫沪閸撗€濮囩紓浣芥硾瀵爼濡甸崟顖涙櫆閻犲洦褰冮～顏嗙磽娴ｇ鈧湱鏁敓鐘茬濠电姴鍟欢鐐烘煕椤愶絿鐭嬮柟鐧哥秮濮? {_format_size(summary.get('latest_backup_size_bytes'))}"
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

    print(f"闂備浇顕уù鐑藉箠閹捐绠熼梽鍥Φ閹版澘绀冩い鏃傚帶閻庮參姊洪崨濠庢畼闁稿孩鍔欏畷?{backup.get('mode')} 濠电姷鏁告慨浼村垂閻撳簶鏋栨繛鎴炩棨濞差亝鏅插璺猴龚閸? {backup.get('id')}")
    print(f"闂傚倷娴囧畷鍨叏瀹曞洦濯伴柨鏇炲€搁崹鍌炴煙濞堝灝鏋熸い? {backup.get('path')}")
    print(f"濠电姷鏁告慨浼村垂瑜版帗鍋夐柕蹇嬪€曠粈鍐┿亜韫囨挻鍣芥俊? {_format_size(backup.get('size_bytes'))}")
    print(f"闂傚倸鍊风粈渚€骞栭锕€纾圭紒瀣紩濞差亝鏅查柛娑变簼閻庡姊洪棃娑氱疄闁稿﹥娲熷? {len(list(backup.get('included_files') or []))}")
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
        print(f"濠电姷鏁告慨浼村垂閻撳簶鏋栨繛鎴炩棨濞差亝鏅插璺猴龚閸╃偤姊洪棃娑氬妞わ富鍨跺畷姗€鍩€椤掑嫭鈷戦悹鎭掑妼閺嬫柨鈹戦鐓庢Щ闁伙絿鍏橀弫鎰板椽娴ｅ搫鏁搁梻浣筋嚃閸ㄨ鲸绔熼崱娆掑С闁秆勵殕閸? {exc}")
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

    print(f"濠电姷鏁告慨浼村垂閻撳簶鏋栨繛鎴炩棨濞差亝鏅插璺猴龚閸╃偤姊洪棃娑氬妞わ富鍨跺畷姗€鍩€椤掑嫭鈷戦悹鎭掑妼閺嬫柨鈹戦鐓庢Щ闁伙絿鍏橀弫鎰緞鐎ｎ亖鍋撻悽鍛婄厽闁绘柨鎼。鍏肩節閳ь剚瀵肩€涙鍘? {verification.get('backup', {}).get('id', backup_ref)}")
    print(f"Valid: {'yes' if verification.get('valid') else 'no'}")
    print(f"闂傚倸鍊风粈渚€骞栭锕€纾圭紒瀣紩濞差亝鏅查柛娑变簼閻庡姊洪棃娑氱疄闁稿﹥娲熷? {len(list(verification.get('included_files') or []))}")
    if verification.get("missing_files"):
        print(f"缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸缁犺銇勯幇鍓佺暠濡楀懘姊虹涵鍛涧缂佺姵鍨佃灋婵せ鍋撻柡灞剧洴婵＄兘顢涢悙鎼偓宥咁渻? {', '.join(verification.get('missing_files') or [])}")
    if verification.get("invalid_files"):
        print(f"闂傚倸鍊搁崐鎼佸磹閹间焦鍋嬮煫鍥ㄧ☉绾惧鏌ｉ幇顒備粵闁稿繑绮撻弻娑㈠箻閼碱剙濡介悗瑙勬礀椤︿即濡甸崟顖氬唨闁靛濡囧▓銈囩磽? {', '.join(verification.get('invalid_files') or [])}")
    if verification.get("checksum_missing_files"):
        print(f"缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸缁犺銇勯幇鍫曟闁稿骸绉甸妵鍕冀椤愵澀绮堕梺鍛婂姀閸嬫捇姊绘担鑺ョ《闁哥姵鎸婚幈銊ョ暋閹殿喗娈鹃梺鎸庣箓椤︿即鎮? {', '.join(verification.get('checksum_missing_files') or [])}")
    if verification.get("checksum_mismatches"):
        mismatch_paths = [item.get("path") for item in verification.get("checksum_mismatches") or [] if item.get("path")]
        print(f"闂傚倸鍊风粈渚€骞栭銈囩煓闁告洦鍘藉畷鍙夌節闂堟侗鍎愰柛瀣戠换娑㈠幢濡纰嶅┑锛勫仒缁瑩骞冨鈧幃娆戞崉鏉炵増鐫忛梻浣藉吹閸犳劗鎹㈤崼銉ヨ摕婵炴垯鍨归崘鈧悷婊冪箳缁柨煤椤忓懐鍘? {', '.join(mismatch_paths)}")
    return 0 if verification.get("valid") else 1


def cmd_backup_restore(args: argparse.Namespace) -> int:
    service = _build_backup_service()
    backup_ref = str(getattr(args, "backup_id", "") or "").strip()
    if not backup_ref:
        raise ValueError("backup_id is required")

    apply_restore = bool(getattr(args, "apply", False))
    allow_running_service = bool(getattr(args, "allow_running_service", False))
    warning = "CLI restore is intended for local maintenance. Use --apply only when runtime is stopped."
    if apply_restore and not allow_running_service and _is_local_runtime_service_running():
        block_message = (
            "Runtime services are still running; --apply is blocked by default. "
            "Stop services first or explicitly pass --allow-running-service."
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
        print(f"闂傚倸鍊峰ù鍥敋閺嶎厼鍌ㄧ憸鐗堝笒閸ㄥ倻鎲搁悧鍫濆惞闁搞儺鍓欓惌妤€顭块懜鐢点€掗柣顓燁殜濮婃椽宕ㄦ繝鍐槱闂佸憡鎼粻鎴︼綖韫囨稑绠氱憸婊堟偄閸℃稒鐓欐い鏍ㄧ☉椤ュ绱掗妸銉﹀仴闁? {exc}")
        print(warning)
        return 1

    if not apply_restore:
        payload = _build_restore_payload(plan, dry_run=True, warning=warning)
        if bool(getattr(args, "json", False)):
            return _print_json_result(payload, success=bool(plan.get("valid")))
        print(f"闂傚倸鍊峰ù鍥敋閺嶎厼鍌ㄧ憸鐗堝笒閸ㄥ倻鎲搁悧鍫濆惞闁搞儺鍓欓惌妤€顭块懜鐢点€掗柣顓燁殜濮婃椽宕ㄦ繝鍐槱闂佸憡鎼粻鎴︼綖韫囨柣鍋呴柛鎰ㄦ櫅閳ь剛鏁婚弻锝夋偄閸濆嫷鏆┑鐘亾濞寸厧鐡ㄩ悡? {plan.get('backup', {}).get('id', backup_ref)}")
        print(f"Valid: {'yes' if plan.get('valid') else 'no'}")
        print(f"闂傚倸鍊风粈渚€骞栭锕€纾圭紒瀣紩濞差亝鏅查柛娑变簼閻庡姊洪棃娑氱疄闁稿﹥娲熷? {len(list(plan.get('included_files') or []))}")
        if plan.get("missing_files"):
            print(f"缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸缁犺銇勯幇鍓佺暠濡楀懘姊虹涵鍛涧缂佺姵鍨佃灋婵せ鍋撻柡灞剧洴婵＄兘顢涢悙鎼偓宥咁渻? {', '.join(plan.get('missing_files') or [])}")
        if plan.get("invalid_files"):
            print(f"闂傚倸鍊搁崐鎼佸磹閹间焦鍋嬮煫鍥ㄧ☉绾惧鏌ｉ幇顒備粵闁稿繑绮撻弻娑㈠箻閼碱剙濡介悗瑙勬礀椤︿即濡甸崟顖氬唨闁靛濡囧▓銈囩磽? {', '.join(plan.get('invalid_files') or [])}")
        if plan.get("checksum_missing_files"):
            print(f"缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸缁犺銇勯幇鍫曟闁稿骸绉甸妵鍕冀椤愵澀绮堕梺鍛婂姀閸嬫捇姊绘担鑺ョ《闁哥姵鎸婚幈銊ョ暋閹殿喗娈鹃梺鎸庣箓椤︿即鎮? {', '.join(plan.get('checksum_missing_files') or [])}")
        if plan.get("checksum_mismatches"):
            mismatch_paths = [item.get("path") for item in plan.get("checksum_mismatches") or [] if item.get("path")]
            print(f"闂傚倸鍊风粈渚€骞栭銈囩煓闁告洦鍘藉畷鍙夌節闂堟侗鍎愰柛瀣戠换娑㈠幢濡纰嶅┑锛勫仒缁瑩骞冨鈧幃娆戞崉鏉炵増鐫忛梻浣藉吹閸犳劗鎹㈤崼銉ヨ摕婵炴垯鍨归崘鈧悷婊冪箳缁柨煤椤忓懐鍘? {', '.join(mismatch_paths)}")
        print(warning)
        return 0 if plan.get("valid") else 1

    pre_restore_backup = None
    try:
        if not plan.get("valid"):
            payload = _build_restore_payload(plan, dry_run=False, warning=warning)
            if bool(getattr(args, "json", False)):
                _print_json(payload)
            else:
                print("Restore aborted because plan validation did not pass.")
                if plan.get("missing_files"):
                    print(f"缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸缁犺銇勯幇鍓佺暠濡楀懘姊虹涵鍛涧缂佺姵鍨佃灋婵せ鍋撻柡灞剧洴婵＄兘顢涢悙鎼偓宥咁渻? {', '.join(plan.get('missing_files') or [])}")
                if plan.get("invalid_files"):
                    print(f"闂傚倸鍊搁崐鎼佸磹閹间焦鍋嬮煫鍥ㄧ☉绾惧鏌ｉ幇顒備粵闁稿繑绮撻弻娑㈠箻閼碱剙濡介悗瑙勬礀椤︿即濡甸崟顖氬唨闁靛濡囧▓銈囩磽? {', '.join(plan.get('invalid_files') or [])}")
                if plan.get("checksum_missing_files"):
                    print(f"缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸缁犺銇勯幇鍫曟闁稿骸绉甸妵鍕冀椤愵澀绮堕梺鍛婂姀閸嬫捇姊绘担鑺ョ《闁哥姵鎸婚幈銊ョ暋閹殿喗娈鹃梺鎸庣箓椤︿即鎮? {', '.join(plan.get('checksum_missing_files') or [])}")
                if plan.get("checksum_mismatches"):
                    mismatch_paths = [item.get("path") for item in plan.get("checksum_mismatches") or [] if item.get("path")]
                    print(f"闂傚倸鍊风粈渚€骞栭銈囩煓闁告洦鍘藉畷鍙夌節闂堟侗鍎愰柛瀣戠换娑㈠幢濡纰嶅┑锛勫仒缁瑩骞冨鈧幃娆戞崉鏉炵増鐫忛梻浣藉吹閸犳劗鎹㈤崼銉ヨ摕婵炴垯鍨归崘鈧悷婊冪箳缁柨煤椤忓懐鍘? {', '.join(mismatch_paths)}")
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

        print(f"闂傚倸鍊峰ù鍥敋閺嶎厼鍌ㄧ憸鐗堝笒閸ㄥ倻鎲搁悧鍫濆惞闁搞儺鍓氶崵鎴炪亜閹达絾顥夊ù婊堢畺閺岋綁鎮㈤崫鍕垫毉濠电姭鍋撳ù鐓庣摠閻? {plan.get('backup', {}).get('id', backup_ref)}")
        print(f"闂傚倸鍊峰ù鍥敋閺嶎厼鍌ㄧ憸鐗堝笒閸ㄥ倻鎲搁悧鍫濆惞闁搞儺鍓欓拑鐔兼煏婢跺牆鍔滄い銉︾箞濮婃椽骞栭悙鎻掑Х闂傚倸瀚€氫即銆侀弴鐔侯浄閻庯綆鍋嗛崢? {restore_result.get('restored_count', 0)}")
        print(f"闂傚倸鍊峰ù鍥敋閺嶎厼鍌ㄧ憸鐗堝笒閸ㄥ倻鎲搁悧鍫濆惞闁搞儺鍓欓拑鐔兼煏婢跺牆鍔ゆい锔诲弮閹鐛崹顔煎闂佺懓鍟跨换妤呭Φ閹版澘唯闁冲搫鍊婚崢? {pre_restore_backup.get('id')}")
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
            print(f"闂傚倸鍊峰ù鍥敋閺嶎厼鍌ㄧ憸鐗堝笒閸ㄥ倻鎲搁悧鍫濆惞闁搞儺鍓欓惌妤€顭跨捄鐚村姛缂佹劗鍋ら弻鈩冨緞婵犲嫬鈷堥梺绋款儏椤︽娊路? {exc}")
            if pre_restore_backup:
                print(f"闂備浇顕у锕傦綖婢舵劖鍋ら柡鍥╁剱閸ゆ洟鏌熼幑鎰厫鐎规洖寮堕幈銊ノ熼崹顔惧帿闂佺顑傞弲婊呮崲濞戙垹骞㈡俊顖氭惈椤牓姊洪崨濠傜瑲閻㈩垱甯￠垾锔炬崉閵婏箑纾梺鎯х箰婢э綁濮€閻欌偓閻斿棛鎲歌箛鏃€鍙忛柛鎾楀懍绗夊┑鐐村灟閸╁嫰寮崘顔界厪闁割偅绻冮崳褰掓倵? {pre_restore_backup.get('id')}")
                if rollback_result and rollback_result.get("success"):
                    print(f"闂備浇顕у锕傦綖婢舵劖鍋ら柡鍥╁С閻掑﹥銇勮箛鎾跺闁告俺顫夌换婵囩節閸屾粌顣虹紓浣插亾濠㈣埖鍔栭悡蹇撯攽閻愯尙浠㈤柛鏃€绮庣槐鎺楀焵椤掑嫬鐒垫い鎺嗗亾闁宠鍨块幃鈺冩嫚瑜庨弫鐐箾閿濆懏澶勬俊鐐舵閻ｇ兘鎮介崨濠冩珖闂佺鏈銊╂偩閹惰姤鈷戦梻鍫熺〒缁犲啿鈹戦锝呭箹閸楀崬鈹戦悩宕囶暡闁绘挻娲熼弻鐔煎箚瑜忛敍宥団偓娑欑箞濮婃椽宕烽鐐插Е闂佸搫鎳愭繛鈧? {rollback_backup_id}")
                elif rollback_backup_id and rollback_error:
                    print(f"闂傚倸鍊烽懗鍫曞储瑜旈妴鍐╂償閵忋埄娲稿┑鐘诧工鐎氼參宕ｈ箛娑欑厓闁告繂瀚崳褰掓煟閹邦剨韬柡宀嬬秮楠炲洭顢楁径濠冾啀婵犵數鍋涢ˇ顖炴晝閵堝鈧箓宕稿Δ鈧粻姘舵煙濞堝灝鏋ょ紓鍫ヤ憾閺? {rollback_error}")
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
        print(f"濠电姷鏁告慨浼村垂閻撳簶鏋栨繛鎴炩棨濞差亝鏅插璺猴龚閸╃偤姊洪棃娑氬闁瑰啿鐭傞崺鈧い鎺嶇濞搭喚鈧娲忛崝鎴︺€佸☉妯锋婵☆垰鍢叉禍楣冩煟閹邦剚鈻曢柣鏂挎閺岀喖顢涘☉姗嗘缂備降鍔屽锟犲箖? {exc}")
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
        print(f"濠电姷鏁搁崕鎴犲緤閽樺娲晜閻愵剙搴婇梺鍛婂姀閺呮粓宕ｈ箛娑欑厪闊洤艌閸嬫挸鐣烽崶鈺冨祦闂傚倷鐒﹂幃鍫曞磿閼姐倗涓嶉柟杈剧畱閺? {', '.join(protected_ids)}")

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
