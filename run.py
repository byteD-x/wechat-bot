#!/usr/bin/env python3
"""
微信 AI 机器人统一启动入口。

使用方式:
    python run.py           # 启动机器人（默认）
    python run.py start     # 启动机器人
    python run.py setup     # 运行配置向导
    python run.py check     # 环境检测
    python run.py web       # 启动 Web 控制面板

更多帮助:
    python run.py --help
    python run.py <command> --help
"""

import sys
import os

from backend.utils.runtime_artifacts import (
    configure_runtime_environment,
    relocate_known_root_artifacts,
)

# 避免已知的后台线程异常（例如 wcferry 本地消息通道连接失败）直接打印完整 traceback 并污染 stderr。
# 这类异常通常是运行环境未就绪（微信未启动/未登录/注入失败）导致，应该以可读提示展示。
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
                            "[wcferry] Connection refused: 请确认微信已启动并登录，且 wcferry 注入/服务正常运行。\n"
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

# 强制使用 UTF-8 编码（解决 Windows 控制台乱码问题）
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.dont_write_bytecode = True

_install_thread_exception_filter()
configure_runtime_environment()
relocate_known_root_artifacts()

import argparse

from backend.core.config_cli import build_config_parser


def print_banner():
    """打印启动横幅"""
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║            🤖 微信 AI 机器人 - 统一管理入口                  ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def cmd_start(args):
    """启动机器人核心"""
    print_banner()
    print("🚀 正在启动机器人...")
    print()

    # Lazy import 避免不必要的依赖加载
    import asyncio
    from backend.main import main

    asyncio.run(main())


def cmd_setup(args):
    """运行配置向导"""
    from scripts.setup_wizard import main

    main()


def cmd_check(args):
    """运行环境检测"""
    from scripts.check import main

    sys.exit(main())


def cmd_web(args):
    """启动 Web API 服务"""
    print_banner()

    host = args.host if hasattr(args, "host") else "127.0.0.1"
    port = args.port if hasattr(args, "port") else 5000

    debug = args.debug if hasattr(args, "debug") else False

    token = os.environ.get("WECHAT_BOT_API_TOKEN", "").strip()
    if not token:
        try:
            import secrets

            token = secrets.token_hex(24)
        except Exception:
            token = ""
        if token:
            os.environ["WECHAT_BOT_API_TOKEN"] = token

    print("🌐 启动 API 服务...")
    print(f"📍 访问地址: http://{host}:{port}")
    if token:
        # 安全：不要在控制台输出 token，避免被日志/截图意外泄露。
        print("🔐 本机访问 Token: 已设置（为安全起见不显示）")
    if debug:
        print("🔧 调试模式: 已开启 (热重载)")
    print("按 Ctrl+C 停止服务\n")

    from backend.api import run_server

    run_server(host=host, port=port, debug=debug)


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="微信 AI 机器人统一管理入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python run.py           启动机器人（默认）
  python run.py setup     首次配置
  python run.py check     检测环境
  python run.py web       启动 Web 面板

更多信息请参阅 README.md
""",
    )

    subparsers = parser.add_subparsers(
        title="可用命令",
        dest="command",
        metavar="<command>",
    )

    # start 子命令
    parser_start = subparsers.add_parser(
        "start",
        help="启动机器人（默认命令）",
        description="启动微信 AI 自动回复机器人核心程序",
    )
    parser_start.set_defaults(func=cmd_start)

    # setup 子命令
    parser_setup = subparsers.add_parser(
        "setup",
        help="运行配置向导",
        description="交互式配置向导，用于首次设置 API 密钥",
    )
    parser_setup.set_defaults(func=cmd_setup)

    # check 子命令
    parser_check = subparsers.add_parser(
        "check",
        help="环境检测",
        description="检测 Python 版本、依赖安装、API 配置、微信连接等",
    )
    parser_check.set_defaults(func=cmd_check)

    # web 子命令
    parser_web = subparsers.add_parser(
        "web",
        help="启动 Web 控制面板",
        description="启动 Web 状态面板，可查看/控制机器人状态",
    )
    parser_web.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址（默认 127.0.0.1，仅本机访问）",
    )
    parser_web.add_argument(
        "--port",
        "-p",
        type=int,
        default=5000,
        help="监听端口（默认 5000）",
    )
    parser_web.add_argument(
        "--debug",
        action="store_true",
        help="开启调试模式（启用热重载）",
    )
    parser_web.set_defaults(func=cmd_web)
    build_config_parser(subparsers)

    # 解析参数
    args = parser.parse_args()

    # 如果没有指定命令，默认启动机器人
    if args.command is None:
        args.func = cmd_start

    # 执行对应命令
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n\n👋 已退出")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
