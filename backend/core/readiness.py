"""
结构化运行准备度检查。

本模块为 CLI、Web API 和桌面端提供统一的环境检查结果。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from backend.shared_config import get_app_config_path
from backend.core.oauth_support import get_preset_auth_summary
from backend.transports.wcferry_adapter import (
    _is_windows_admin,
    detect_wcferry_supported_versions,
    detect_wechat_path,
    detect_wechat_version,
)
from backend.wechat_versions import OFFICIAL_SUPPORTED_WECHAT_VERSION

REQUIRED_PACKAGES: Sequence[str] = ("httpx", "openai", "quart", "wcferry")
DEFAULT_READINESS_TTL_SEC = 5.0


def _build_check(
    key: str,
    label: str,
    *,
    passed: Optional[bool],
    message: str,
    blocking: bool = False,
    action: str = "retry",
    action_label: str = "重新检查",
    hint: str = "",
) -> Dict[str, Any]:
    if passed is None:
        status = "skipped"
    else:
        status = "passed" if passed else "failed"

    return {
        "key": key,
        "label": label,
        "status": status,
        "blocking": bool(blocking and passed is False),
        "message": str(message or "").strip(),
        "action": str(action or "retry").strip() or "retry",
        "action_label": str(action_label or "重新检查").strip() or "重新检查",
        "hint": str(hint or "").strip(),
    }


def _check_python_version() -> Dict[str, Any]:
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    passed = version >= (3, 9)
    message = f"Python {version_str}" if passed else f"Python {version_str}，需要 3.9+"
    return _build_check(
        "python_version",
        "Python 版本",
        passed=passed,
        message=message,
        blocking=True,
        action="retry",
        action_label="重新检查",
        hint="请升级到 Python 3.9 或更高版本。",
    )


def _check_dependencies(packages: Iterable[str] = REQUIRED_PACKAGES) -> Dict[str, Any]:
    missing: List[str] = []
    installed: List[str] = []
    for package in packages:
        try:
            __import__(package)
            installed.append(package)
        except ImportError:
            missing.append(package)

    if missing:
        return _build_check(
            "dependencies",
            "依赖安装",
            passed=False,
            message=f"缺少: {', '.join(missing)}",
            blocking=True,
            action="retry",
            action_label="重新检查",
            hint=f"请先安装依赖：pip install {' '.join(missing)}",
        )

    return _build_check(
        "dependencies",
        "依赖安装",
        passed=True,
        message=f"已安装: {', '.join(installed)}",
        blocking=False,
    )


def _count_wechat_processes() -> Optional[int]:
    if os.name != "nt":
        return None

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "((Get-Process WeChat,Weixin -ErrorAction SilentlyContinue) | Measure-Object).Count",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    raw = (completed.stdout or "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return None


def _load_current_config(config_loader: Optional[Callable[[], dict]] = None) -> dict:
    if callable(config_loader):
        try:
            payload = config_loader()
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    config_path = Path(get_app_config_path())
    if not config_path.exists():
        return {}

    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _check_admin_permission(admin_checker: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    if os.name != "nt":
        return _build_check(
            "admin_permission",
            "管理员权限",
            passed=None,
            message="非 Windows 环境，跳过管理员权限检查",
            blocking=False,
        )

    checker = admin_checker or _is_windows_admin
    passed = bool(checker())
    return _build_check(
        "admin_permission",
        "管理员权限",
        passed=passed,
        message="已具备管理员权限" if passed else "未以管理员身份运行",
        blocking=True,
        action="restart_as_admin",
        action_label="以管理员身份重启",
        hint="请使用“以管理员身份运行”启动终端或桌面端。",
    )


def _check_wechat_process(process_counter: Optional[Callable[[], Optional[int]]] = None) -> Dict[str, Any]:
    counter = process_counter or _count_wechat_processes
    count = counter()
    if count is None:
        return _build_check(
            "wechat_process",
            "微信进程",
            passed=None,
            message="无法识别微信进程数量",
            blocking=False,
        )

    if count > 0:
        return _build_check(
            "wechat_process",
            "微信进程",
            passed=True,
            message=f"检测到 {count} 个微信进程",
            blocking=False,
            action="open_wechat",
            action_label="打开微信",
        )

    return _build_check(
        "wechat_process",
        "微信进程",
        passed=False,
        message="未检测到已启动的微信进程",
        blocking=True,
        action="open_wechat",
        action_label="打开微信",
        hint="请先启动并登录微信 PC 客户端。",
    )


def _check_wechat_installation(
    path_getter: Optional[Callable[[], str]] = None,
) -> tuple[Dict[str, Any], str]:
    getter = path_getter or detect_wechat_path
    path = str(getter() or "").strip()
    if not path:
        return (
            _build_check(
                "wechat_installation",
                "微信安装",
                passed=False,
                message="未找到 WeChat.exe 安装路径",
                blocking=True,
                action="retry",
                action_label="重新检查",
                hint="请确认已安装微信 PC 客户端，并且当前账户可访问 WeChat.exe。",
            ),
            "",
        )

    return (
        _build_check(
            "wechat_installation",
            "微信安装",
            passed=True,
            message=f"检测到微信路径: {path}",
            blocking=False,
        ),
        path,
    )


def _check_wechat_compatibility(
    wechat_path: str,
    *,
    version_getter: Optional[Callable[[str], Optional[str]]] = None,
    supported_versions_getter: Optional[Callable[[], List[str]]] = None,
) -> Dict[str, Any]:
    current_path = str(wechat_path or "").strip()
    if not current_path:
        return _build_check(
            "wechat_compatibility",
            "WCFerry 兼容性",
            passed=None,
            message="未检测到微信安装路径，跳过兼容性检查",
            blocking=False,
        )

    current_version = (version_getter or detect_wechat_version)(current_path)
    supported_versions = (supported_versions_getter or detect_wcferry_supported_versions)()

    if not current_version:
        return _build_check(
            "wechat_compatibility",
            "WCFerry 兼容性",
            passed=None,
            message="未读取到微信版本",
            blocking=False,
        )

    if not supported_versions:
        return _build_check(
            "wechat_compatibility",
            "WCFerry 兼容性",
            passed=None,
            message=f"当前微信版本 {current_version}；未读取到本地 wcferry 支持版本",
            blocking=False,
            action="retry",
            action_label="重新检查",
        )

    if current_version in supported_versions:
        return _build_check(
            "wechat_compatibility",
            "WCFerry 兼容性",
            passed=True,
            message=f"当前微信版本 {current_version} 与 wcferry 兼容",
            blocking=False,
        )

    supported_text = ", ".join(supported_versions)
    return _build_check(
        "wechat_compatibility",
        "WCFerry 兼容性",
        passed=False,
        message=f"当前微信版本 {current_version}；本地 wcferry 支持: {supported_text}",
        blocking=True,
        action="retry",
        action_label="我已切换微信版本",
        hint=f"请安装或切换到微信 {OFFICIAL_SUPPORTED_WECHAT_VERSION}。",
    )


def _check_transport_config(config: dict) -> Dict[str, Any]:
    bot_cfg = config.get("bot", {}) if isinstance(config, dict) else {}
    if not isinstance(bot_cfg, dict) or not bot_cfg:
        return _build_check(
            "transport_config",
            "传输配置",
            passed=None,
            message="未检测到共享配置文件，跳过传输配置检查",
            blocking=False,
            action="open_settings",
            action_label="前往设置",
        )

    required_version = str(
        bot_cfg.get("required_wechat_version") or OFFICIAL_SUPPORTED_WECHAT_VERSION
    ).strip()
    silent_mode_required = bool(bot_cfg.get("silent_mode_required", True))
    return _build_check(
        "transport_config",
        "传输配置",
        passed=True,
        message=(
            f"required_wechat_version={required_version}; "
            f"silent_mode_required={silent_mode_required}"
        ),
        blocking=False,
        action="open_settings",
        action_label="前往设置",
    )


def _check_api_config(config: dict) -> Dict[str, Any]:
    api_cfg = config.get("api", {}) if isinstance(config, dict) else {}
    presets = api_cfg.get("presets", []) if isinstance(api_cfg, dict) else []

    valid_count = 0
    for preset in presets:
        if not isinstance(preset, dict):
            continue
        auth_summary = get_preset_auth_summary(preset)
        if auth_summary.get("auth_ready"):
            valid_count += 1

    if valid_count > 0:
        return _build_check(
            "api_config",
            "API 配置",
            passed=True,
            message=f"检测到 {valid_count} 个可用预设",
            blocking=False,
            action="open_settings",
            action_label="前往设置",
        )

    return _build_check(
        "api_config",
        "API 配置",
        passed=False,
        message="未检测到可用 API 预设",
        blocking=True,
        action="open_settings",
        action_label="前往设置",
        hint="请前往设置页补齐至少一个可用预设。",
    )


def _build_suggested_actions(checks: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    suggestions: List[Dict[str, str]] = []
    seen_actions: set[str] = set()

    for check in checks:
        if check.get("status") != "failed" or not check.get("blocking"):
            continue
        action = str(check.get("action") or "").strip()
        label = str(check.get("action_label") or "").strip()
        if not action or action in seen_actions:
            continue
        seen_actions.add(action)
        suggestions.append(
            {
                "action": action,
                "label": label or "执行建议动作",
                "source_check": str(check.get("key") or "").strip(),
            }
        )

    if "retry" not in seen_actions:
        suggestions.append(
            {
                "action": "retry",
                "label": "重新检查",
                "source_check": "",
            }
        )

    return suggestions


def build_readiness_report(
    *,
    config_loader: Optional[Callable[[], dict]] = None,
    admin_checker: Optional[Callable[[], bool]] = None,
    process_counter: Optional[Callable[[], Optional[int]]] = None,
    wechat_path_getter: Optional[Callable[[], str]] = None,
    wechat_version_getter: Optional[Callable[[str], Optional[str]]] = None,
    supported_versions_getter: Optional[Callable[[], List[str]]] = None,
    now_provider: Optional[Callable[[], float]] = None,
) -> Dict[str, Any]:
    now = float((now_provider or time.time)())
    config = _load_current_config(config_loader)

    install_check, wechat_path = _check_wechat_installation(wechat_path_getter)
    checks = [
        _check_python_version(),
        _check_dependencies(),
        _check_admin_permission(admin_checker),
        _check_wechat_process(process_counter),
        install_check,
        _check_wechat_compatibility(
            wechat_path,
            version_getter=wechat_version_getter,
            supported_versions_getter=supported_versions_getter,
        ),
        _check_transport_config(config),
        _check_api_config(config),
    ]

    blocking_count = sum(
        1 for check in checks if check.get("status") == "failed" and check.get("blocking")
    )
    ready = blocking_count == 0

    if ready:
        summary = {
            "title": "运行准备已完成",
            "detail": "环境与配置检查均已通过，可以启动机器人。",
        }
    else:
        summary = {
            "title": f"还差 {blocking_count} 项准备",
            "detail": "先处理阻塞项，再启动机器人会更稳定。",
        }

    return {
        "success": True,
        "ready": ready,
        "blocking_count": blocking_count,
        "checks": checks,
        "suggested_actions": _build_suggested_actions(checks),
        "summary": summary,
        "checked_at": now,
    }


class ReadinessService:
    def __init__(
        self,
        *,
        ttl_sec: float = DEFAULT_READINESS_TTL_SEC,
        builder: Callable[..., Dict[str, Any]] = build_readiness_report,
        time_provider: Callable[[], float] = time.time,
    ) -> None:
        self.ttl_sec = float(ttl_sec)
        self._builder = builder
        self._time_provider = time_provider
        self._cache: Optional[Dict[str, Any]] = None
        self._cached_at = 0.0

    def get_report(self, *, force_refresh: bool = False) -> Dict[str, Any]:
        now = float(self._time_provider())
        if (
            not force_refresh
            and self._cache is not None
            and (now - self._cached_at) < self.ttl_sec
        ):
            return copy.deepcopy(self._cache)

        report = self._builder(now_provider=lambda: now)
        self._cache = copy.deepcopy(report)
        self._cached_at = now
        return report

    def invalidate(self) -> None:
        self._cache = None
        self._cached_at = 0.0


readiness_service = ReadinessService()
