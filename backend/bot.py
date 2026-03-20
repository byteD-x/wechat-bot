import asyncio
import hashlib
import inspect
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .core.export_rag import ExportChatRAG
from .core.memory import MemoryManager
from .core.vector_memory import VectorMemory
from .core.bot_control import (
    should_respond,
    get_bot_state,
)
from .core.factory import (
    select_ai_client,
    select_specific_ai_client,
    get_reconnect_policy,
    get_last_ai_client_error,
    get_last_transport_error,
    reconnect_wechat,
    compute_api_signature,
    reload_ai_module,
)
from .core.config_service import get_config_service
from .core.config_audit import diff_config_paths
from .core.pricing_catalog import get_pricing_catalog
from .core.reply_quality_tracker import get_reply_quality_tracker

from .types import MessageEvent
from .bot_event_flow import (
    handle_control_command as helper_handle_control_command,
    maybe_save_event_image,
    maybe_send_quiet_reply,
    record_incoming_event,
    schedule_incoming_broadcast,
)
from .bot_runtime_helpers import (
    build_final_reply_text as helper_build_final_reply_text,
    build_reply_body_text as helper_build_reply_body_text,
    build_reply_suffix_text as helper_build_reply_suffix_text,
    ensure_send_succeeded as helper_ensure_send_succeeded,
    get_natural_split_config as helper_get_natural_split_config,
    is_filehelper_chat as helper_is_filehelper_chat,
    is_recent_outgoing_echo as helper_is_recent_outgoing_echo,
    normalize_chat_name as helper_normalize_chat_name,
    prepare_event_for_processing as helper_prepare_event_for_processing,
    prune_recent_outgoing_messages as helper_prune_recent_outgoing_messages,
    remember_recent_outgoing_message as helper_remember_recent_outgoing_message,
    sanitize_reply_segment as helper_sanitize_reply_segment,
)
from .bot_reply_flow import (
    complete_delayed_reply as helper_complete_delayed_reply,
    finalize_reply_delivery as helper_finalize_reply_delivery,
    mark_deadline_missed as helper_mark_deadline_missed,
    process_and_reply as helper_process_and_reply,
    schedule_delayed_reply as helper_schedule_delayed_reply,
)
from .handlers.filter import should_reply_with_reason
from .handlers.sender import send_message, send_reply_chunks
from .handlers.converters import normalize_new_messages
from .utils.common import as_float, as_int, get_file_mtime, iter_items
from .utils.config import get_model_alias
from .utils.logging import (
    setup_logging,
    get_logging_settings,
    get_log_behavior,
    format_log_text,
    build_stage_log_message,
)
from .utils.config_watcher import ConfigReloadWatcher
from .utils.message import (
    is_voice_message,
    split_reply_naturally,
)
from .utils.tools import transcribe_voice_message, estimate_exchange_tokens
from .utils.ipc import IPCManager
from .bot_manager import get_bot_manager
from .wechat_versions import OFFICIAL_SUPPORTED_WECHAT_VERSION
from .model_catalog import infer_provider_id
from .transports import BaseTransport

