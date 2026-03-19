#!/usr/bin/env python3
"""项目环境自检脚本。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.shared_config import get_app_config_path
from backend.transports.wcferry_adapter import (
    _is_windows_admin,
    detect_wcferry_supported_versions,
    detect_wechat_path,
    detect_wechat_version,
)
from backend.wechat_versions import OFFICIAL_SUPPORTED_WECHAT_VERSION


def check_python_version() -> Tuple[bool, str]:
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    if version >= (3, 9):
        return True, f"Python {version_str}"
    return False, f"Python {version_str}，需要 3.9+"


def check_dependencies() -> Tuple[bool, str, List[str]]:
    required = ["httpx", "openai", "quart", "wcferry"]
    missing: List[str] = []
    installed: List[str] = []
    for package in required:
        try:
            __import__(package)
            installed.append(package)
        except ImportError:
            missing.append(package)
    if missing:
        return False, f"缺少: {', '.join(missing)}", missing
    return True, f"已安装: {', '.join(installed)}", []


def check_admin_permission() -> Tuple[Optional[bool], str]:
    if os.name != "nt":
        return None, "非 Windows 环境，跳过管理员权限检查"
    return _is_windows_admin(), "已具备管理员权限" if _is_windows_admin() else "未以管理员身份运行"


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


def check_wechat_process() -> Tuple[Optional[bool], str]:
    count = _count_wechat_processes()
    if count is None:
        return None, "无法识别微信进程数量"
    if count > 0:
        return True, f"检测到 {count} 个微信进程"
    return False, "未检测到已启动的微信进程"


def check_wechat_installation() -> Tuple[Optional[bool], str, str]:
    path = detect_wechat_path()
    if not path:
        return False, "未找到 WeChat.exe 安装路径", ""
    return True, f"检测到微信路径: {path}", path


def check_wcferry_compatibility(wechat_path: str) -> Tuple[Optional[bool], str]:
    supported_versions = detect_wcferry_supported_versions()
    current_version = detect_wechat_version(wechat_path)

    if not current_version:
        return None, "未读取到微信版本"
    if not supported_versions:
        return None, f"当前微信版本 {current_version}；未读取到本地 wcferry 支持版本"
    if current_version in supported_versions:
        return True, f"当前微信版本 {current_version} 与 wcferry 兼容"

    supported_text = ", ".join(supported_versions)
    return False, f"当前微信版本 {current_version}，本地 wcferry 支持: {supported_text}"


def _load_current_config() -> dict:
    config_path = Path(get_app_config_path())
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check_api_config() -> Tuple[bool, str, int]:
    config = _load_current_config()
    api_cfg = config.get("api", {}) if isinstance(config, dict) else {}
    presets = api_cfg.get("presets", []) if isinstance(api_cfg, dict) else []

    valid_count = 0
    for preset in presets:
        if not isinstance(preset, dict):
            continue
        api_key = str(preset.get("api_key") or "").strip()
        allow_empty_key = bool(preset.get("allow_empty_key", False))
        if allow_empty_key or (api_key and not api_key.upper().startswith("YOUR_")):
            valid_count += 1

    if valid_count > 0:
        return True, f"检测到 {valid_count} 个可用预设", valid_count
    return False, "未检测到可用 API 预设", 0


def check_transport_config() -> Tuple[Optional[bool], str]:
    config = _load_current_config()
    bot_cfg = config.get("bot", {}) if isinstance(config, dict) else {}
    required_version = str(bot_cfg.get("required_wechat_version") or "").strip()
    silent_mode_required = bool(bot_cfg.get("silent_mode_required", True))
    if not bot_cfg:
        return None, "未检测到共享配置文件，跳过传输配置检查"
    return True, (
        f"required_wechat_version={required_version or OFFICIAL_SUPPORTED_WECHAT_VERSION}; "
        f"silent_mode_required={silent_mode_required}"
    )


def _print_result(label: str, result: Optional[bool], message: str) -> None:
    if result is None:
        icon = "⏭"
    else:
        icon = "✅" if result else "❌"
    print(f"{icon} {label}: {message}")


def main() -> int:
    print()
    print("微信 AI 助手环境检测")
    print("-" * 50)
    print()

    issues: List[str] = []
    suggestions: List[str] = []

    ok, message = check_python_version()
    _print_result("Python 版本", ok, message)
    if not ok:
        issues.append("Python 版本过低")
        suggestions.append("升级到 Python 3.9 或更高版本")

    ok, message, missing = check_dependencies()
    _print_result("依赖安装", ok, message)
    if not ok:
        issues.append("缺少必要依赖")
        suggestions.append(f"运行: pip install {' '.join(missing)}")

    admin_ok, message = check_admin_permission()
    _print_result("管理员权限", admin_ok, message)
    if admin_ok is False:
        issues.append("未以管理员身份运行")
        suggestions.append("请使用“以管理员身份运行”启动终端或桌面端")

    process_ok, message = check_wechat_process()
    _print_result("微信进程", process_ok, message)
    if process_ok is False:
        issues.append("微信未启动")
        suggestions.append("请先启动并登录微信 PC 客户端")

    install_ok, message, wechat_path = check_wechat_installation()
    _print_result("微信安装", install_ok, message)
    if install_ok is False:
        issues.append("未找到微信安装")
        suggestions.append("确认已安装微信 PC，并且 WeChat.exe 可被当前账户访问")

    compat_ok, message = check_wcferry_compatibility(wechat_path)
    _print_result("WCFerry 兼容性", compat_ok, message)
    if compat_ok is False:
        issues.append("微信版本与 wcferry 不兼容")
        suggestions.append(f"请安装或切换到微信 {OFFICIAL_SUPPORTED_WECHAT_VERSION}")

    config_ok, message = check_transport_config()
    _print_result("传输配置", config_ok, message)

    ok, message, _count = check_api_config()
    _print_result("API 配置", ok, message)
    if not ok:
        issues.append("未检测到可用 API 预设")
        suggestions.append("运行: python run.py setup")

    print()
    print("-" * 50)

    if not issues:
        print("✅ 检测通过，可以继续运行项目。")
        return 0

    print(f"❌ 发现 {len(issues)} 个问题:")
    for issue in issues:
        print(f"  - {issue}")

    if suggestions:
        print()
        print("建议操作:")
        for suggestion in suggestions:
            print(f"  - {suggestion}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
