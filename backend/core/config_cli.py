from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from backend.core.config_probe import probe_config
from backend.core.config_service import ConfigService
from backend.shared_config import get_app_config_path, migrate_legacy_config

logger = logging.getLogger(__name__)


def _read_stdin_json() -> Dict[str, Any]:
    payload = sys.stdin.read()
    if not payload.strip():
        return {}
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("stdin JSON must be an object")
    return data


def _build_service() -> ConfigService:
    return ConfigService()


def _load_base_config(service: ConfigService, base_path: str) -> Dict[str, Any]:
    snapshot = service.get_snapshot(config_path=base_path, force_reload=True)
    return snapshot.to_dict()


def _merge_candidate(service: ConfigService, *, base_path: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    base_config = _load_base_config(service, base_path)
    return service._merge_patch(base_config, deepcopy(patch))


def _print_result(payload: Dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    config = migrate_legacy_config(output_path=args.output or get_app_config_path(), force=args.force, backup=not args.no_backup)
    return _print_result(
        {
            "success": True,
            "config": config,
            "config_path": str(Path(args.output or get_app_config_path()).resolve()),
        }
    )


def cmd_validate(args: argparse.Namespace) -> int:
    service = _build_service()
    base_path = str(Path(args.base_path or get_app_config_path()).resolve())
    patch = _read_stdin_json() if args.stdin else {}
    if patch:
        candidate = _merge_candidate(service, base_path=base_path, patch=patch)
    else:
        candidate = _load_base_config(service, base_path)
    normalized = service._validate_config_dict(candidate)
    return _print_result({"success": True, "config": normalized})


def cmd_probe(args: argparse.Namespace) -> int:
    service = _build_service()
    base_path = str(Path(args.base_path or get_app_config_path()).resolve())
    patch = _read_stdin_json() if args.stdin else {}
    if patch:
        candidate = _merge_candidate(service, base_path=base_path, patch=patch)
    else:
        candidate = _load_base_config(service, base_path)
    normalized = service._validate_config_dict(candidate)
    ok, preset_name, message = asyncio.run(
        probe_config(normalized, preset_name=str(args.preset_name or "").strip())
    )
    return _print_result(
        {
            "success": ok,
            "preset_name": preset_name,
            "message": message,
        }
    )


def build_config_parser(subparsers: argparse._SubParsersAction) -> None:
    parser_config = subparsers.add_parser("config", help="共享配置辅助命令")
    config_subparsers = parser_config.add_subparsers(dest="config_command", metavar="<config-command>")

    parser_migrate = config_subparsers.add_parser("migrate", help="迁移旧配置到 app_config.json")
    parser_migrate.add_argument("--output", default=get_app_config_path(), help="输出配置文件路径")
    parser_migrate.add_argument("--force", action="store_true", help="强制重新迁移")
    parser_migrate.add_argument("--no-backup", action="store_true", help="迁移时不备份旧配置")
    parser_migrate.set_defaults(func=cmd_migrate)

    parser_validate = config_subparsers.add_parser("validate", help="校验并规范化配置")
    parser_validate.add_argument("--base-path", default=get_app_config_path(), help="基础配置文件路径")
    parser_validate.add_argument("--stdin", action="store_true", help="从 stdin 读取 patch JSON")
    parser_validate.set_defaults(func=cmd_validate)

    parser_probe = config_subparsers.add_parser("probe", help="使用配置测试 AI 联通")
    parser_probe.add_argument("--base-path", default=get_app_config_path(), help="基础配置文件路径")
    parser_probe.add_argument("--stdin", action="store_true", help="从 stdin 读取 patch JSON")
    parser_probe.add_argument("--preset-name", default="", help="可选，指定要测试的预设名称")
    parser_probe.set_defaults(func=cmd_probe)