class WeChatBot:
    def __init__(self, config_path: str, memory_manager: Optional[MemoryManager] = None):
        self.config_path = config_path
        self.config_service = get_config_service()
        self.config: Dict[str, Any] = {}
        self.bot_cfg: Dict[str, Any] = {}
        self.api_cfg: Dict[str, Any] = {}
        self.agent_cfg: Dict[str, Any] = {}
        self.reply_quality_tracker = get_reply_quality_tracker()
        self.ai_client: Optional[Any] = None
        self.wx: Optional[BaseTransport] = None
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
        self.recent_outgoing_messages: Dict[str, List[Dict[str, Any]]] = {}
        self.reply_quality_stats: Dict[str, Any] = {
            "attempted": 0,
            "successful": 0,
            "empty": 0,
            "failed": 0,
            "delayed": 0,
            "retrieval_augmented": 0,
            "retrieval_hit_count": 0,
            "helpful_count": 0,
            "unhelpful_count": 0,
            "last_reply_at": None,
        }

    def _load_effective_config(self, *, force_reload: bool = False) -> Dict[str, Any]:
        snapshot = self.config_service.get_snapshot(
            config_path=self.config_path,
            force_reload=force_reload,
        )
        self.config = snapshot.to_dict()
        self.config_service.sync_default_config_snapshot(
            self.config,
            config_path=self.config_path,
        )
        return self.config

    def _build_event_trace_id(self, event: MessageEvent) -> str:
        raw = "|".join(
            [
                str(getattr(event, "chat_name", "") or ""),
                str(getattr(event, "sender", "") or ""),
                str(getattr(event, "content", "") or ""),
                str(getattr(event, "msg_type", "") or ""),
                str(getattr(event, "timestamp", "") or ""),
                "group" if bool(getattr(event, "is_group", False)) else "friend",
            ]
        )
        digest = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:8]
        return f"{'g' if bool(getattr(event, 'is_group', False)) else 'f'}-{digest}"

    @staticmethod
    def _ensure_event_defaults(event: Any) -> None:
        defaults = {
            "chat_name": "",
            "sender": "",
            "content": "",
            "msg_type": "text",
            "is_group": False,
            "is_self": False,
            "is_at_me": False,
            "timestamp": None,
            "raw_item": None,
        }
        defaults["chat_type"] = "group" if bool(getattr(event, "is_group", False)) else "friend"
        for key, value in defaults.items():
            if hasattr(event, key):
                continue
            try:
                setattr(event, key, value)
            except Exception:
                pass

    def _log_flow(
        self,
        level: int,
        stage: str,
        *,
        event: Optional[MessageEvent] = None,
        trace_id: Optional[str] = None,
        **fields: Any,
    ) -> None:
        payload: Dict[str, Any] = {}
        if trace_id:
            payload["trace"] = trace_id
        if event is not None:
            payload.setdefault("chat", getattr(event, "chat_name", ""))
            payload.setdefault("sender", getattr(event, "sender", ""))
            payload.setdefault("msg_type", getattr(event, "msg_type", ""))
            payload.setdefault("group", bool(getattr(event, "is_group", False)))
            payload.setdefault("self", bool(getattr(event, "is_self", False)))
        payload.update(fields)
        logging.log(level, build_stage_log_message(stage, **payload))

    def _message_preview(self, text: str, *, max_len: int = 120) -> str:
        return format_log_text(text, self.log_message_content, max_len=max_len)

    def _reply_preview(self, text: str, *, max_len: int = 120) -> str:
        return format_log_text(text, self.log_reply_content, max_len=max_len)

    @staticmethod
    def _transport_reconnect_required(changed_paths: List[str]) -> bool:
        transport_paths = {
            "bot.required_wechat_version",
            "bot.silent_mode_required",
        }
        return any(path in transport_paths for path in changed_paths)

    async def _reconnect_transport(self, reason: str) -> Dict[str, Any]:
        policy = get_reconnect_policy(self.bot_cfg)
        new_wx = await reconnect_wechat(
            reason,
            policy,
            bot_cfg=self.bot_cfg,
            ai_client=self.ai_client,
        )
        if new_wx is None:
            return {
                "success": False,
                "message": "微信传输层重连失败，请检查微信状态后重试",
            }

        if hasattr(new_wx, "ai_client"):
            new_wx.ai_client = self.ai_client

        async with self.wx_lock:
            self.wx = new_wx
            self._wx_supports_filter_mute = None

        return {
            "success": True,
            "message": "微信传输层已自动重连并生效",
        }

    async def initialize(self) -> Optional[BaseTransport]:
        try:
            await self.bot_manager.update_startup_state(
                "loading_config",
                "正在加载配置...",
                15,
                active=True,
            )
            self.config_mtime = get_file_mtime(self.config_path)
            self._load_effective_config()
        except Exception as exc:
            logging.error("无法加载配置文件: %s", exc)
            self._set_ai_health("error", "No available AI preset", error=True)
            self.bot_manager.set_issue(
                code="config_load_failed",
                title="配置加载失败",
                detail=str(exc),
                suggestions=[
                    "检查 app_config.json 是否存在语法错误或字段格式问题。",
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
            self._sync_ai_runtime_dependencies()
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
            ai_issue_detail = (
                get_last_ai_client_error()
                or "未能选择到可用的 AI 预设，机器人将无法正常回复。"
            )
            suggestions = [
                "检查激活预设的 base_url、model 和 API Key。",
                "在设置页使用“测试连接”验证当前预设。",
            ]
            if "Ollama" in ai_issue_detail:
                suggestions = [
                    "确认当前选择的是本地聊天模型，而不是 *:cloud 或 embedding 模型。",
                    "如果列表里只有云模型或 embedding 模型，请先在本机拉取一个可聊天的 Ollama 模型。",
                    "也可以先切换到其他已配置且可用的预设。",
                ]
            self.bot_manager.set_issue(
                code="ai_client_unavailable",
                title="AI 客户端初始化失败",
                detail=ai_issue_detail,
                suggestions=suggestions,
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
        self._sync_ai_runtime_dependencies()

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
        self._sync_ai_runtime_dependencies()

    def _vector_memory_requested(self) -> bool:
        if not bool(self.bot_cfg.get("vector_memory_enabled", True)):
            return False
        return bool(
            self.bot_cfg.get("rag_enabled", False)
            or self.bot_cfg.get("export_rag_enabled", False)
        )

    @staticmethod
    def _normalize_chat_name(chat_name: str) -> str:
        return helper_normalize_chat_name(chat_name)

    def _is_filehelper_chat(self, chat_name: str) -> bool:
        return helper_is_filehelper_chat(chat_name)

    def _prune_recent_outgoing_messages(self, *, now: Optional[float] = None) -> None:
        helper_prune_recent_outgoing_messages(
            self.recent_outgoing_messages,
            now=now,
        )

    def _remember_recent_outgoing_message(
        self,
        chat_name: str,
        text: str,
        *,
        chunk_size: Optional[int] = None,
    ) -> None:
        helper_remember_recent_outgoing_message(
            self.recent_outgoing_messages,
            chat_name,
            text,
            chunk_size=chunk_size,
        )

    def _is_recent_outgoing_echo(self, event: MessageEvent) -> bool:
        return helper_is_recent_outgoing_echo(self.recent_outgoing_messages, event)

    def _prepare_event_for_processing(self, event: MessageEvent) -> str:
        result = helper_prepare_event_for_processing(
            event,
            self.bot_cfg,
            self.recent_outgoing_messages,
        )
        if result == "skip_recent_outgoing_echo":
            logging.debug("跳过文件传输助手回声消息 | 会话=%s", event.chat_name)
        elif result == "accepted_self_filehelper":
            logging.debug("允许文件传输助手自发消息进入处理链路 | 会话=%s", event.chat_name)
        return result

    async def run(self) -> None:
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
                                    wx.poll_new_messages,
                                    filter_mute=True,
                                )
                                self._wx_supports_filter_mute = True
                            except TypeError as exc:
                                if "filter_mute" not in str(exc):
                                    raise
                                self._wx_supports_filter_mute = False
                                logging.warning("transport filter_mute unsupported; fallback to unfiltered polling")
                                raw = await asyncio.to_thread(wx.poll_new_messages)
                        else:
                            raw = await asyncio.to_thread(wx.poll_new_messages)
                    last_poll_ok_ts = time.time()
                except Exception as exc:
                    logging.exception("获取消息异常：%s", exc)
                    reconnect_policy = get_reconnect_policy(self.bot_cfg)
                    wx = await reconnect_wechat(
                        "poll_new_messages 异常",
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
                merge_sec = as_float(self.bot_cfg.get("merge_user_messages_sec", 0.0), 0.0)
                
                if events:
                    logging.info(
                        build_stage_log_message(
                            "POLL.RECEIVED",
                            count=len(events),
                            merge_mode=merge_sec > 0,
                        )
                    )
                    poll_interval = poll_interval_min
                else:
                    poll_interval = min(poll_interval_max, poll_interval * poll_backoff)

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
        watch_paths = [self.config_path]
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
        new_mtime = get_file_mtime(self.config_path)

        should_reload = force

        if new_mtime and new_mtime != self.config_mtime:
            should_reload = True
            self.config_mtime = new_mtime
            
        if force:
            self.config_mtime = new_mtime

        if should_reload:
            previous_config = dict(self.config or {})
            try:
                snapshot = self.config_service.reload(config_path=self.config_path)
                new_config = snapshot.to_dict()
            except Exception as exc:
                logging.warning("配置重载失败: %s", exc)
                return
            changed_paths = diff_config_paths(previous_config, new_config)

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
                    if self.bot_cfg.get("reload_ai_client_module", False):
                        await reload_ai_module(self.ai_client)
                    new_client, new_preset = await select_ai_client(
                        self.api_cfg, self.bot_cfg, self.agent_cfg
                    )
                    if new_client:
                        if self.ai_client and hasattr(self.ai_client, "close"):
                            await self.ai_client.close()
                        self.ai_client = new_client
                        self.api_signature = new_signature
                        self.runtime_preset_name = new_preset or ""
                        self._sync_ai_runtime_dependencies()
                        self._set_ai_health(
                            "healthy",
                            f"AI preset {self.runtime_preset_name or 'unknown'} reloaded successfully",
                            success=True,
                        )
                        logging.info("配置更新，已重新加载 AI 客户端: %s", new_preset)
            if self.wx is not None and self._transport_reconnect_required(changed_paths):
                reconnect_result = await self._reconnect_transport("配置热更新")
                if not reconnect_result.get("success"):
                    logging.warning("配置热更新后微信重连失败: %s", reconnect_result.get("message"))
            await self._schedule_export_rag_sync(force=False)
            self.bot_manager._invalidate_status_cache()
            await self.bot_manager.notify_status_change()

    async def reload_runtime_config(
        self,
        *,
        new_config: Optional[Dict[str, Any]] = None,
        changed_paths: Optional[List[str]] = None,
        force_ai_reload: bool = False,
        strict_active_preset: bool = False,
    ) -> Dict[str, Any]:
        """
        立即重载运行时配置，并在需要时立刻切换 AI 客户端。
        """
        previous_config = dict(self.config or {})
        try:
            if new_config is not None:
                snapshot = self.config_service.publish(
                    new_config,
                    config_path=self.config_path,
                    source="runtime_reload",
                )
            else:
                snapshot = self.config_service.reload(config_path=self.config_path)
            self.config = snapshot.to_dict()
            self.config_service.sync_default_config_snapshot(
                self.config,
                config_path=self.config_path,
            )
            self.config_mtime = get_file_mtime(self.config_path)
        except Exception as exc:
            logging.warning("立即重载配置失败: %s", exc)
            return {"success": False, "message": f"配置加载失败: {exc}", "runtime_preset": self.runtime_preset_name}

        resolved_changed_paths = list(changed_paths or diff_config_paths(previous_config, self.config))
        self._apply_config()
        self._ensure_config_reload_watcher()
        self._ensure_vector_memory()
        transport_reconnect_required = self._transport_reconnect_required(resolved_changed_paths)
        new_signature = compute_api_signature(
            {"api": self.api_cfg, "agent": self.agent_cfg}
        )
        need_reload_client = (
            force_ai_reload
            or bool(self.bot_cfg.get("reload_ai_client_module", False))
            or new_signature != self.api_signature
        )
        transport_reconnected = False
        messages: List[str] = []

        if not need_reload_client and not transport_reconnect_required:
            await self._schedule_export_rag_sync(force=True)
            self.bot_manager._invalidate_status_cache()
            await self.bot_manager.notify_status_change()
            return {
                "success": True,
                "message": "配置已立即应用",
                "runtime_preset": self.runtime_preset_name,
                "transport_reconnect_required": False,
                "transport_reconnected": False,
            }

        if not self.bot_cfg.get("reload_ai_client_on_change", True) and not force_ai_reload:
            messages.append("配置已应用，AI 客户端保持不变")
        elif need_reload_client:
            active_preset = str(self.api_cfg.get("active_preset") or "").strip()
            if self.bot_cfg.get("reload_ai_client_module", False):
                await reload_ai_module(self.ai_client)
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
                    "transport_reconnect_required": transport_reconnect_required,
                    "transport_reconnected": False,
                }

            if self.ai_client and hasattr(self.ai_client, "close"):
                await self.ai_client.close()

            self.ai_client = new_client
            self.api_signature = new_signature
            self.runtime_preset_name = new_preset or active_preset
            self._sync_ai_runtime_dependencies()
            self._set_ai_health(
                "healthy",
                f"AI preset {self.runtime_preset_name or 'unknown'} hot-switched successfully",
                success=True,
            )
            logging.info("已立即切换运行中 AI 客户端: %s", self.runtime_preset_name)
            messages.append(f"运行中的 AI 已立即切换到 {self.runtime_preset_name}")
        elif not messages:
            messages.append("配置已立即应用")

        if transport_reconnect_required and self.wx is not None:
            reconnect_result = await self._reconnect_transport("配置更新")
            if not reconnect_result.get("success"):
                self.bot_manager._invalidate_status_cache()
                await self.bot_manager.notify_status_change()
                return {
                    "success": False,
                    "message": reconnect_result.get("message") or "微信传输层重连失败",
                    "runtime_preset": self.runtime_preset_name,
                    "transport_reconnect_required": True,
                    "transport_reconnected": False,
                }
            transport_reconnected = True
            messages.append(reconnect_result.get("message") or "微信传输层已自动重连并生效")

        await self._schedule_export_rag_sync(force=True)
        self.bot_manager._invalidate_status_cache()
        await self.bot_manager.notify_status_change()
        return {
            "success": True,
            "message": "；".join(messages) if messages else "配置已立即应用",
            "runtime_preset": self.runtime_preset_name,
            "transport_reconnect_required": transport_reconnect_required,
            "transport_reconnected": transport_reconnected,
        }

    async def _schedule_export_rag_sync(self, *, force: bool) -> None:
        if (
            not self.export_rag
            or not self.export_rag.enabled
            or not self.export_rag.auto_ingest
            or not self.ai_client
        ):
            return
        self._sync_ai_runtime_dependencies()
        if hasattr(self.ai_client, "schedule_export_rag_sync"):
            await self.ai_client.schedule_export_rag_sync(force=force)
            asyncio.create_task(self.bot_manager.notify_status_change())
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
            "growth_mode": "deferred_until_batch",
            "growth_tasks_pending": 0,
            "last_growth_error": "",
            "foreground_active": 0,
            "foreground_waiters": 0,
            "background_active": 0,
            "background_backlog_count": 0,
            "background_backlog_by_task": {},
            "next_background_batch_at": None,
            "last_background_batch": {},
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

    async def schedule_merged_reply(self, wx: BaseTransport, event: MessageEvent) -> None:
        self._ensure_event_defaults(event)
        if is_voice_message(event.msg_type):
            await self.handle_event(wx, event)
            return

        trace_id = self._build_event_trace_id(event)
        event_state = self._prepare_event_for_processing(event)
        if event_state == "skip_recent_outgoing_echo":
            self._log_flow(
                logging.INFO,
                "MERGE.SKIP_ECHO",
                event=event,
                trace_id=trace_id,
            )
            return

        should_handle, reason = should_reply_with_reason(
            event, 
            self.config,
            ignore_names_set=self.ignore_names_set,
            ignore_keywords_list=self.ignore_keywords_list
        )
        if not should_handle:
            self._log_flow(
                logging.INFO,
                "MERGE.SKIP",
                event=event,
                trace_id=trace_id,
                reason=reason,
                preview=self._message_preview(event.content),
            )
            return

        chat_id = f"group:{event.chat_name}" if event.is_group else f"friend:{event.chat_name}"
        now = time.time()
        
        async with self.pending_merge_lock:
            if chat_id not in self.pending_merge_first_ts:
                self.pending_merge_first_ts[chat_id] = now
                self.pending_merge_first_event[chat_id] = event
            
            self.pending_merge_messages.setdefault(chat_id, []).append(event.content)
            self.pending_merge_events[chat_id] = event
            self._log_flow(
                logging.INFO,
                "MERGE.QUEUE",
                event=event,
                trace_id=trace_id,
                chat_id=chat_id,
                queued=len(self.pending_merge_messages.get(chat_id, [])),
                preview=self._message_preview(event.content),
            )
            
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

    async def wait_and_reply(self, wx: BaseTransport, chat_id: str, delay: float) -> None:
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

        trace_id = self._build_event_trace_id(event)
        self._log_flow(
            logging.INFO,
            "MERGE.FLUSH",
            event=event,
            trace_id=trace_id,
            chat_id=chat_id,
            merged_count=len(messages),
            preview=self._message_preview(combined_text),
        )
            
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
        wx: BaseTransport,
        event: MessageEvent,
        user_text_override: Optional[str] = None,
        message_log_override: Optional[str] = None
    ) -> None:
        async with self.sem:
            self._ensure_event_defaults(event)
            trace_id = self._build_event_trace_id(event)
            try:
                event_state = self._prepare_event_for_processing(event)
                if event_state == "skip_recent_outgoing_echo":
                    self._log_flow(
                        logging.INFO,
                        "EVENT.SKIP_ECHO",
                        event=event,
                        trace_id=trace_id,
                    )
                    return

                # 1. 记录日志
                log_text = message_log_override if message_log_override is not None else event.content
                message_log = format_log_text(log_text, self.log_message_content)
                self._log_flow(
                    logging.INFO,
                    "CONV.RECV",
                    event=event,
                    trace_id=trace_id,
                    event_state=event_state,
                    preview=message_log,
                )

                image_path = await self._maybe_save_event_image(
                    event,
                    trace_id=trace_id,
                )
                
                record_incoming_event(self.ipc, event)
                schedule_incoming_broadcast(self.bot_manager, event)


                # 2. 控制命令
                if self.bot_cfg.get("control_commands_enabled", True):
                    if await self._handle_control_command(wx, event, trace_id=trace_id):
                        return

                # 3. 响应检查 (暂停/静默)
                can_respond, quiet_reply = should_respond(self.bot_cfg)
                if not can_respond:
                    self._log_flow(
                        logging.INFO,
                        "EVENT.SKIP_RESPOND",
                        event=event,
                        trace_id=trace_id,
                        quiet_reply=bool(quiet_reply),
                    )
                    await maybe_send_quiet_reply(
                        wx=wx,
                        event=event,
                        quiet_reply=quiet_reply,
                        bot_cfg=self.bot_cfg,
                        wx_lock=self.wx_lock,
                    )
                    return

                should_handle, reason = should_reply_with_reason(
                    event,
                    self.config,
                    ignore_names_set=self.ignore_names_set,
                    ignore_keywords_list=self.ignore_keywords_list
                )
                if not should_handle:
                    self._log_flow(
                        logging.INFO,
                        "EVENT.SKIP_FILTERED",
                        event=event,
                        trace_id=trace_id,
                        reason=reason,
                        preview=message_log,
                    )
                    return

                # 4. 语音转文字
                if is_voice_message(event.msg_type) and user_text_override is None:
                    self._log_flow(
                        logging.INFO,
                        "VOICE.TRANSCRIBE_START",
                        event=event,
                        trace_id=trace_id,
                    )
                    voice_text, err = await transcribe_voice_message(event, self.bot_cfg, self.wx_lock)
                    if not voice_text:
                        self._log_flow(
                            logging.WARNING,
                            "VOICE.TRANSCRIBE_FAILED",
                            event=event,
                            trace_id=trace_id,
                            error=err,
                        )
                        fail_reply = str(self.bot_cfg.get("voice_to_text_fail_reply") or "").strip()
                        if fail_reply:
                            async with self.wx_lock:
                                await asyncio.to_thread(
                                    send_message, wx, event.chat_name, fail_reply, self.bot_cfg
                                )
                        return
                    event.content = voice_text
                    if message_log_override is None:
                        message_log = format_log_text(event.content, self.log_message_content)
                    self._log_flow(
                        logging.INFO,
                        "VOICE.TRANSCRIBE_DONE",
                        event=event,
                        trace_id=trace_id,
                        preview=message_log,
                    )

                # 5. 核心处理
                self._log_flow(
                    logging.INFO,
                    "EVENT.PROCESS_START",
                    event=event,
                    trace_id=trace_id,
                    user_text=self._message_preview(user_text_override or event.content),
                )
                await self._process_and_reply(
                    wx, 
                    event,
                    user_text_override or event.content,
                    message_log,
                    image_path=image_path,
                    trace_id=trace_id,
                )
                
            except Exception as exc:
                self._log_flow(
                    logging.ERROR,
                    "EVENT.FAILED",
                    event=event,
                    trace_id=trace_id,
                    error=str(exc),
                )
                logging.exception("消息处理异常: %s", exc)

    async def _handle_control_command(
        self,
        wx: BaseTransport,
        event: MessageEvent,
        trace_id: Optional[str] = None,
    ) -> bool:
        return await helper_handle_control_command(
            wx=wx,
            event=event,
            trace_id=trace_id,
            bot_cfg=self.bot_cfg,
            log_flow=self._log_flow,
            bot_manager=self.bot_manager,
            wx_lock=self.wx_lock,
        )

    async def _maybe_save_event_image(
        self,
        event: MessageEvent,
        *,
        trace_id: Optional[str] = None,
    ) -> Optional[str]:
        return await maybe_save_event_image(
            event,
            trace_id=trace_id,
            log_flow=self._log_flow,
        )

    async def _process_and_reply(
        self,
        wx: BaseTransport,
        event: MessageEvent,
        user_text: str,
        message_log: str,
        image_path: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        await helper_process_and_reply(
            self,
            wx,
            event,
            user_text,
            message_log,
            image_path=image_path,
            trace_id=trace_id,
        )

    def _mark_deadline_missed(
        self,
        prepared: Any,
        reply_deadline_sec: float,
        *,
        reason: str,
    ) -> None:
        helper_mark_deadline_missed(
            prepared,
            reply_deadline_sec,
            reason=reason,
        )

    def _schedule_delayed_reply(
        self,
        *,
        wx: BaseTransport,
        event: MessageEvent,
        prepared: Any,
        user_text: str,
        chat_id: str,
        trace_id: Optional[str],
        invoke_task: asyncio.Task,
        reply_deadline_sec: float,
    ) -> None:
        helper_schedule_delayed_reply(
            self,
            wx=wx,
            event=event,
            prepared=prepared,
            user_text=user_text,
            chat_id=chat_id,
            trace_id=trace_id,
            invoke_task=invoke_task,
            reply_deadline_sec=reply_deadline_sec,
        )

    async def _complete_delayed_reply(
        self,
        *,
        wx: BaseTransport,
        event: MessageEvent,
        prepared: Any,
        user_text: str,
        chat_id: str,
        trace_id: Optional[str],
        invoke_task: asyncio.Task,
        reply_deadline_sec: float,
    ) -> None:
        await helper_complete_delayed_reply(
            self,
            wx=wx,
            event=event,
            prepared=prepared,
            user_text=user_text,
            chat_id=chat_id,
            trace_id=trace_id,
            invoke_task=invoke_task,
            reply_deadline_sec=reply_deadline_sec,
        )

    async def _finalize_reply_delivery(
        self,
        *,
        prepared: Any,
        event: MessageEvent,
        chat_id: str,
        user_text: str,
        reply_text: str,
        trace_id: Optional[str],
        streamed: bool,
    ) -> str:
        return await helper_finalize_reply_delivery(
            self,
            prepared=prepared,
            event=event,
            chat_id=chat_id,
            user_text=user_text,
            reply_text=reply_text,
            trace_id=trace_id,
            streamed=streamed,
        )

    def _runtime_dependencies(self) -> Dict[str, Any]:
        return {
            "memory": self.memory,
            "vector_memory": self.vector_memory,
            "export_rag": self.export_rag,
        }

    def _sync_ai_runtime_dependencies(self) -> None:
        if self.ai_client and hasattr(self.ai_client, "update_runtime_dependencies"):
            result = self.ai_client.update_runtime_dependencies(self._runtime_dependencies())
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return
                loop.create_task(result)

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        lock = self.chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self.chat_locks[chat_id] = lock
        return lock

    async def _send_smart_reply(
        self,
        wx: BaseTransport,
        event: MessageEvent,
        reply_text: str,
        trace_id: Optional[str] = None,
    ) -> str:
        chunk_size = as_int(self.bot_cfg.get("reply_chunk_size", 500), 500)
        reply_deadline_sec = as_float(
            self.bot_cfg.get("reply_deadline_sec", 0.0),
            0.0,
            min_value=0.0,
        )
        fast_reply_mode = 0.0 < reply_deadline_sec <= 2.0
        delay_sec = 0.0 if fast_reply_mode else as_float(self.bot_cfg.get("reply_chunk_delay_sec", 0.0), 0.0)
        min_interval = 0.0 if fast_reply_mode else as_float(self.bot_cfg.get("min_reply_interval_sec", 0.2), 0.2)
        sanitized_reply = self._build_final_reply_text(reply_text)
        self._log_flow(
            logging.INFO,
            "SEND.PREPARE",
            event=event,
            trace_id=trace_id,
            reply=self._reply_preview(sanitized_reply or reply_text),
            natural_split=bool(self.bot_cfg.get("natural_split_enabled", False)),
        )
        if not sanitized_reply:
            logging.warning("回复内容清洗后为空，已跳过发送 | 会话=%s", event.chat_name)
            return ""

        # 即时回复模式下，统一走单次发送，避免分段策略拉长首包时间。
        natural_split_enabled = bool(self.bot_cfg.get("natural_split_enabled", False)) and not fast_reply_mode
        if natural_split_enabled:
            split_config = self._get_natural_split_config()
            segments = split_reply_naturally(
                sanitized_reply,
                min_chars=split_config["min_chars"],
                max_chars=split_config["max_chars"],
                max_segments=split_config["max_segments"],
            )
            for idx, seg in enumerate(segments):
                result = await send_reply_chunks(
                    wx, event.chat_name, seg, self.bot_cfg,
                    chunk_size, delay_sec, min_interval,
                    self.last_reply_ts, self.wx_lock,
                )
                if not result[0]:
                    self._log_flow(
                        logging.ERROR,
                        "CONV.SEND_FAILED",
                        event=event,
                        trace_id=trace_id,
                        reply=self._reply_preview(seg),
                        error=result[1],
                        segment_index=idx + 1,
                        segment_count=len(segments),
                    )
                self._ensure_send_succeeded(result, context="自然分段回复")
                self._log_flow(
                    logging.INFO,
                    "SEND.NATURAL_SEGMENT",
                    event=event,
                    trace_id=trace_id,
                    segment_index=idx + 1,
                    segment_count=len(segments),
                    reply=self._reply_preview(seg),
                )
                self._remember_recent_outgoing_message(
                    event.chat_name,
                    seg,
                    chunk_size=chunk_size,
                )
                if idx < len(segments) - 1 and split_config["delay_max"] > 0:
                    await asyncio.sleep(random.uniform(split_config["delay_min"], split_config["delay_max"]))
        else:
            result = await send_reply_chunks(
                wx, event.chat_name, sanitized_reply, self.bot_cfg,
                chunk_size, delay_sec, min_interval,
                self.last_reply_ts, self.wx_lock,
            )
            if not result[0]:
                self._log_flow(
                    logging.ERROR,
                    "CONV.SEND_FAILED",
                    event=event,
                    trace_id=trace_id,
                    reply=self._reply_preview(sanitized_reply),
                    error=result[1],
                )
            self._ensure_send_succeeded(result, context="回复")
            self._log_flow(
                logging.INFO,
                "CONV.SEND_DONE",
                event=event,
                trace_id=trace_id,
                reply=self._reply_preview(sanitized_reply),
            )
            self._remember_recent_outgoing_message(
                event.chat_name,
                sanitized_reply,
                chunk_size=chunk_size,
            )
        if self.bot_cfg.get("natural_split_enabled", False):
            self._log_flow(
                logging.INFO,
                "CONV.SEND_DONE",
                event=event,
                trace_id=trace_id,
                reply=self._reply_preview(sanitized_reply),
            )
        return sanitized_reply

    def _sanitize_reply_segment(self, reply_text: str) -> str:
        return helper_sanitize_reply_segment(self.bot_cfg, reply_text)

    def _build_reply_body_text(self, reply_text: str) -> str:
        return helper_build_reply_body_text(self.bot_cfg, reply_text)

    @staticmethod
    def _ensure_send_succeeded(result: Any, *, context: str) -> None:
        helper_ensure_send_succeeded(result, context=context)

    def _build_final_reply_text(self, reply_text: str) -> str:
        return helper_build_final_reply_text(self.bot_cfg, self.ai_client, reply_text)

    def _build_reply_suffix_text(self) -> str:
        return helper_build_reply_suffix_text(self.bot_cfg, self.ai_client)

    def _get_natural_split_config(self) -> Dict[str, float]:
        return helper_get_natural_split_config(self.bot_cfg)

    def _record_reply_stats(self, user_text: str, reply_text: str) -> None:
        state = get_bot_state()
        tokens = 0
        if self.bot_cfg.get("usage_tracking_enabled", True):
            _, _, tokens = estimate_exchange_tokens(self.ai_client, user_text, reply_text)
        state.add_reply(tokens)
        self.bot_manager._invalidate_status_cache()
        asyncio.create_task(self.bot_manager.notify_status_change())

    def _mark_reply_quality_dirty(self) -> None:
        self.bot_manager._invalidate_status_cache()

    def _record_reply_attempt(self) -> None:
        self.reply_quality_stats["attempted"] = int(self.reply_quality_stats.get("attempted", 0) or 0) + 1
        self._mark_reply_quality_dirty()

    def _record_reply_empty(self) -> None:
        self.reply_quality_stats["empty"] = int(self.reply_quality_stats.get("empty", 0) or 0) + 1
        try:
            self.reply_quality_tracker.log_event(outcome="empty")
        except Exception as exc:
            logging.warning("回复质量持久化失败(empty): %s", exc)
        self._notify_runtime_status_changed()

    def _record_reply_failure(self) -> None:
        self.reply_quality_stats["failed"] = int(self.reply_quality_stats.get("failed", 0) or 0) + 1
        try:
            self.reply_quality_tracker.log_event(outcome="failed")
        except Exception as exc:
            logging.warning("回复质量持久化失败(failed): %s", exc)
        self._notify_runtime_status_changed()

    def _record_reply_success(self, response_metadata: Optional[Dict[str, Any]] = None) -> None:
        metadata = dict(response_metadata or {})
        retrieval = dict(metadata.get("retrieval") or {})
        runtime_hit_count = as_int(retrieval.get("runtime_hit_count", 0), 0, min_value=0)
        retrieval_augmented = bool(retrieval.get("augmented"))

        self.reply_quality_stats["successful"] = int(self.reply_quality_stats.get("successful", 0) or 0) + 1
        if bool(metadata.get("delayed_reply")):
            self.reply_quality_stats["delayed"] = int(self.reply_quality_stats.get("delayed", 0) or 0) + 1
        if retrieval_augmented:
            self.reply_quality_stats["retrieval_augmented"] = (
                int(self.reply_quality_stats.get("retrieval_augmented", 0) or 0) + 1
            )
        if runtime_hit_count > 0:
            self.reply_quality_stats["retrieval_hit_count"] = (
                int(self.reply_quality_stats.get("retrieval_hit_count", 0) or 0) + runtime_hit_count
            )
        self.reply_quality_stats["last_reply_at"] = time.time()
        try:
            self.reply_quality_tracker.log_event(
                outcome="success",
                delayed=bool(metadata.get("delayed_reply")),
                retrieval_augmented=retrieval_augmented,
                retrieval_hit_count=runtime_hit_count,
            )
        except Exception as exc:
            logging.warning("回复质量持久化失败(success): %s", exc)
        self._mark_reply_quality_dirty()

    @staticmethod
    def _summarize_prepared_retrieval(prepared: Any) -> Dict[str, Any]:
        memory_context = list(getattr(prepared, "memory_context", []) or [])
        runtime_hit_count = 0
        export_rag_used = False

        for item in memory_context:
            if not isinstance(item, dict):
                continue
            runtime_hit_count += as_int(item.get("hit_count", 0), 0, min_value=0)
            content = str(item.get("content") or "").strip()
            if content.startswith("以下内容来自你与当前联系人的真实历史聊天"):
                export_rag_used = True

        return {
            "augmented": runtime_hit_count > 0 or export_rag_used,
            "runtime_hit_count": runtime_hit_count,
            "export_rag_used": export_rag_used,
        }

    def _build_reply_quality_status(self) -> Dict[str, Any]:
        attempted = int(self.reply_quality_stats.get("attempted", 0) or 0)
        successful = int(self.reply_quality_stats.get("successful", 0) or 0)
        empty = int(self.reply_quality_stats.get("empty", 0) or 0)
        failed = int(self.reply_quality_stats.get("failed", 0) or 0)
        delayed = int(self.reply_quality_stats.get("delayed", 0) or 0)
        retrieval_augmented = int(self.reply_quality_stats.get("retrieval_augmented", 0) or 0)
        retrieval_hit_count = int(self.reply_quality_stats.get("retrieval_hit_count", 0) or 0)
        helpful_count = int(self.reply_quality_stats.get("helpful_count", 0) or 0)
        unhelpful_count = int(self.reply_quality_stats.get("unhelpful_count", 0) or 0)
        success_rate = round((successful / attempted) * 100, 1) if attempted > 0 else 0.0
        history_24h: Dict[str, Any] = {}
        history_7d: Dict[str, Any] = {}
        try:
            summaries = self.reply_quality_tracker.get_recent_summaries()
            history_24h = dict(summaries.get("24h") or {})
            history_7d = dict(summaries.get("7d") or {})
        except Exception as exc:
            logging.warning("读取回复质量历史失败: %s", exc)

        if attempted <= 0:
            status_text = "回复质量：暂无样本"
        else:
            status_text = (
                f"回复成功率 {success_rate:.1f}%（{successful}/{attempted}），"
                f"空回复 {empty}，失败 {failed}，检索增强 {retrieval_augmented} 次"
            )

        return {
            "attempted": attempted,
            "successful": successful,
            "empty": empty,
            "failed": failed,
            "delayed": delayed,
            "retrieval_augmented": retrieval_augmented,
            "retrieval_hit_count": retrieval_hit_count,
            "helpful_count": helpful_count,
            "unhelpful_count": unhelpful_count,
            "success_rate": success_rate,
            "last_reply_at": self.reply_quality_stats.get("last_reply_at"),
            "status_text": status_text,
            "history_24h": history_24h,
            "history_7d": history_7d,
        }

    def apply_reply_feedback_change(
        self,
        previous_feedback: str,
        next_feedback: str,
    ) -> None:
        prev = str(previous_feedback or "").strip().lower()
        nxt = str(next_feedback or "").strip().lower()

        if prev == nxt:
            return
        if prev == "helpful":
            self.reply_quality_stats["helpful_count"] = max(
                0,
                int(self.reply_quality_stats.get("helpful_count", 0) or 0) - 1,
            )
        elif prev == "unhelpful":
            self.reply_quality_stats["unhelpful_count"] = max(
                0,
                int(self.reply_quality_stats.get("unhelpful_count", 0) or 0) - 1,
            )

        if nxt == "helpful":
            self.reply_quality_stats["helpful_count"] = int(
                self.reply_quality_stats.get("helpful_count", 0) or 0
            ) + 1
        elif nxt == "unhelpful":
            self.reply_quality_stats["unhelpful_count"] = int(
                self.reply_quality_stats.get("unhelpful_count", 0) or 0
            ) + 1

        self._notify_runtime_status_changed()

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

        metadata = dict(getattr(prepared, "response_metadata", {}) or {})
        retrieval_summary = self._summarize_prepared_retrieval(prepared)
        provider_id = str(getattr(self.ai_client, "provider_id", "") or "").strip().lower()
        if not provider_id:
            provider_id = infer_provider_id(
                provider_id=None,
                preset_name=self.runtime_preset_name,
                base_url=getattr(self.ai_client, "base_url", ""),
                model=str(getattr(self.ai_client, "model", "") or ""),
            ) or ""

        pricing_snapshot = None
        cost_snapshot = None
        source_url = ""
        price_verified_at = ""
        if provider_id and total_tokens > 0:
            pricing_snapshot = get_pricing_catalog().resolve_price(
                provider_id,
                str(getattr(self.ai_client, "model", "") or ""),
                prompt_tokens=user_tokens,
            )
            if pricing_snapshot:
                input_cost = round(
                    (user_tokens / 1_000_000) * float(pricing_snapshot.get("input_price_per_1m") or 0.0),
                    8,
                )
                output_cost = round(
                    (reply_tokens / 1_000_000) * float(pricing_snapshot.get("output_price_per_1m") or 0.0),
                    8,
                )
                cost_snapshot = {
                    "input_cost": input_cost,
                    "output_cost": output_cost,
                    "total_cost": round(input_cost + output_cost, 8),
                }
                source_url = str(pricing_snapshot.get("source_url") or "")
                price_verified_at = str(pricing_snapshot.get("price_verified_at") or "")

        metadata.update({
            "kind": "assistant_reply",
            "chat_id": chat_id,
            "chat_name": event.chat_name,
            "sender": event.sender,
            "preset": self.runtime_preset_name,
            "provider_id": provider_id,
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
            "pricing": pricing_snapshot,
            "cost": cost_snapshot,
            "estimated": {
                "tokens": False,
                "pricing": False,
            },
            "source_url": source_url,
            "price_verified_at": price_verified_at,
            "emotion": dict(getattr(prepared, "trace", {}).get("emotion") or {}) or None,
            "context_summary": dict(getattr(prepared, "trace", {}).get("context_summary") or {}),
            "profile": dict(getattr(prepared, "trace", {}).get("profile") or {}) or None,
            "retrieval": retrieval_summary,
        })
        return metadata

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
            "reply_quality": self._build_reply_quality_status(),
        }

    def _notify_runtime_status_changed(self) -> None:
        self.bot_manager._invalidate_status_cache()
        asyncio.create_task(self.bot_manager.notify_status_change())

    async def _execute_ipc_command(self, wx: BaseTransport, cmd: Dict) -> None:
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
                    self._remember_recent_outgoing_message(target, content)
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
            logging.info(
                build_stage_log_message(
                    "API_SEND.START",
                    target=target,
                    preview=self._reply_preview(content),
                )
            )
            async with self.wx_lock:
                ok, err_msg = await asyncio.to_thread(
                    send_message, self.wx, target, content, self.bot_cfg
                )
            if not ok:
                logging.error(
                    build_stage_log_message(
                        "API_SEND.FAILED",
                        target=target,
                        error=err_msg or "发送失败",
                    )
                )
                return {'success': False, 'message': err_msg or '发送失败'}
            
            self._remember_recent_outgoing_message(target, content)
            # 记录到 IPC/日志
            self.ipc.log_message("API", content, "outgoing", target)
            logging.info(
                build_stage_log_message(
                    "API_SEND.DONE",
                    target=target,
                    preview=self._reply_preview(content),
                )
            )

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
            logging.error(build_stage_log_message("API_SEND.ERROR", target=target, error=str(e)))
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
                "transport_backend": "wcferry",
                "silent_mode": True,
                "wechat_version": "",
                "required_wechat_version": "",
                "supports_native_quote": False,
                "supports_voice_transcription": True,
                "transport_status": "connected",
                "transport_warning": "",
            }
        return {
            "transport_backend": "wcferry",
            "silent_mode": True,
            "wechat_version": "",
            "required_wechat_version": str(
                self.bot_cfg.get("required_wechat_version") or ""
            ).strip(),
            "supports_native_quote": False,
            "supports_voice_transcription": True,
            "transport_status": "disconnected",
            "transport_warning": get_last_transport_error(),
        }

