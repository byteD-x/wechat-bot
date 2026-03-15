import asyncio
import inspect
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Set

from .core.export_rag import ExportChatRAG
from .core.memory import MemoryManager
from .core.vector_memory import VectorMemory
from .core.bot_control import (
    parse_control_command,
    is_command_message,
    should_respond,
    get_bot_state,
)
from .core.factory import (
    select_ai_client,
    select_specific_ai_client,
    get_reconnect_policy,
    get_last_transport_error,
    reconnect_wechat,
    compute_api_signature,
)

from .types import MessageEvent
from .handlers.filter import should_reply
from .handlers.sender import send_message, send_reply_chunks
from .handlers.converters import normalize_new_messages
from .utils.common import as_float, as_int, get_file_mtime, iter_items
from .utils.config import load_config, get_model_alias
from .utils.logging import (
    setup_logging,
    get_logging_settings,
    get_log_behavior,
    format_log_text,
)
from .utils.config_watcher import ConfigReloadWatcher
from .utils.message import (
    is_voice_message,
    is_image_message,
    build_reply_suffix,
    refine_reply_text,
    sanitize_reply_text,
    split_reply_naturally,
)
from .utils.tools import transcribe_voice_message, estimate_exchange_tokens
from .utils.ipc import IPCManager


from .bot_manager import get_bot_manager
from .wechat_versions import OFFICIAL_SUPPORTED_WECHAT_VERSION

