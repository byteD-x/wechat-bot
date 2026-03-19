"""
机器人生命周期管理器

提供机器人的启动、停止、暂停、恢复等生命周期管理功能。
使用单例模式确保全局唯一实例。
"""

import asyncio
import ctypes
import logging
import os
import sys
import time
from typing import Any, Dict, Optional, Set

from .core.config_service import get_config_service
from .growth_manager import get_growth_manager
from .shared_config import get_app_config_path
from .wechat_versions import OFFICIAL_SUPPORTED_WECHAT_VERSION

logger = logging.getLogger(__name__)


def _health_level_from_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "healthy":
        return "healthy"
    if normalized in {"degraded", "warning"}:
        return "warning"
    if normalized in {"error", "failed", "offline"}:
        return "error"
    return "warning"


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class BotManager:
    """
    机器人生命周期管理器（单例）

    负责管理 WeChatBot 实例的完整生命周期，包括：
    - 启动和停止
    - 暂停和恢复
    - 状态查询
    - 资源清理
    """

    _instance: Optional["BotManager"] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> "BotManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.bot = None  # WeChatBot 实例
        self.task: Optional[asyncio.Task] = None  # 运行任务
        self.stop_event = asyncio.Event()  # 停止信号

        # 事件广播
        self._event_queues: Set[asyncio.Queue] = set()

        # 状态
        self.is_running = False
        self.is_paused = False
        self.start_time: Optional[float] = None

        # 统计
        self.stats = {"today_replies": 0, "today_tokens": 0, "total_replies": 0}

        self._status_cache: Optional[Dict[str, Any]] = None
        self._status_cache_time: float = 0.0
        self._status_cache_ttl: float = 0.5
        self._stats_cache: Optional[Dict[str, Any]] = None
        self._stats_cache_time: float = 0.0
        self._stats_cache_ttl: float = 2.0
        self._startup_state: Dict[str, Any] = self._make_startup_state(
            stage="idle",
            message="机器人未启动",
            progress=0,
            active=False,
        )
        self._last_issue: Optional[Dict[str, Any]] = None
        self._last_status_log_snapshot: Optional[Dict[str, Any]] = None
        self._cpu_sample: Dict[str, float] = {
            "cpu_time": time.process_time(),
            "wall_time": time.perf_counter(),
            "cpu_percent": 0.0,
        }

        # 共享组件
        self.memory_manager = None
        self._growth_start_task: Optional[asyncio.Task] = None

        # 配置路径
        self.config_path = get_app_config_path()
        self.config_service = get_config_service()

        logger.info("BotManager 初始化完成")

    @classmethod
    def get_instance(cls) -> "BotManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_memory_manager(self):
        """获取或初始化共享记忆管理器"""
        if self.memory_manager is None:
            from backend.core.memory import MemoryManager

            bot_cfg = self.config_service.get_snapshot(
                config_path=self.config_path
            ).bot
            db_path = (
                bot_cfg.get("memory_db_path")
                or bot_cfg.get("sqlite_db_path")
                or "data/chat_memory.db"
            )
            self.memory_manager = MemoryManager(
                db_path,
                ttl_sec=bot_cfg.get("memory_ttl_sec"),
                cleanup_interval_sec=float(
                    bot_cfg.get("memory_cleanup_interval_sec", 0.0) or 0.0
                ),
            )
        return self.memory_manager

    async def start(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """
        启动机器人

        Args:
            config_path: 可选的配置文件路径，不提供则使用默认路径

        Returns:
            包含 success 和 message 的字典
        """
        async with self._lock:
            if self.is_running:
                return {"success": False, "message": "机器人已在运行"}

            try:
                from backend.bot import WeChatBot
                from backend.core.bot_control import get_bot_state

                # 使用提供的配置路径或默认路径
                path = config_path or self.config_path
                self.config_service.save_effective_config(
                    {"services": {"growth_tasks_enabled": True}},
                    config_path=path,
                    source="bot_start_enable_growth",
                )

                # 重置停止事件
                self.stop_event.clear()
                self.clear_issue()
                await self.update_startup_state(
                    "starting",
                    "正在创建机器人实例...",
                    8,
                    active=True,
                )
                state = get_bot_state()

                # 创建机器人实例
                self.bot = WeChatBot(path, memory_manager=self.get_memory_manager())

                # 注入停止事件（让 bot 可以检查是否需要停止）
                self.bot._stop_event = self.stop_event

                # 创建运行任务
                self.task = asyncio.create_task(self._run_bot())

                self.is_running = True
                self.is_paused = bool(state.is_paused)
                self.start_time = time.time()
                state.start_time = self.start_time
                state.save()
                self._invalidate_status_cache()
                await self.notify_status_change()
                self._schedule_growth_start()

                logger.info("机器人启动流程已开始")
                return {"success": True, "message": "机器人启动中，请稍候..."}

            except Exception as e:
                logger.error(f"机器人启动失败: {e}")
                self.is_running = False
                self.bot = None
                self.task = None
                self.set_issue(
                    code="bot_start_failed",
                    title="机器人启动失败",
                    detail=str(e),
                    suggestions=[
                        "检查当前 AI 预设是否可用。",
                        "确认微信 PC 已启动并保持登录。",
                        "如问题持续，请查看日志页中的错误明细。",
                    ],
                    recoverable=True,
                )
                self._startup_state = self._make_startup_state(
                    stage="failed",
                    message="启动失败",
                    progress=100,
                    active=False,
                )
                self._invalidate_status_cache()
                return {"success": False, "message": f"启动失败: {str(e)}"}

    def _schedule_growth_start(self) -> None:
        if self._growth_start_task and not self._growth_start_task.done():
            return
        self._growth_start_task = asyncio.create_task(
            self._start_growth_in_background()
        )
        self._growth_start_task.add_done_callback(self._on_growth_start_done)

    async def _start_growth_in_background(self) -> Dict[str, Any]:
        return await get_growth_manager().start(
            persist=False,
            source="bot_start",
        )

    def _on_growth_start_done(self, task: asyncio.Task) -> None:
        if self._growth_start_task is task:
            self._growth_start_task = None
        try:
            growth_result = task.result()
        except asyncio.CancelledError:
            logger.info("Growth task bootstrap cancelled")
            return
        except Exception:
            logger.exception("Growth task bootstrap failed unexpectedly")
            return

        if not growth_result.get("success"):
            logger.warning(
                "Growth task manager did not start with bot: %s",
                growth_result.get("message"),
            )

    async def _run_bot(self):
        """内部运行逻辑"""
        try:
            await self.bot.run()
        except asyncio.CancelledError:
            logger.info("机器人任务被取消")
        except Exception as e:
            logger.error(f"机器人运行错误: {e}")
            self.set_issue(
                code="bot_runtime_error",
                title="机器人运行异常",
                detail=str(e),
                suggestions=[
                    "检查微信连接状态与当前支持的版本。",
                    "检查 AI 服务是否可访问。",
                    "点击“一键恢复”后再次观察是否复现。",
                ],
                recoverable=True,
            )
        finally:
            self.is_running = False
            self.start_time = None
            if self._startup_state.get("active"):
                self._startup_state = self._make_startup_state(
                    stage="stopped",
                    message="机器人未运行",
                    progress=0,
                    active=False,
                )
            self._invalidate_status_cache()
            await self.notify_status_change()
            logger.info("机器人已停止")

    async def stop(self) -> Dict[str, Any]:
        """
        停止机器人

        Returns:
            包含 success 和 message 的字典
        """
        async with self._lock:
            if not self.is_running:
                return {"success": False, "message": "机器人未在运行"}

            try:
                # 设置停止信号
                self.stop_event.set()

                # 等待任务完成或超时后取消
                if self.task and not self.task.done():
                    try:
                        await asyncio.wait_for(self.task, timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning("等待停止超时，强制取消任务")
                        self.task.cancel()
                        try:
                            await self.task
                        except asyncio.CancelledError:
                            pass

                # 清理资源
                if self.bot:
                    if hasattr(self.bot, "shutdown"):
                        await self.bot.shutdown()
                    self.bot = None

                self.task = None
                self.is_running = False
                self.is_paused = False
                self.start_time = None
                self._startup_state = self._make_startup_state(
                    stage="stopped",
                    message="机器人已停止",
                    progress=0,
                    active=False,
                )
                self._invalidate_status_cache()
                await self.notify_status_change()

                logger.info("机器人停止成功")
                return {"success": True, "message": "机器人已停止"}

            except Exception as e:
                logger.error(f"停止机器人失败: {e}")
                return {"success": False, "message": f"停止失败: {str(e)}"}

    async def pause(self, reason: str = "用户暂停") -> Dict[str, Any]:
        """暂停机器人"""
        if not self.is_running:
            return {"success": False, "message": "机器人未在运行"}

        if self.is_paused:
            return {"success": False, "message": "机器人已暂停"}

        await self.apply_pause_state(True, reason=reason, propagate_to_bot=True)

        logger.info("机器人已暂停")
        return {"success": True, "message": "机器人已暂停"}

    async def resume(self) -> Dict[str, Any]:
        """恢复机器人"""
        if not self.is_running:
            return {"success": False, "message": "机器人未在运行"}

        if not self.is_paused:
            return {"success": False, "message": "机器人未暂停"}

        await self.apply_pause_state(False, propagate_to_bot=True)

        logger.info("机器人已恢复")
        return {"success": True, "message": "机器人已恢复"}

    async def restart(self) -> Dict[str, Any]:
        """重启机器人"""
        await self.stop()
        return await self.start()

    async def recover(self) -> Dict[str, Any]:
        """执行一键恢复。"""
        if self.is_running:
            return await self.restart()
        return await self.start()

    async def start_growth(self) -> Dict[str, Any]:
        return await get_growth_manager().start(source="api")

    async def stop_growth(self) -> Dict[str, Any]:
        return await get_growth_manager().stop(source="api")

    async def list_growth_tasks(self) -> Dict[str, Any]:
        return await get_growth_manager().list_growth_tasks()

    async def clear_growth_task(self, task_type: str) -> Dict[str, Any]:
        return await get_growth_manager().clear_growth_task(task_type)

    async def run_growth_task_now(self, task_type: str) -> Dict[str, Any]:
        return await get_growth_manager().run_growth_task_now(task_type)

    async def pause_growth_task(self, task_type: str) -> Dict[str, Any]:
        return await get_growth_manager().pause_growth_task(task_type)

    async def resume_growth_task(self, task_type: str) -> Dict[str, Any]:
        return await get_growth_manager().resume_growth_task(task_type)

    async def reload_runtime_config(
        self,
        *,
        new_config: Optional[Dict[str, Any]] = None,
        changed_paths: Optional[list[str]] = None,
        force_ai_reload: bool = False,
        strict_active_preset: bool = False,
    ) -> Dict[str, Any]:
        """
        立即将最新配置应用到运行中的机器人。
        """
        if not self.is_running or not self.bot:
            return {
                "success": False,
                "message": "机器人未运行，无法立即切换",
                "skipped": True,
            }

        if not hasattr(self.bot, "reload_runtime_config"):
            return {
                "success": False,
                "message": "当前机器人实例不支持立即重载",
                "skipped": True,
            }

        return await self.bot.reload_runtime_config(
            new_config=new_config,
            changed_paths=changed_paths,
            force_ai_reload=force_ai_reload,
            strict_active_preset=strict_active_preset,
        )

    async def send_message(self, target: str, content: str) -> Dict[str, Any]:
        """
        发送消息

        Args:
           target: 目标
           content: 内容
        """
        if not self.is_running or not self.bot:
            return {"success": False, "message": "机器人未运行"}

        if self.is_paused:
            return {"success": False, "message": "机器人已暂停"}

        if hasattr(self.bot, "send_text_message"):
            return await self.bot.send_text_message(target, content)

        return {"success": False, "message": "机器人实例不支持发送消息"}

    def get_usage(self) -> Dict[str, Any]:
        """获取使用统计"""
        return self._get_stats()

    def _get_stats(self) -> Dict[str, Any]:
        now = time.time()
        if self._stats_cache and (now - self._stats_cache_time) < self._stats_cache_ttl:
            return dict(self._stats_cache)

        stats = self.stats.copy()
        try:
            from backend.core.bot_control import get_bot_state

            state = get_bot_state()
            stats.update(
                {
                    "today_replies": state.today_replies,
                    "today_tokens": state.today_tokens,
                    "total_replies": state.total_replies,
                    "total_tokens": state.total_tokens,
                }
            )
        except Exception:
            pass
        if self.bot and hasattr(self.bot, "get_stats"):
            try:
                bot_stats = self.bot.get_stats()
                if bot_stats:
                    stats.update(bot_stats)
            except Exception:
                pass

        self._stats_cache = stats
        self._stats_cache_time = now
        return dict(stats)

    def get_status(self) -> Dict[str, Any]:
        """
        获取机器人状态

        Returns:
            状态信息字典
        """
        now = time.time()
        if (
            self._status_cache
            and (now - self._status_cache_time) < self._status_cache_ttl
        ):
            return dict(self._status_cache)

        uptime = "--"
        if self.is_running and self.start_time:
            elapsed = int(time.time() - self.start_time)
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # 尝试从 bot 获取统计数据
        stats = self._get_stats()

        status = {
            "service_running": True,
            "running": self.is_running,
            "bot_running": self.is_running,
            "is_paused": self.is_paused,
            "uptime": uptime,
            "today_replies": stats.get("today_replies", 0),
            "today_tokens": stats.get("today_tokens", 0),
            "total_replies": stats.get("total_replies", 0),
            "total_tokens": stats.get("total_tokens", 0),
            "engine": "langgraph",
            "startup": dict(self._startup_state),
        }
        try:
            snapshot = self.config_service.get_snapshot(config_path=self.config_path)
            loaded_at = getattr(snapshot, "loaded_at", None)
            if hasattr(loaded_at, "isoformat"):
                loaded_at_value = loaded_at.isoformat()
            elif loaded_at:
                loaded_at_value = float(loaded_at)
            else:
                loaded_at_value = None
            status["config_snapshot"] = {
                "version": int(getattr(snapshot, "version", 0) or 0),
                "loaded_at": loaded_at_value,
                "source": str(getattr(snapshot, "source", "") or ""),
                "valid": bool(getattr(snapshot, "valid", True)),
            }
            status["growth_enabled"] = bool(snapshot.services.get("growth_tasks_enabled", False))
        except Exception:
            status["config_snapshot"] = None
            status["growth_enabled"] = False
        if self.bot and hasattr(self.bot, "get_export_rag_status"):
            try:
                status["export_rag"] = self.bot.get_export_rag_status()
            except Exception:
                status["export_rag"] = None
        else:
            try:
                bot_cfg = self.config_service.get_snapshot(
                    config_path=self.config_path
                ).bot
                status["export_rag"] = {
                    "enabled": bool(bot_cfg.get("export_rag_enabled", False)),
                    "base_dir": str(bot_cfg.get("export_rag_dir") or ""),
                    "auto_ingest": bool(bot_cfg.get("export_rag_auto_ingest", True)),
                    "indexed_contacts": 0,
                    "indexed_chunks": 0,
                    "last_scan_at": None,
                    "last_scan_summary": {},
                }
            except Exception:
                status["export_rag"] = None
        if self.bot and hasattr(self.bot, "get_agent_status"):
            try:
                status.update(self.bot.get_agent_status())
            except Exception:
                pass
        try:
            status.update(get_growth_manager().get_status())
        except Exception:
            pass
        if self.bot and hasattr(self.bot, "get_transport_status"):
            try:
                status.update(self.bot.get_transport_status())
            except Exception:
                pass
        if self.bot and hasattr(self.bot, "get_runtime_status"):
            try:
                status.update(self.bot.get_runtime_status())
            except Exception:
                pass
        status["system_metrics"] = self._collect_system_metrics(status)
        status["health_checks"] = self._build_health_checks(status)
        status["diagnostics"] = self._build_diagnostics(status)
        self._status_cache = status
        self._status_cache_time = now
        return dict(status)

    def _invalidate_status_cache(self) -> None:
        self._status_cache = None
        self._status_cache_time = 0.0
        self._stats_cache = None
        self._stats_cache_time = 0.0

    async def apply_pause_state(
        self,
        paused: bool,
        *,
        reason: str = "",
        propagate_to_bot: bool = False,
    ) -> None:
        from backend.core.bot_control import get_bot_state

        state = get_bot_state()
        state.set_paused(paused, reason if paused else "")
        self.is_paused = paused
        if propagate_to_bot and self.bot:
            if paused and hasattr(self.bot, "pause"):
                self.bot.pause()
            elif not paused and hasattr(self.bot, "resume"):
                self.bot.resume()
        self._invalidate_status_cache()
        await self.notify_status_change()

    async def notify_status_change(self) -> None:
        status = self.get_status()
        self._log_status_change(status)
        await self.broadcast_event("status_change", status)

    def _log_status_change(self, status: Dict[str, Any]) -> None:
        snapshot = self._build_status_log_snapshot(status)
        if snapshot == self._last_status_log_snapshot:
            return

        self._last_status_log_snapshot = snapshot
        summary = self._build_status_log_message(status)
        level = self._get_status_log_level(status)
        if level == "warning":
            logger.warning("状态更新: %s", summary)
        else:
            logger.info("状态更新: %s", summary)

    def _build_status_log_snapshot(self, status: Dict[str, Any]) -> Dict[str, Any]:
        startup = status.get("startup") or {}
        health_checks = status.get("health_checks") or {}
        ai = health_checks.get("ai") or {}
        wechat = health_checks.get("wechat") or {}
        diagnostics = status.get("diagnostics") or {}
        return {
            "running": bool(status.get("running")),
            "is_paused": bool(status.get("is_paused")),
            "startup_active": bool(startup.get("active")),
            "startup_stage": str(startup.get("stage") or ""),
            "startup_message": str(startup.get("message") or ""),
            "startup_progress": int(startup.get("progress", 0) or 0),
            "transport_status": str(status.get("transport_status") or ""),
            "transport_warning": str(status.get("transport_warning") or ""),
            "ai_status": str(ai.get("status") or ""),
            "ai_message": str(ai.get("message") or ""),
            "wechat_status": str(wechat.get("status") or ""),
            "wechat_message": str(wechat.get("message") or ""),
            "runtime_preset": str(status.get("runtime_preset") or ""),
            "model": str(status.get("model") or ""),
            "diagnostic_level": str(diagnostics.get("level") or ""),
            "diagnostic_title": str(diagnostics.get("title") or ""),
            "diagnostic_detail": str(diagnostics.get("detail") or ""),
        }

    def _build_status_log_message(self, status: Dict[str, Any]) -> str:
        startup = status.get("startup") or {}
        health_checks = status.get("health_checks") or {}
        ai = health_checks.get("ai") or {}
        wechat = health_checks.get("wechat") or {}
        diagnostics = status.get("diagnostics") or {}

        parts = []
        if bool(startup.get("active")):
            progress = int(startup.get("progress", 0) or 0)
            message = str(startup.get("message") or "").strip() or "正在启动"
            parts.append(f"启动中 {progress}%")
            parts.append(message)
        else:
            if not bool(status.get("running")):
                parts.append("机器人未运行")
            elif bool(status.get("is_paused")):
                parts.append("机器人已暂停")
            else:
                parts.append("机器人运行中")
            uptime = str(status.get("uptime") or "").strip()
            if uptime and uptime != "--":
                parts.append(f"已运行 {uptime}")

        wechat_status = str(status.get("transport_status") or wechat.get("status") or "").strip().lower()
        wechat_message = str(status.get("transport_warning") or wechat.get("message") or "").strip()
        if wechat_status == "connected":
            parts.append("微信已连接")
        elif wechat_status in {"connecting", "warning", "degraded"}:
            parts.append("微信连接中" if not wechat_message else f"微信提示：{wechat_message}")
        elif wechat_status in {"disconnected", "error", "offline"}:
            parts.append("微信未连接" if not wechat_message else f"微信异常：{wechat_message}")

        runtime_label = str(status.get("runtime_preset") or status.get("model") or "").strip()
        ai_status = str(ai.get("status") or "").strip().lower()
        ai_message = str(ai.get("message") or "").strip()
        if ai_status == "healthy":
            parts.append(f"AI可用：{runtime_label}" if runtime_label else "AI可用")
        elif ai_status:
            detail = ai_message or runtime_label or "请检查 AI 连接"
            parts.append(f"AI状态：{detail}")

        diagnostic_title = str(diagnostics.get("title") or "").strip()
        diagnostic_detail = str(diagnostics.get("detail") or "").strip()
        if diagnostic_title:
            parts.append(f"诊断：{diagnostic_title}")
            if diagnostic_detail:
                compact = " ".join(diagnostic_detail.split())
                if len(compact) > 80:
                    compact = f"{compact[:80]}..."
                parts.append(compact)

        return " | ".join(part for part in parts if part)

    @staticmethod
    def _get_status_log_level(status: Dict[str, Any]) -> str:
        diagnostics = status.get("diagnostics") or {}
        if str(diagnostics.get("level") or "").strip().lower() in {"warning", "error"}:
            return "warning"

        health_checks = status.get("health_checks") or {}
        for component in ("wechat", "ai", "database"):
            item = health_checks.get(component) or {}
            normalized = str(item.get("status") or "").strip().lower()
            if normalized in {"warning", "degraded", "error", "failed", "offline"}:
                return "warning"
        return "info"

    async def update_startup_state(
        self,
        stage: str,
        message: str,
        progress: int,
        *,
        active: bool,
    ) -> None:
        next_state = self._make_startup_state(
            stage=stage,
            message=message,
            progress=progress,
            active=active,
        )
        prev_state = self._startup_state or {}
        if (
            str(prev_state.get("stage") or "") == str(next_state.get("stage") or "")
            and str(prev_state.get("message") or "")
            == str(next_state.get("message") or "")
            and int(prev_state.get("progress", 0) or 0)
            == int(next_state.get("progress", 0) or 0)
            and bool(prev_state.get("active")) == bool(next_state.get("active"))
        ):
            return

        self._startup_state = next_state
        self._invalidate_status_cache()
        await self.notify_status_change()

    def set_issue(
        self,
        *,
        code: str,
        title: str,
        detail: str = "",
        suggestions: Optional[list[str]] = None,
        recoverable: bool = True,
        level: str = "error",
    ) -> None:
        self._last_issue = {
            "level": level,
            "code": code,
            "title": title,
            "detail": detail,
            "suggestions": list(suggestions or []),
            "recoverable": recoverable,
            "updated_at": time.time(),
            "action_label": "一键恢复" if recoverable else "",
        }
        self._startup_state = self._make_startup_state(
            stage="failed",
            message=title,
            progress=100,
            active=False,
        )
        self._invalidate_status_cache()

    def clear_issue(self) -> None:
        self._last_issue = None
        self._invalidate_status_cache()

    @staticmethod
    def _make_startup_state(
        *,
        stage: str,
        message: str,
        progress: int,
        active: bool,
    ) -> Dict[str, Any]:
        return {
            "stage": str(stage or "idle"),
            "message": str(message or ""),
            "progress": max(0, min(int(progress or 0), 100)),
            "active": bool(active),
            "updated_at": time.time(),
        }

    def _build_diagnostics(self, status: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self._last_issue:
            return dict(self._last_issue)

        startup = status.get("startup") or {}
        if bool(startup.get("active")):
            # 启动中：使用 startup 面板展示进度即可，避免把“尚未连接”误报为“已断开/失败”。
            return None

        transport_status = str(status.get("transport_status") or "").strip().lower()
        transport_warning = str(status.get("transport_warning") or "").strip()
        if self.is_running and transport_status == "disconnected":
            return {
                "level": "error",
                "code": "wechat_disconnected",
                "title": "微信连接已断开",
                "detail": "机器人正在运行，但当前未检测到有效的微信连接。",
                "suggestions": [
                    "确认微信 PC 客户端已启动且保持登录。",
                    f"确认当前微信版本为 {OFFICIAL_SUPPORTED_WECHAT_VERSION}。",
                    "点击“一键恢复”重新建立连接。",
                ],
                "recoverable": True,
                "updated_at": time.time(),
                "action_label": "一键恢复",
            }
        if transport_warning:
            return {
                "level": "warning",
                "code": "transport_warning",
                "title": "运行环境存在兼容性提示",
                "detail": transport_warning,
                "suggestions": [
                    f"优先检查当前微信版本是否为 {OFFICIAL_SUPPORTED_WECHAT_VERSION}。",
                    "如消息发送或引用异常，可先执行重启恢复。",
                ],
                "recoverable": True,
                "updated_at": time.time(),
                "action_label": "一键恢复",
            }
        return None

    def _collect_system_metrics(self, status: Dict[str, Any]) -> Dict[str, Any]:
        process_memory_mb = self._get_process_memory_mb()
        memory = self._get_system_memory_snapshot()
        cpu_percent = self._sample_process_cpu_percent()
        queue_messages = int(status.get("merge_pending_messages", 0) or 0)
        queue_chats = int(status.get("merge_pending_chats", 0) or 0)
        pending_tasks = int(status.get("pending_tasks", 0) or 0)
        runtime_timings = status.get("runtime_timings") or {}
        ai_latency_sec = (
            runtime_timings.get("stream_sec")
            or runtime_timings.get("invoke_sec")
            or runtime_timings.get("prepare_total_sec")
            or 0.0
        )
        warning = ""
        if cpu_percent >= 80:
            warning = "CPU 占用偏高"
        elif memory.get("percent", 0) >= 85:
            warning = "内存占用偏高"
        elif queue_messages >= 10 or pending_tasks >= 20:
            warning = "消息队列积压"

        return {
            "cpu_percent": cpu_percent,
            "process_memory_mb": process_memory_mb,
            "system_memory_percent": memory.get("percent", 0.0),
            "system_memory_used_mb": memory.get("used_mb", 0.0),
            "system_memory_total_mb": memory.get("total_mb", 0.0),
            "pending_tasks": pending_tasks,
            "merge_pending_chats": queue_chats,
            "merge_pending_messages": queue_messages,
            "ai_latency_ms": round(float(ai_latency_sec or 0.0) * 1000, 1),
            "warning": warning,
        }

    def _build_health_checks(self, status: Dict[str, Any]) -> Dict[str, Any]:
        ai_ready = bool(self.bot and getattr(self.bot, "ai_client", None))
        ai_health = status.get("ai_health") or {}
        ai_status = str(ai_health.get("status") or "").strip().lower()
        ai_detail = str(ai_health.get("detail") or "").strip()

        if ai_status not in {"healthy", "warning", "degraded", "error"}:
            if ai_ready:
                ai_status = "healthy"
            elif self.is_running:
                ai_status = "degraded"
            else:
                ai_status = "unknown"

        if not ai_detail:
            if ai_ready and status.get("model"):
                ai_detail = f"AI client ready: {status.get('model')}"
            elif ai_ready:
                ai_detail = "AI client initialized, awaiting first runtime check"
            elif self.is_running:
                ai_detail = "Bot is running, but AI client is unavailable"
            else:
                ai_detail = "Bot not running, AI has not been checked yet"

        transport_status = str(status.get("transport_status") or "").strip().lower()
        transport_warning = str(status.get("transport_warning") or "").strip()
        startup = status.get("startup") or {}
        startup_active = bool(startup.get("active"))
        startup_stage = str(startup.get("stage") or "").strip().lower()
        if transport_status == "connected":
            wechat_status = "healthy"
            wechat_detail = "Verified active WeChat connection"
            if transport_warning:
                wechat_detail = f"{wechat_detail}; {transport_warning}"
        elif self.is_running and startup_active:
            wechat_status = "warning"
            if startup_stage == "connect_wechat":
                wechat_detail = "正在连接微信客户端..."
            else:
                wechat_detail = "机器人启动中，微信连接尚未就绪"
            if transport_warning:
                wechat_detail = f"{wechat_detail}；{transport_warning}"
        elif self.is_running:
            wechat_status = "error"
            wechat_detail = (
                transport_warning
                or "Bot is running, but no active WeChat connection was detected"
            )
        else:
            wechat_status = "warning"
            wechat_detail = (
                transport_warning
                or "Bot is stopped, so WeChat connection is not active"
            )

        db_status = "warning"
        db_detail = "Database connection has not been initialized"
        memory_manager = None
        if self.bot and hasattr(self.bot, "memory"):
            memory_manager = getattr(self.bot, "memory", None)
        elif self.memory_manager is not None:
            memory_manager = self.memory_manager
        if memory_manager is not None:
            db_path = str(getattr(memory_manager, "db_path", "") or "")
            has_connection = getattr(memory_manager, "_conn", None) is not None
            if has_connection:
                db_status = "healthy"
                db_detail = db_path or "Verified active SQLite connection"
            elif db_path:
                db_detail = (
                    f"Database path configured, but no active connection: {db_path}"
                )

        checks = {
            "ai": {
                "status": ai_status,
                "detail": ai_detail,
            },
            "wechat": {
                "status": wechat_status,
                "detail": wechat_detail,
            },
            "database": {
                "status": db_status,
                "detail": db_detail,
            },
        }
        for item in checks.values():
            item["level"] = _health_level_from_status(item.get("status", ""))
            item["message"] = item.get("detail", "")
        return checks

    def export_metrics(self) -> str:
        status = self.get_status()
        metrics = status.get("system_metrics") or {}
        health_checks = status.get("health_checks") or {}
        startup = status.get("startup") or {}
        config_reload = status.get("config_reload") or {}

        lines = [
            "# HELP wechat_bot_running Whether the bot is running.",
            "# TYPE wechat_bot_running gauge",
            f"wechat_bot_running {1 if status.get('running') else 0}",
            "# HELP wechat_bot_paused Whether the bot is paused.",
            "# TYPE wechat_bot_paused gauge",
            f"wechat_bot_paused {1 if status.get('is_paused') else 0}",
            "# HELP wechat_bot_today_replies Replies sent today.",
            "# TYPE wechat_bot_today_replies gauge",
            f"wechat_bot_today_replies {int(status.get('today_replies', 0) or 0)}",
            "# HELP wechat_bot_today_tokens Tokens used today.",
            "# TYPE wechat_bot_today_tokens gauge",
            f"wechat_bot_today_tokens {int(status.get('today_tokens', 0) or 0)}",
            "# HELP wechat_bot_total_replies Total replies sent.",
            "# TYPE wechat_bot_total_replies counter",
            f"wechat_bot_total_replies {int(status.get('total_replies', 0) or 0)}",
            "# HELP wechat_bot_total_tokens Total tokens used.",
            "# TYPE wechat_bot_total_tokens counter",
            f"wechat_bot_total_tokens {int(status.get('total_tokens', 0) or 0)}",
            "# HELP wechat_bot_cpu_percent Process CPU usage percent.",
            "# TYPE wechat_bot_cpu_percent gauge",
            f"wechat_bot_cpu_percent {float(metrics.get('cpu_percent', 0.0) or 0.0)}",
            "# HELP wechat_bot_process_memory_mb Process working set memory in MB.",
            "# TYPE wechat_bot_process_memory_mb gauge",
            f"wechat_bot_process_memory_mb {float(metrics.get('process_memory_mb', 0.0) or 0.0)}",
            "# HELP wechat_bot_system_memory_percent System memory usage percent.",
            "# TYPE wechat_bot_system_memory_percent gauge",
            f"wechat_bot_system_memory_percent {float(metrics.get('system_memory_percent', 0.0) or 0.0)}",
            "# HELP wechat_bot_pending_tasks Pending asyncio tasks.",
            "# TYPE wechat_bot_pending_tasks gauge",
            f"wechat_bot_pending_tasks {int(metrics.get('pending_tasks', 0) or 0)}",
            "# HELP wechat_bot_merge_pending_chats Chats waiting for merged replies.",
            "# TYPE wechat_bot_merge_pending_chats gauge",
            f"wechat_bot_merge_pending_chats {int(metrics.get('merge_pending_chats', 0) or 0)}",
            "# HELP wechat_bot_merge_pending_messages Messages waiting for merged replies.",
            "# TYPE wechat_bot_merge_pending_messages gauge",
            f"wechat_bot_merge_pending_messages {int(metrics.get('merge_pending_messages', 0) or 0)}",
            "# HELP wechat_bot_ai_latency_ms Latest AI latency in milliseconds.",
            "# TYPE wechat_bot_ai_latency_ms gauge",
            f"wechat_bot_ai_latency_ms {float(metrics.get('ai_latency_ms', 0.0) or 0.0)}",
            "# HELP wechat_bot_startup_progress Startup progress percent.",
            "# TYPE wechat_bot_startup_progress gauge",
            f"wechat_bot_startup_progress {int(startup.get('progress', 0) or 0)}",
            "# HELP wechat_bot_config_reload_mode Active config reload mode.",
            "# TYPE wechat_bot_config_reload_mode gauge",
            f'wechat_bot_config_reload_mode{{mode="{config_reload.get("mode", "unknown")}"}} 1',
            "# HELP wechat_bot_health_check Component health state.",
            "# TYPE wechat_bot_health_check gauge",
        ]

        for component, check in health_checks.items():
            status_label = str(check.get("status") or "unknown").lower()
            lines.append(
                f'wechat_bot_health_check{{component="{component}",status="{status_label}"}} 1'
            )
        return "\n".join(lines) + "\n"

    def _sample_process_cpu_percent(self) -> float:
        now_cpu = time.process_time()
        now_wall = time.perf_counter()
        last_cpu = self._cpu_sample.get("cpu_time", now_cpu)
        last_wall = self._cpu_sample.get("wall_time", now_wall)
        delta_wall = max(now_wall - last_wall, 1e-6)
        delta_cpu = max(now_cpu - last_cpu, 0.0)
        cpu_percent = round(min(100.0, max(0.0, (delta_cpu / delta_wall) * 100.0)), 1)
        self._cpu_sample = {
            "cpu_time": now_cpu,
            "wall_time": now_wall,
            "cpu_percent": cpu_percent,
        }
        return cpu_percent

    def _get_process_memory_mb(self) -> float:
        if sys.platform.startswith("win"):
            try:
                counters = _ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
                process = ctypes.windll.kernel32.GetCurrentProcess()
                ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                    process,
                    ctypes.byref(counters),
                    counters.cb,
                )
                if ok:
                    return round(counters.WorkingSetSize / (1024 * 1024), 1)
            except Exception:
                pass
        return 0.0

    def _get_system_memory_snapshot(self) -> Dict[str, float]:
        if sys.platform.startswith("win"):
            try:
                status = _MemoryStatusEx()
                status.dwLength = ctypes.sizeof(_MemoryStatusEx)
                ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
                if ok:
                    used = max(0, status.ullTotalPhys - status.ullAvailPhys)
                    return {
                        "percent": round(float(status.dwMemoryLoad), 1),
                        "used_mb": round(used / (1024 * 1024), 1),
                        "total_mb": round(status.ullTotalPhys / (1024 * 1024), 1),
                    }
            except Exception:
                pass
        return {"percent": 0.0, "used_mb": 0.0, "total_mb": 0.0}

    async def broadcast_event(self, event_type: str, data: Any) -> None:
        """
        广播事件到所有监听者

        Args:
            event_type: 事件类型 (e.g., 'message', 'status_change')
            data: 事件数据
        """
        if not self._event_queues:
            return

        payload = {
            "type": event_type,
            "data": data,
            "timestamp": asyncio.get_running_loop().time(),
        }

        # Avoid disconnecting slow SSE clients: when a queue is full, drop the
        # oldest event and keep pushing the latest one.
        closed = []
        # Iterate over a snapshot to avoid edge-case "set changed size during iteration"
        # if a client disconnects while we are broadcasting.
        for q in tuple(self._event_queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()  # Drop oldest
                    q.put_nowait(payload)
                except Exception:
                    # Still full or broken; drop this event for this queue.
                    pass
            except Exception:
                closed.append(q)

        for q in closed:
            self._event_queues.discard(q)

    async def event_generator(self):
        """
        SSE 事件生成器
        """
        queue = asyncio.Queue(maxsize=100)
        self._event_queues.add(queue)

        import json

        loop = asyncio.get_running_loop()
        heartbeat_interval_sec = 15.0

        try:
            # Send an initial status payload so the UI can render immediately without
            # waiting for the first polling round-trip.
            try:
                initial = {
                    "type": "status_change",
                    "data": self.get_status(),
                    "timestamp": loop.time(),
                }
                yield f"data: {json.dumps(initial, ensure_ascii=False)}\n\n"
            except Exception:
                # Status is best-effort; keep SSE alive even if status building fails.
                pass

            while True:
                # Wait for the next event, but emit a small heartbeat periodically to
                # keep the EventSource connection alive (some proxies/timeouts are aggressive).
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=heartbeat_interval_sec
                    )
                except asyncio.TimeoutError:
                    event = {
                        "type": "heartbeat",
                        "data": None,
                        "timestamp": loop.time(),
                    }

                # SSE 格式: data: <json>\n\n
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self._event_queues.discard(queue)


# 便捷访问函数
def get_bot_manager() -> BotManager:
    """获取 BotManager 实例"""
    return BotManager.get_instance()