class WeChatBot:
    def __init__(self, config_path: str, memory_manager: Optional[MemoryManager] = None):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.bot_cfg: Dict[str, Any] = {}
        self.api_cfg: Dict[str, Any] = {}
        self.agent_cfg: Dict[str, Any] = {}
        self.ai_client: Optional[Any] = None
        self.wx: Optional[Any] = None
        self.memory: Optional[MemoryManager] = memory_manager
        self.vector_memory: Optional[VectorMemory] = None
        self.export_rag: Optional[ExportChatRAG] = None
        self.export_rag_sync_task: Optional[asyncio.Task] = None
        self.wx_lock = asyncio.Lock()
        self.sem: Optional[asyncio.Semaphore] = None
        self.ipc = IPCManager()  # IPC 管理器
        self.bot_manager = get_bot_manager() # 获取 BotManager 实例以广播事件

        self.last_reply_ts: Dict[str, float] = {"ts": 0.0}
        self.pending_tasks: Set[asyncio.Task] = set()
        self.chat_locks: Dict[str, asyncio.Lock] = {}
        
        # 合并消息状态
        self.pending_merge_messages: Dict[str, List[str]] = {}
        self.pending_merge_events: Dict[str, MessageEvent] = {}
        self.pending_merge_first_event: Dict[str, MessageEvent] = {}
        self.pending_merge_tasks: Dict[str, asyncio.Task] = {}
        self.pending_merge_first_ts: Dict[str, float] = {}
        self.pending_merge_lock = asyncio.Lock()

        # 配置监控
        self.config_mtime: Optional[float] = None
        self.override_path = os.path.abspath(
            os.path.join("data", "config_override.json")
        )
        self.override_mtime: Optional[float] = None
        self.config_reload_watcher: Optional[ConfigReloadWatcher] = None
        self.ai_module_mtime: Optional[float] = None
        self.api_signature: str = ""
        self.runtime_preset_name: str = ""
        self.ai_health: Dict[str, Any] = {
            "status": "unknown",
            "detail": "AI not initialized",
            "checked_at": None,
            "last_success_at": None,
            "last_error_at": None,
            "last_error": "",
        }
        
        # 日志标志
        self.log_message_content: bool = True
        self.log_reply_content: bool = True
        
        # 停止事件（由 BotManager 注入或自行创建）
        self._stop_event: Optional[asyncio.Event] = None
        self._is_paused: bool = False
        self._wx_supports_filter_mute: Optional[bool] = None
        self.max_pending_tasks = 100

        # 缓存的过滤配置
        self.ignore_names_set: Set[str] = set()
        self.ignore_keywords_list: List[str] = []

    async def initialize(self) -> Optional["WeChat"]:
        try:
            await self.bot_manager.update_startup_state(
                "loading_config",
                "正在加载配置...",
                15,
                active=True,
            )
            self.config_mtime = get_file_mtime(self.config_path)
            self.override_mtime = get_file_mtime(self.override_path)
            self.config = load_config(self.config_path)
        except Exception as exc:
            logging.error("无法加载配置文件: %s", exc)
            self._set_ai_health("error", "No available AI preset", error=True)
            self.bot_manager.set_issue(
                code="config_load_failed",
                title="配置加载失败",
                detail=str(exc),
                suggestions=[
                    "检查 backend/config.py 或覆盖配置文件是否存在语法错误。",
                    "确认配置项中的路径和数值格式正确。",
                ],
                recoverable=False,
            )
            return None

        self._apply_config()
        self._ensure_config_reload_watcher()
        
        # 初始化记忆模块
        await self.bot_manager.update_startup_state(
            "init_memory",
            "正在初始化本地记忆库...",
            28,
            active=True,
        )
        if self.memory is None:
            db_path = self.bot_cfg.get("memory_db_path") or self.bot_cfg.get("sqlite_db_path") or "data/chat_memory.db"
            self.memory = MemoryManager(db_path)
        initialize_memory = getattr(self.memory, "initialize", None)
        if callable(initialize_memory):
            maybe_result = initialize_memory()
            if inspect.isawaitable(maybe_result):
                await maybe_result

        self._ensure_vector_memory()
        
        # 初始化 AI 客户端
        await self.bot_manager.update_startup_state(
            "init_ai",
            "正在初始化 AI 客户端...",
            55,
            active=True,
        )
        self._set_ai_health("unknown", "Checking AI preset availability")
        self.ai_client, preset_name = await select_ai_client(
            self.api_cfg, self.bot_cfg, self.agent_cfg
        )
        if self.ai_client:
            self.api_signature = compute_api_signature(
                {"api": self.api_cfg, "agent": self.agent_cfg}
            )
            self.runtime_preset_name = preset_name or ""
            self._set_ai_health(
                "healthy",
                f"AI preset {self.runtime_preset_name or 'unknown'} passed startup probe",
                success=True,
            )
            logging.info("AI 客户端初始化成功，使用预设: %s", preset_name)
            self.bot_manager.clear_issue()
            await self._schedule_export_rag_sync(force=False)
        else:
            logging.warning("AI 客户端初始化失败，未能选择有效预设")
            self.bot_manager.set_issue(
                code="ai_client_unavailable",
                title="AI 客户端初始化失败",
                detail="未能选择到可用的 AI 预设，机器人将无法正常回复。",
                suggestions=[
                    "检查激活预设的 base_url、model 和 API Key。",
                    "在设置页使用“测试连接”验证当前预设。",
                ],
                recoverable=False,
            )

        # 初始化微信客户端
        await self.bot_manager.update_startup_state(
            "connect_wechat",
            "正在连接微信客户端...",
            78,
            active=True,
        )
        reconnect_policy = get_reconnect_policy(self.bot_cfg)
        self.wx = await reconnect_wechat(
            "初始化",
            reconnect_policy,
            bot_cfg=self.bot_cfg,
            ai_client=self.ai_client,
        )
        if self.wx is not None and hasattr(self.wx, "ai_client"):
            self.wx.ai_client = self.ai_client
        if self.wx is None:
            logging.error("微信初始化失败")
            self.bot_manager.set_issue(
                code="wechat_connect_failed",
                title="微信连接失败",
                detail="未能连接到微信客户端，请确认微信已启动且版本受支持。",
                suggestions=[
                    "检查微信 PC 是否已登录。",
                    f"确认当前微信版本为受支持的 {OFFICIAL_SUPPORTED_WECHAT_VERSION}。",
                    "必要时点击“一键恢复”重新连接。",
                ],
                recoverable=True,
            )
            return None
        await self.bot_manager.update_startup_state(
            "ready",
            "机器人已就绪",
            100,
            active=False,
        )
            
        return self.wx

    def _apply_config(self) -> None:
        self.bot_cfg = self.config.get("bot", {})
        self.api_cfg = self.config.get("api", {})
        self.agent_cfg = self.config.get("agent", {})
        
        level, log_file, max_bytes, backup_count, format_type = get_logging_settings(self.config)
        setup_logging(level, log_file, max_bytes, backup_count, format_type)
        
        self.log_message_content, self.log_reply_content = get_log_behavior(self.config)
        
        max_concurrency = as_int(self.bot_cfg.get("max_concurrency", 5), 5, min_value=1)
        self.sem = asyncio.Semaphore(max_concurrency)

        # 预处理过滤列表
        ignore_names = [
            str(name).strip()
            for name in iter_items(self.bot_cfg.get("ignore_names", []))
            if str(name).strip()
        ]
        self.ignore_names_set = {name.lower() for name in ignore_names}
        
        self.ignore_keywords_list = [
            str(keyword).strip()
            for keyword in iter_items(self.bot_cfg.get("ignore_keywords", []))
            if str(keyword).strip()
        ]

        if self.export_rag:
            self.export_rag.update_config(self.bot_cfg)

    def _ensure_vector_memory(self) -> None:
        if not self._vector_memory_requested():
            if self.export_rag_sync_task and not self.export_rag_sync_task.done():
                self.export_rag_sync_task.cancel()
            self.vector_memory = None
            self.export_rag = None
            return
        if self.vector_memory is None:
            try:
                self.vector_memory = VectorMemory()
                logging.info("向量记忆模块已启用")
            except Exception as exc:
                logging.warning("向量记忆模块初始化失败: %s", exc)
                self.vector_memory = None
        if self.vector_memory is not None:
            if self.export_rag is None:
                self.export_rag = ExportChatRAG(self.vector_memory)
            self.export_rag.update_config(self.bot_cfg)

    def _vector_memory_requested(self) -> bool:
        if not bool(self.bot_cfg.get("vector_memory_enabled", True)):
            return False
        return bool(
            self.bot_cfg.get("rag_enabled", False)
            or self.bot_cfg.get("export_rag_enabled", False)
        )

    async def run(self) -> None:
        from wxauto import WeChat  # 延迟导入以避免顶层依赖问题
        
        wx = await self.initialize()
        if not wx:
            return

        logging.info("机器人主循环启动")
        
        # 主循环变量
        poll_interval_min = as_float(self.bot_cfg.get("poll_interval_min_sec", 0.05), 0.05)
        poll_interval_max = as_float(self.bot_cfg.get("poll_interval_max_sec", 1.0), 1.0)
        poll_interval = poll_interval_min
        poll_backoff = as_float(self.bot_cfg.get("poll_interval_backoff_factor", 1.2), 1.2)
        
        config_reload_sec = as_float(self.bot_cfg.get("config_reload_sec", 2.0), 2.0)
        config_check_ts = 0.0
        
        last_poll_ok_ts = time.time()
        
        while not self._should_stop():
            try:
                now = time.time()
                
                # 检查配置重载
                watcher_triggered = False
                if self.config_reload_watcher and self.config_reload_watcher.mode == "watchdog":
                    if self.config_reload_watcher.consume_change():
                        watcher_triggered = True
                        await self._check_config_reload(now, force=True)
                if (
                    not watcher_triggered
                    and config_reload_sec > 0
                    and now - config_check_ts >= config_reload_sec
                ):
                    config_check_ts = now
                    await self._check_config_reload(now)
                    # 更新本地变量以适应配置变更
                    poll_interval_min = as_float(self.bot_cfg.get("poll_interval_min_sec", 0.05), 0.05)
                    poll_interval_max = as_float(self.bot_cfg.get("poll_interval_max_sec", 1.0), 1.0)
                    poll_backoff = as_float(self.bot_cfg.get("poll_interval_backoff_factor", 1.2), 1.2)
                    config_reload_sec = as_float(self.bot_cfg.get("config_reload_sec", 2.0), 2.0)
                elif watcher_triggered:
                    poll_interval_min = as_float(self.bot_cfg.get("poll_interval_min_sec", 0.05), 0.05)
                    poll_interval_max = as_float(self.bot_cfg.get("poll_interval_max_sec", 1.0), 1.0)
                    poll_backoff = as_float(self.bot_cfg.get("poll_interval_backoff_factor", 1.2), 1.2)
                    config_reload_sec = as_float(self.bot_cfg.get("config_reload_sec", 2.0), 2.0)

                # IPC 命令检查
                cmds = self.ipc.get_commands()
                for cmd in cmds:
                    await self._execute_ipc_command(wx, cmd)


                # 心跳保活检查
                keepalive_idle_sec = as_float(self.bot_cfg.get("keepalive_idle_sec", 0.0), 0.0)
                if keepalive_idle_sec > 0 and (now - last_poll_ok_ts > keepalive_idle_sec):
                    reconnect_policy = get_reconnect_policy(self.bot_cfg)
                    wx = await reconnect_wechat(
                        "keepalive 超时",
                        reconnect_policy,
                        bot_cfg=self.bot_cfg,
                        ai_client=self.ai_client,
                    )
                    if wx is not None and hasattr(wx, "ai_client"):
                        wx.ai_client = self.ai_client
                    if wx is None:
                        await asyncio.sleep(reconnect_policy.base_delay_sec)
                        continue
                    last_poll_ok_ts = time.time()

                # 轮询消息
                try:
                    filter_mute = bool(self.bot_cfg.get("filter_mute", False))
                    async with self.wx_lock:
                        if filter_mute and self._wx_supports_filter_mute is not False:
                            try:
                                raw = await asyncio.to_thread(
                                    wx.GetNextNewMessage,
                                    filter_mute=True,
                                )
                                self._wx_supports_filter_mute = True
                            except TypeError as exc:
                                if "filter_mute" not in str(exc):
                                    raise
                                self._wx_supports_filter_mute = False
                                logging.warning("当前 wxauto 版本不支持 filter_mute，已回退为无参轮询。")
                                raw = await asyncio.to_thread(wx.GetNextNewMessage)
                        else:
                            raw = await asyncio.to_thread(wx.GetNextNewMessage)
                    last_poll_ok_ts = time.time()
                except Exception as exc:
                    logging.exception("获取消息异常：%s", exc)
                    reconnect_policy = get_reconnect_policy(self.bot_cfg)
                    wx = await reconnect_wechat(
                        "GetNextNewMessage 异常",
                        reconnect_policy,
                        bot_cfg=self.bot_cfg,
                        ai_client=self.ai_client,
                    )
                    if wx is not None and hasattr(wx, "ai_client"):
                        wx.ai_client = self.ai_client
                    if wx is None:
                        await asyncio.sleep(reconnect_policy.base_delay_sec)
                    poll_interval = min(poll_interval_max, poll_interval * poll_backoff)
                    continue

                events = normalize_new_messages(raw, self.bot_cfg.get("self_name", ""))
                
                if events:
                    poll_interval = poll_interval_min
                else:
                    poll_interval = min(poll_interval_max, poll_interval * poll_backoff)

                merge_sec = as_float(self.bot_cfg.get("merge_user_messages_sec", 0.0), 0.0)
                for event in events:
                    if merge_sec > 0:
                        task = asyncio.create_task(self.schedule_merged_reply(wx, event))
                    else:
                        task = asyncio.create_task(self.handle_event(wx, event))
                    self._track_pending_task(task)
                    task.add_done_callback(self.pending_tasks.discard)

            except KeyboardInterrupt:
                logging.info("收到退出信号")
                break
            except Exception as exc:
                logging.exception("主循环异常：%s", exc)
                await asyncio.sleep(2)
            
            await asyncio.sleep(poll_interval)

        # 清理资源
        await self.shutdown()

    def _should_stop(self) -> bool:
        """检查是否应该停止"""
        if self._stop_event and self._stop_event.is_set():
            return True
        return False
    
    def pause(self):
        """暂停机器人"""
        self._is_paused = True
        logging.info("机器人已暂停")
    
    def resume(self):
        """恢复机器人"""
        self._is_paused = False
        logging.info("机器人已恢复")

    async def shutdown(self) -> None:
        """优雅关闭，清理所有资源"""
        if self.pending_tasks:
            for task in self.pending_tasks:
                task.cancel()
            await asyncio.gather(*self.pending_tasks, return_exceptions=True)

        if self.export_rag_sync_task and not self.export_rag_sync_task.done():
            self.export_rag_sync_task.cancel()
            await asyncio.gather(self.export_rag_sync_task, return_exceptions=True)
            
        if self.ai_client and hasattr(self.ai_client, "close"):
            await self.ai_client.close()

        if self.memory:
            await self.memory.close()

        if self.config_reload_watcher:
            self.config_reload_watcher.stop()

    def _ensure_config_reload_watcher(self) -> None:
        preferred_mode = str(
            self.bot_cfg.get("config_reload_mode", "auto") or "auto"
        ).strip().lower()
        debounce_ms = as_int(
            self.bot_cfg.get("config_reload_debounce_ms", 500),
            500,
            min_value=0,
        )
        watch_paths = [self.config_path, self.override_path]
        if self.config_reload_watcher is None:
            self.config_reload_watcher = ConfigReloadWatcher(
                watch_paths,
                debounce_ms=debounce_ms,
                preferred_mode=preferred_mode,
            )
            self.config_reload_watcher.start()
            return
        self.config_reload_watcher.update(
            paths=watch_paths,
            debounce_ms=debounce_ms,
            preferred_mode=preferred_mode,
        )

    async def _check_config_reload(self, now: float, force: bool = False) -> None:
        # Check main config file
        new_mtime = get_file_mtime(self.config_path)
        new_override_mtime = get_file_mtime(self.override_path)
        
        should_reload = force

        if new_mtime and new_mtime != self.config_mtime:
            should_reload = True
            self.config_mtime = new_mtime
            
        # Also reload if override file changed (or was created/deleted)
        # Note: get_file_mtime returns None if file doesn't exist
        if new_override_mtime != self.override_mtime:
            should_reload = True
            self.override_mtime = new_override_mtime

        if force:
            self.config_mtime = new_mtime
            self.override_mtime = new_override_mtime

        if should_reload:
            try:
                new_config = load_config(self.config_path)
            except Exception as exc:
                logging.warning("配置重载失败: %s", exc)
                return

            self.config = new_config
            self._apply_config()
            self._ensure_config_reload_watcher()
            self._ensure_vector_memory()
            
            # 重新检查 AI 客户端
            if self.bot_cfg.get("reload_ai_client_on_change", True):
                new_signature = compute_api_signature(
                    {"api": self.api_cfg, "agent": self.agent_cfg}
                )
                if new_signature != self.api_signature:
                    new_client, new_preset = await select_ai_client(
                        self.api_cfg, self.bot_cfg, self.agent_cfg
                    )
                    if new_client:
                        if self.ai_client and hasattr(self.ai_client, "close"):
                            await self.ai_client.close()
                        self.ai_client = new_client
                        self.api_signature = new_signature
                        self.runtime_preset_name = new_preset or ""
                        self._set_ai_health(
                            "healthy",
                            f"AI preset {self.runtime_preset_name or 'unknown'} reloaded successfully",
                            success=True,
                        )
                        logging.info("配置更新，已重新加载 AI 客户端: %s", new_preset)
            await self._schedule_export_rag_sync(force=False)

    async def reload_runtime_config(
        self,
        *,
        new_config: Optional[Dict[str, Any]] = None,
        force_ai_reload: bool = False,
        strict_active_preset: bool = False,
    ) -> Dict[str, Any]:
        """
        立即重载运行时配置，并在需要时立刻切换 AI 客户端。
        """
        try:
            self.config = new_config if new_config is not None else load_config(self.config_path)
        except Exception as exc:
            logging.warning("立即重载配置失败: %s", exc)
            return {"success": False, "message": f"配置加载失败: {exc}", "runtime_preset": self.runtime_preset_name}

        self._apply_config()
        self._ensure_vector_memory()
        new_signature = compute_api_signature(
            {"api": self.api_cfg, "agent": self.agent_cfg}
        )
        need_reload_client = force_ai_reload or new_signature != self.api_signature

        if not need_reload_client:
            await self._schedule_export_rag_sync(force=True)
            return {
                "success": True,
                "message": "配置已立即应用",
                "runtime_preset": self.runtime_preset_name,
            }

        if not self.bot_cfg.get("reload_ai_client_on_change", True) and not force_ai_reload:
            return {
                "success": True,
                "message": "配置已应用，AI 客户端保持不变",
                "runtime_preset": self.runtime_preset_name,
            }

        active_preset = str(self.api_cfg.get("active_preset") or "").strip()
        if strict_active_preset and active_preset:
            new_client, new_preset = await select_specific_ai_client(
                self.api_cfg, self.bot_cfg, active_preset, self.agent_cfg
            )
        else:
            new_client, new_preset = await select_ai_client(
                self.api_cfg, self.bot_cfg, self.agent_cfg
            )

        if not new_client:
            self._set_ai_health("error", "AI hot reload failed", error=True)
            return {
                "success": False,
                "message": "AI 客户端重载失败，请检查当前激活预设的连接配置",
                "runtime_preset": self.runtime_preset_name,
            }

        if self.ai_client and hasattr(self.ai_client, "close"):
            await self.ai_client.close()

        self.ai_client = new_client
        self.api_signature = new_signature
        self.runtime_preset_name = new_preset or active_preset
        self._set_ai_health(
            "healthy",
            f"AI preset {self.runtime_preset_name or 'unknown'} hot-switched successfully",
            success=True,
        )
        logging.info("已立即切换运行中 AI 客户端: %s", self.runtime_preset_name)
        await self._schedule_export_rag_sync(force=True)
        return {
            "success": True,
            "message": f"运行中的 AI 已立即切换到 {self.runtime_preset_name}",
            "runtime_preset": self.runtime_preset_name,
        }

    async def _schedule_export_rag_sync(self, *, force: bool) -> None:
        if (
            not self.export_rag
            or not self.export_rag.enabled
            or not self.export_rag.auto_ingest
            or not self.ai_client
        ):
            return
        if self.export_rag_sync_task and not self.export_rag_sync_task.done():
            if not force:
                return
            self.export_rag_sync_task.cancel()
            await asyncio.gather(self.export_rag_sync_task, return_exceptions=True)
        self.export_rag_sync_task = asyncio.create_task(self._run_export_rag_sync(force=force))

    async def _run_export_rag_sync(self, *, force: bool) -> None:
        if not self.export_rag or not self.ai_client:
            return
        try:
            result = await self.export_rag.sync(self.ai_client, force=force)
            reason = result.get("reason")
            if result.get("indexed_chunks"):
                logging.info(
                    "导出语料 RAG 已更新: 联系人 %s, 片段 %s",
                    result.get("indexed_contacts", 0),
                    result.get("indexed_chunks", 0),
                )
            elif reason and reason not in {"disabled", ""}:
                logging.info("导出语料 RAG 未执行: %s", reason)
            asyncio.create_task(self.bot_manager.notify_status_change())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.warning("导出语料 RAG 同步失败: %s", exc)
            asyncio.create_task(self.bot_manager.notify_status_change())

    def get_export_rag_status(self) -> Dict[str, Any]:
        vector_memory_enabled = bool(self.bot_cfg.get("vector_memory_enabled", True))
        if not self.export_rag:
            return {
                "enabled": bool(
                    vector_memory_enabled and self.bot_cfg.get("export_rag_enabled", False)
                ),
                "vector_memory_enabled": vector_memory_enabled,
                "base_dir": str(self.bot_cfg.get("export_rag_dir") or ""),
                "auto_ingest": bool(self.bot_cfg.get("export_rag_auto_ingest", True)),
                "indexed_contacts": 0,
                "indexed_chunks": 0,
                "last_scan_at": None,
                "last_scan_summary": {},
            }
        status = self.export_rag.get_status()
        status["vector_memory_enabled"] = vector_memory_enabled
        return status

    def get_agent_status(self) -> Dict[str, Any]:
        if self.ai_client and hasattr(self.ai_client, "get_status"):
            status = dict(self.ai_client.get_status())
            status["ai_health"] = dict(self.ai_health)
            return status
        return {
            "engine": "legacy",
            "graph_mode": "disabled",
            "langsmith_enabled": False,
            "retriever_stats": {},
            "cache_stats": {},
            "runtime_timings": {},
            "ai_health": dict(self.ai_health),
        }

    def _set_ai_health(
        self,
        status: str,
        detail: str,
        *,
        success: bool = False,
        error: bool = False,
    ) -> None:
        now = time.time()
        next_state = {
            "status": str(status or "unknown").strip().lower(),
            "detail": str(detail or "").strip(),
            "checked_at": now,
            "last_success_at": self.ai_health.get("last_success_at"),
            "last_error_at": self.ai_health.get("last_error_at"),
            "last_error": self.ai_health.get("last_error", ""),
        }
        if success:
            next_state["last_success_at"] = now
            next_state["last_error"] = ""
        if error:
            next_state["last_error_at"] = now
            next_state["last_error"] = str(detail or "").strip()
        self.ai_health = next_state
        self._notify_runtime_status_changed()

    async def schedule_merged_reply(self, wx: "WeChat", event: MessageEvent) -> None:
        if is_voice_message(event.msg_type):
            await self.handle_event(wx, event)
            return

        if not should_reply(
            event, 
            self.config,
            ignore_names_set=self.ignore_names_set,
            ignore_keywords_list=self.ignore_keywords_list
        ):
            return

        chat_id = f"group:{event.chat_name}" if event.is_group else f"friend:{event.chat_name}"
        now = time.time()
        
        async with self.pending_merge_lock:
            if chat_id not in self.pending_merge_first_ts:
                self.pending_merge_first_ts[chat_id] = now
                self.pending_merge_first_event[chat_id] = event
            
            self.pending_merge_messages.setdefault(chat_id, []).append(event.content)
            self.pending_merge_events[chat_id] = event
            
            if chat_id in self.pending_merge_tasks:
                task = self.pending_merge_tasks[chat_id]
                if not task.done():
                    task.cancel()
            
            merge_sec = as_float(self.bot_cfg.get("merge_user_messages_sec", 0.0), 0.0)
            max_wait = as_float(self.bot_cfg.get("merge_user_messages_max_wait_sec", 0.0), 0.0)
            
            delay = merge_sec
            if max_wait > 0:
                elapsed = now - self.pending_merge_first_ts[chat_id]
                remaining = max_wait - elapsed
                delay = min(delay, max(0.0, remaining))
            
            task = asyncio.create_task(self.wait_and_reply(wx, chat_id, delay))
            self.pending_merge_tasks[chat_id] = task
            self._track_pending_task(task)
            task.add_done_callback(self.pending_tasks.discard)
            self._notify_runtime_status_changed()

    async def wait_and_reply(self, wx: "WeChat", chat_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self._notify_runtime_status_changed()
            return

        async with self.pending_merge_lock:
            messages = self.pending_merge_messages.pop(chat_id, [])
            event = self.pending_merge_events.pop(chat_id, None)
            first_event = self.pending_merge_first_event.pop(chat_id, None)
            self.pending_merge_tasks.pop(chat_id, None)
            self.pending_merge_first_ts.pop(chat_id, None)
        self._notify_runtime_status_changed()
        
        combined_text = "\n".join(messages).strip()
        if not event or not combined_text:
            return
            
        if first_event and first_event.raw_item:
            event.raw_item = first_event.raw_item
            
        await self.handle_event(
            wx,
            event,
            user_text_override=combined_text,
            message_log_override=combined_text,
        )

    async def handle_event(
        self,
        wx: "WeChat",
        event: MessageEvent,
        user_text_override: Optional[str] = None,
        message_log_override: Optional[str] = None
    ) -> None:
        async with self.sem:
            try:
                # 1. 记录日志
                log_text = message_log_override if message_log_override is not None else event.content
                message_log = format_log_text(log_text, self.log_message_content)
                logging.debug(
                    "收到消息 | 会话=%s | 发送者=%s | 类型=%s | 内容=%s",
                    event.chat_name, event.sender, event.msg_type, message_log
                )

                # 如果是图片消息，content 包含 [图片] 标记
                image_path = None
                if is_image_message(event.msg_type) and "[图片]" in event.content:
                    try:
                        save_dir = os.path.join(os.getcwd(), "temp_images")
                        os.makedirs(save_dir, exist_ok=True)
                        if event.raw_item:
                            filename = f"{int(time.time())}_{hash(event.sender)}.jpg"
                            save_path = os.path.join(save_dir, filename)
                            await asyncio.to_thread(event.raw_item.SaveFile, save_path)
                            logging.info(f"图片已保存: {save_path}")
                            image_path = save_path
                    except Exception as e:
                        logging.error(f"图片下载失败: {e}")
                
                # IPC 记录
                recipient = f"group:{event.chat_name}" if event.is_group else "Bot"
                self.ipc.log_message(event.sender, event.content, "incoming", recipient)
                
                # 广播事件
                asyncio.create_task(self.bot_manager.broadcast_event("message", {
                    "direction": "incoming",
                    "chat_id": f"group:{event.chat_name}" if event.is_group else f"friend:{event.chat_name}",
                    "chat_name": event.chat_name,
                    "sender": event.sender,
                    "content": event.content,
                    "recipient": recipient,
                    "timestamp": event.timestamp or time.time()
                }))


                # 2. 控制命令
                if self.bot_cfg.get("control_commands_enabled", True):
                    if await self._handle_control_command(wx, event):
                        return

                # 3. 响应检查 (暂停/静默)
                can_respond, quiet_reply = should_respond(self.bot_cfg)
                if not can_respond:
                    if quiet_reply:
                        async with self.wx_lock:
                            await asyncio.to_thread(
                                send_message, wx, event.chat_name, quiet_reply, self.bot_cfg
                            )
                    return

                if not should_reply(
                    event,
                    self.config,
                    ignore_names_set=self.ignore_names_set,
                    ignore_keywords_list=self.ignore_keywords_list
                ):
                    return

                # 4. 语音转文字
                if is_voice_message(event.msg_type) and user_text_override is None:
                    voice_text, err = await transcribe_voice_message(event, self.bot_cfg, self.wx_lock)
                    if not voice_text:
                        logging.warning("语音转文字失败: %s", err)
                        return
                    event.content = voice_text
                    if message_log_override is None:
                        message_log = format_log_text(event.content, self.log_message_content)

                # 5. 核心处理
                await self._process_and_reply(
                    wx, 
                    event,
                    user_text_override or event.content,
                    message_log,
                    image_path=image_path
                )
                
            except Exception as exc:
                logging.exception("消息处理异常: %s", exc)

    async def _handle_control_command(self, wx: "WeChat", event: MessageEvent) -> bool:
        cmd_prefix = self.bot_cfg.get("control_command_prefix", "/")
        if not is_command_message(event.content, cmd_prefix):
            return False
            
        allowed = self.bot_cfg.get("control_allowed_users", [])
        
        # 使用 asyncio.to_thread 包装可能包含文件 I/O 的同步调用
        result = await asyncio.to_thread(
            parse_control_command, 
            event.content, 
            cmd_prefix, 
            allowed, 
            event.sender
        )
        
        if result and result.should_reply:
            if result.command in ("pause", "resume"):
                await self.bot_manager.apply_pause_state(
                    result.command == "pause",
                    reason=(" ".join(result.args) or "手动暂停") if result.command == "pause" else "",
                    propagate_to_bot=False,
                )
            if self.bot_cfg.get("control_reply_visible", True):
                async with self.wx_lock:
                    await asyncio.to_thread(
                        send_message, wx, event.chat_name, result.response, self.bot_cfg
                    )
            logging.info("执行控制命令: %s", result.command)
            return True
        return False

    async def _process_and_reply(
        self,
        wx: "WeChat",
        event: MessageEvent,
        user_text: str,
        message_log: str,
        image_path: Optional[str] = None
    ) -> None:
        chat_id = f"group:{event.chat_name}" if event.is_group else f"friend:{event.chat_name}"
        if not self.ai_client:
            return

        try:
            async with self._get_chat_lock(chat_id):
                prepared = await self.ai_client.prepare_request(
                    event=event,
                    chat_id=chat_id,
                    user_text=user_text,
                    dependencies=self._runtime_dependencies(),
                    image_path=image_path,
                )

                reply_text = ""
                should_stream = bool(self.bot_cfg.get("stream_reply", False)) and bool(
                    self.agent_cfg.get("streaming_enabled", True)
                )
                if should_stream:
                    reply_text = await self._stream_smart_reply(wx, event, prepared)
                else:
                    reply_text = await self.ai_client.invoke(prepared)
                    if reply_text:
                        await self._send_smart_reply(wx, event, reply_text)
        except Exception as exc:
            self._set_ai_health("error", f"Last AI call failed: {exc}", error=True)
            raise

        try:
            if not reply_text:
                return

            timings = dict(getattr(prepared, "timings", {}) or {})
            latency_sec = 0.0
            for key in ("stream_sec", "invoke_sec", "prepare_total_sec"):
                value = timings.get(key)
                if value:
                    latency_sec = float(value)
                    break
            if latency_sec > 0:
                detail = (
                    f"Last AI call succeeded on preset {self.runtime_preset_name or 'unknown'} "
                    f"in {round(latency_sec * 1000)} ms"
                )
            else:
                detail = f"Last AI call succeeded on preset {self.runtime_preset_name or 'unknown'}"
            self._set_ai_health("healthy", detail, success=True)

            response_metadata = self._build_reply_metadata(
                prepared=prepared,
                event=event,
                chat_id=chat_id,
                user_text=user_text,
                reply_text=reply_text,
                streamed=should_stream,
            )
            prepared.response_metadata = response_metadata

            # IPC 记录出口消息
            self.ipc.log_message("Bot", reply_text, "outgoing", event.sender)

            asyncio.create_task(self.bot_manager.broadcast_event("message", {
                "direction": "outgoing",
                "chat_id": chat_id,
                "chat_name": event.chat_name,
                "sender": "Bot",
                "content": reply_text,
                "recipient": event.chat_name,
                "timestamp": time.time(),
                "metadata": response_metadata,
            }))

            await self.ai_client.finalize_request(
                prepared,
                reply_text,
                self._runtime_dependencies(),
            )
            self._record_reply_stats(user_text, reply_text)
        finally:
            if image_path and os.path.exists(image_path):
                await asyncio.to_thread(os.remove, image_path)

    def _runtime_dependencies(self) -> Dict[str, Any]:
        return {
            "memory": self.memory,
            "vector_memory": self.vector_memory,
            "export_rag": self.export_rag,
        }

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        lock = self.chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self.chat_locks[chat_id] = lock
        return lock

    async def _stream_smart_reply(
        self,
        wx: "WeChat",
        event: MessageEvent,
        prepared: Any,
    ) -> str:
        chunk_size = as_int(self.bot_cfg.get("reply_chunk_size", 500), 500)
        delay_sec = as_float(self.bot_cfg.get("reply_chunk_delay_sec", 0.0), 0.0)
        min_interval = as_float(self.bot_cfg.get("min_reply_interval_sec", 0.2), 0.2)
        stream_buffer_chars = as_int(self.bot_cfg.get("stream_buffer_chars", 30), 30, min_value=1)
        stream_chunk_max = as_int(self.bot_cfg.get("stream_chunk_max_chars", 200), 200, min_value=1)

        emoji_policy = str(self.bot_cfg.get("emoji_policy", "wechat"))
        replacements = self.bot_cfg.get("emoji_replacements")

        quote_mode = str(self.bot_cfg.get("reply_quote_mode", "wechat") or "wechat").lower()
        quote_template = str(self.bot_cfg.get("reply_quote_template") or "引用：{content}\n")
        quote_max_chars = as_int(self.bot_cfg.get("reply_quote_max_chars", 120), 120, min_value=0)
        quote_timeout_sec = as_float(self.bot_cfg.get("reply_quote_timeout_sec", 5.0), 5.0, min_value=0.0)
        quote_fallback_to_text = bool(self.bot_cfg.get("reply_quote_fallback_to_text", True))

        quote_text = ""
        if quote_max_chars > 0:
            quote_content = str(event.content or "").strip()
            if quote_content:
                if quote_max_chars and len(quote_content) > quote_max_chars:
                    quote_content = quote_content[:quote_max_chars]
                try:
                    quote_text = quote_template.format(
                        content=quote_content,
                        sender=event.sender or "",
                        chat=event.chat_name or "",
                    )
                except Exception:
                    quote_text = f"引用：{quote_content}\n"

        quote_item = None
        quote_fallback_text = None
        if quote_mode == "wechat":
            raw_item = getattr(event, "raw_item", None)
            if raw_item is not None and callable(getattr(raw_item, "quote", None)):
                quote_item = raw_item
            if quote_item and quote_text and quote_fallback_to_text:
                quote_fallback_text = quote_text
        elif quote_mode == "text":
            quote_fallback_text = quote_text

        emitted = False
        first_quote_item = quote_item
        first_quote_fallback = quote_fallback_text
        buffer = ""
        collected_parts: List[str] = []

        async for raw_chunk in self.ai_client.stream_reply(prepared):
            chunk = str(raw_chunk or "")
            if not chunk:
                continue
            collected_parts.append(chunk)
            buffer += chunk

            if len(buffer) < stream_buffer_chars and len(buffer) < stream_chunk_max:
                continue

            flush_now = len(buffer) >= stream_chunk_max or any(
                mark in buffer for mark in ("。", "！", "？", "\n", ".", "!", "?")
            )
            if not flush_now:
                continue

            sanitized = self._sanitize_reply_segment(buffer)
            if sanitized:
                if not emitted and quote_mode == "text" and first_quote_fallback:
                    sanitized = f"{first_quote_fallback}{sanitized}"
                    first_quote_fallback = None
                await send_reply_chunks(
                    wx,
                    event.chat_name,
                    sanitized,
                    self.bot_cfg,
                    chunk_size,
                    delay_sec,
                    min_interval,
                    self.last_reply_ts,
                    self.wx_lock,
                    quote_item=first_quote_item if not emitted else None,
                    quote_timeout_sec=quote_timeout_sec,
                    quote_fallback_text=first_quote_fallback if not emitted else None,
                )
                emitted = True
                first_quote_item = None
                first_quote_fallback = None
                buffer = ""

        if buffer:
            sanitized = self._sanitize_reply_segment(buffer)
            if sanitized:
                if not emitted and quote_mode == "text" and first_quote_fallback:
                    sanitized = f"{first_quote_fallback}{sanitized}"
                    first_quote_fallback = None
                await send_reply_chunks(
                    wx,
                    event.chat_name,
                    sanitized,
                    self.bot_cfg,
                    chunk_size,
                    delay_sec,
                    min_interval,
                    self.last_reply_ts,
                    self.wx_lock,
                    quote_item=first_quote_item if not emitted else None,
                    quote_timeout_sec=quote_timeout_sec,
                    quote_fallback_text=first_quote_fallback if not emitted else None,
                )
                emitted = True

        suffix = self._build_reply_suffix_text()
        if suffix and emitted:
            await send_reply_chunks(
                wx,
                event.chat_name,
                suffix,
                self.bot_cfg,
                chunk_size,
                delay_sec,
                min_interval,
                self.last_reply_ts,
                self.wx_lock,
            )

        return "".join(collected_parts)


    async def _send_smart_reply(self, wx: "WeChat", event: MessageEvent, reply_text: str) -> None:
        chunk_size = as_int(self.bot_cfg.get("reply_chunk_size", 500), 500)
        delay_sec = as_float(self.bot_cfg.get("reply_chunk_delay_sec", 0.0), 0.0)
        min_interval = as_float(self.bot_cfg.get("min_reply_interval_sec", 0.2), 0.2)
        sanitized_reply = self._build_final_reply_text(reply_text)

        quote_mode = str(self.bot_cfg.get("reply_quote_mode", "wechat") or "wechat").lower()
        quote_template = str(self.bot_cfg.get("reply_quote_template") or "引用：{content}\n")
        quote_max_chars = as_int(self.bot_cfg.get("reply_quote_max_chars", 120), 120, min_value=0)
        quote_timeout_sec = as_float(self.bot_cfg.get("reply_quote_timeout_sec", 5.0), 5.0, min_value=0.0)
        quote_fallback_to_text = bool(self.bot_cfg.get("reply_quote_fallback_to_text", True))

        quote_text = ""
        if quote_max_chars > 0:
            quote_content = str(event.content or "").strip()
            if quote_content:
                if quote_max_chars and len(quote_content) > quote_max_chars:
                    quote_content = quote_content[:quote_max_chars]
                try:
                    quote_text = quote_template.format(
                        content=quote_content,
                        sender=event.sender or "",
                        chat=event.chat_name or "",
                    )
                except Exception:
                    quote_text = f"引用：{quote_content}\n"

        quote_item = None
        quote_fallback_text = None
        if quote_mode == "wechat":
            raw_item = getattr(event, "raw_item", None)
            if raw_item is not None and callable(getattr(raw_item, "quote", None)):
                quote_item = raw_item
            if quote_item and quote_text and quote_fallback_to_text:
                quote_fallback_text = quote_text
            elif not quote_item and quote_text and quote_fallback_to_text:
                sanitized_reply = f"{quote_text}{sanitized_reply}"
        elif quote_mode == "text":
            if quote_text:
                sanitized_reply = f"{quote_text}{sanitized_reply}"
        
        # 自然分段逻辑
        if self.bot_cfg.get("natural_split_enabled", False):
            segments = split_reply_naturally(sanitized_reply)
            for idx, seg in enumerate(segments):
                await send_reply_chunks(
                    wx, event.chat_name, seg, self.bot_cfg,
                    chunk_size, delay_sec, min_interval,
                    self.last_reply_ts, self.wx_lock,
                    quote_item=quote_item if idx == 0 else None,
                    quote_timeout_sec=quote_timeout_sec,
                    quote_fallback_text=quote_fallback_text if idx == 0 else None
                )
                if idx < len(segments) - 1:
                    await asyncio.sleep(random.uniform(0.8, 2.0))
        else:
            await send_reply_chunks(
                wx, event.chat_name, sanitized_reply, self.bot_cfg,
                chunk_size, delay_sec, min_interval,
                self.last_reply_ts, self.wx_lock,
                quote_item=quote_item,
                quote_timeout_sec=quote_timeout_sec,
                quote_fallback_text=quote_fallback_text
            )

    def _sanitize_reply_segment(self, reply_text: str) -> str:
        emoji_policy = str(self.bot_cfg.get("emoji_policy", "wechat"))
        replacements = self.bot_cfg.get("emoji_replacements")
        refined_reply = refine_reply_text(reply_text)
        return sanitize_reply_text(refined_reply, emoji_policy, replacements)

    def _build_final_reply_text(self, reply_text: str) -> str:
        sanitized = self._sanitize_reply_segment(reply_text)
        suffix = self._build_reply_suffix_text()
        return f"{sanitized}{suffix}" if suffix else sanitized

    def _build_reply_suffix_text(self) -> str:
        reply_suffix = str(self.bot_cfg.get("reply_suffix") or "").strip()
        if not reply_suffix:
            return ""
        model_name = getattr(self.ai_client, "model", "") if self.ai_client else ""
        alias = get_model_alias(self.ai_client)
        return build_reply_suffix(reply_suffix, model_name or "", alias)

    def _record_reply_stats(self, user_text: str, reply_text: str) -> None:
        state = get_bot_state()
        tokens = 0
        if self.bot_cfg.get("usage_tracking_enabled", True):
            _, _, tokens = estimate_exchange_tokens(self.ai_client, user_text, reply_text)
        state.add_reply(tokens)
        self.bot_manager._invalidate_status_cache()
        asyncio.create_task(self.bot_manager.notify_status_change())

    def _track_pending_task(self, task: asyncio.Task) -> None:
        completed = {item for item in self.pending_tasks if item.done()}
        if completed:
            self.pending_tasks.difference_update(completed)
        if len(self.pending_tasks) >= self.max_pending_tasks:
            logging.warning("待处理任务已达到上限 (%s)，跳过新增任务。", self.max_pending_tasks)
            task.cancel()
            self._notify_runtime_status_changed()
            return
        self.pending_tasks.add(task)
        self._notify_runtime_status_changed()

    def _build_reply_metadata(
        self,
        *,
        prepared: Any,
        event: MessageEvent,
        chat_id: str,
        user_text: str,
        reply_text: str,
        streamed: bool,
    ) -> Dict[str, Any]:
        user_tokens = 0
        reply_tokens = 0
        total_tokens = 0
        try:
            user_tokens, reply_tokens, total_tokens = estimate_exchange_tokens(
                self.ai_client, user_text, reply_text
            )
        except Exception:
            pass

        engine = "unknown"
        if self.ai_client and hasattr(self.ai_client, "get_status"):
            try:
                engine = str(self.ai_client.get_status().get("engine") or "unknown")
            except Exception:
                engine = "unknown"

        return {
            "kind": "assistant_reply",
            "chat_id": chat_id,
            "chat_name": event.chat_name,
            "sender": event.sender,
            "preset": self.runtime_preset_name,
            "model": str(getattr(self.ai_client, "model", "") or ""),
            "model_alias": get_model_alias(self.ai_client),
            "engine": engine,
            "streamed": streamed,
            "timings": dict(getattr(prepared, "timings", {}) or {}),
            "tokens": {
                "user": user_tokens,
                "reply": reply_tokens,
                "total": total_tokens,
            },
            "emotion": dict(getattr(prepared, "trace", {}).get("emotion") or {}) or None,
            "context_summary": dict(getattr(prepared, "trace", {}).get("context_summary") or {}),
            "profile": dict(getattr(prepared, "trace", {}).get("profile") or {}) or None,
        }

    def get_runtime_status(self) -> Dict[str, Any]:
        pending_merge_chats = len(self.pending_merge_tasks)
        pending_merge_messages = sum(len(items) for items in self.pending_merge_messages.values())
        return {
            "pending_tasks": len(self.pending_tasks),
            "merge_pending_chats": pending_merge_chats,
            "merge_pending_messages": pending_merge_messages,
            "merge_feedback": {
                "enabled": as_float(self.bot_cfg.get("merge_user_messages_sec", 0.0), 0.0) > 0,
                "active": pending_merge_chats > 0,
                "status_text": (
                    f"正在合并 {pending_merge_chats} 个会话的 {pending_merge_messages} 条消息"
                    if pending_merge_chats > 0
                    else "当前没有待合并消息"
                ),
            },
            "config_reload": (
                self.config_reload_watcher.get_status()
                if self.config_reload_watcher
                else {
                    "mode": "polling",
                    "preferred_mode": "auto",
                    "debounce_ms": 500,
                    "watch_paths": [],
                }
            ),
        }

    def _notify_runtime_status_changed(self) -> None:
        self.bot_manager._invalidate_status_cache()
        asyncio.create_task(self.bot_manager.notify_status_change())

    async def _execute_ipc_command(self, wx: "WeChat", cmd: Dict) -> None:
        """执行来自 Web 的 IPC 命令"""
        try:
            c_type = cmd.get("type")
            data = cmd.get("data", {})
            logging.info("执行 IPC 命令: %s", c_type)
            
            if c_type == "send_msg":
                target = data.get("target")
                content = data.get("content")
                if target and content:
                    async with self.wx_lock:
                        # 这是一个同步调用，但在线程中运行
                        await asyncio.to_thread(
                            send_message, wx, target, content, self.bot_cfg
                        )
                    self.ipc.log_message("WebUser", content, "outgoing", target)
            
            # 其他命令...
            
        except Exception as e:
            logging.error("IPC 命令执行失败: %s", e)

    async def send_text_message(self, target: str, content: str) -> Dict[str, Any]:
        """
        发送文本消息（供外部调用）
        
        Args:
            target: 目标名称（微信号/备注/群名）
            content: 消息内容
            
        Returns:
            执行结果字典
        """
        if not self.wx:
            return {'success': False, 'message': '微信客户端未连接'}
            
        try:
            async with self.wx_lock:
                 await asyncio.to_thread(
                    send_message, self.wx, target, content, self.bot_cfg
                )
            
            # 记录到 IPC/日志
            self.ipc.log_message("API", content, "outgoing", target)
            logging.info(f"API 发送消息 | 目标={target} | 内容={content}")

            # 广播事件
            asyncio.create_task(self.bot_manager.broadcast_event("message", {
                "direction": "outgoing",
                "chat_id": target,
                "chat_name": target,
                "sender": "API",
                "content": content,
                "recipient": target,
                "timestamp": time.time()
            }))

            return {'success': True, 'message': '发送成功'}
        except Exception as e:
            logging.error(f"消息发送失败: {e}")
            return {'success': False, 'message': f'发送失败: {str(e)}'}

    def get_stats(self) -> Dict[str, Any]:
        state = get_bot_state()
        return {
            "today_replies": state.today_replies,
            "today_tokens": state.today_tokens,
            "total_replies": state.total_replies,
            "total_tokens": state.total_tokens,
        }

    def get_transport_status(self) -> Dict[str, Any]:
        if self.wx and hasattr(self.wx, "get_transport_status"):
            try:
                return dict(self.wx.get_transport_status())
            except Exception as exc:
                logging.debug("获取 transport 状态失败: %s", exc)
        if self.wx:
            return {
                "transport_backend": "compat_ui",
                "silent_mode": False,
                "wechat_version": "",
                "required_wechat_version": "",
                "compat_mode": True,
                "supports_native_quote": True,
                "supports_voice_transcription": True,
                "transport_status": "connected",
                "transport_warning": "",
            }
        preferred_backend = str(self.bot_cfg.get("transport_backend") or "hook_wcferry").strip().lower()
        return {
            "transport_backend": preferred_backend,
            "silent_mode": preferred_backend == "hook_wcferry",
            "wechat_version": "",
            "required_wechat_version": str(self.bot_cfg.get("required_wechat_version") or "").strip(),
            "compat_mode": preferred_backend == "compat_ui",
            "supports_native_quote": preferred_backend != "hook_wcferry",
            "supports_voice_transcription": True,
            "transport_status": "disconnected",
            "transport_warning": get_last_transport_error(),
        }

