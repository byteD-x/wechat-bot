import asyncio
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .core.ai_client import AIClient
from .core.export_rag import ExportChatRAG
from .core.memory import MemoryManager
from .core.vector_memory import VectorMemory # 新增
from .core.emotion import (
    EmotionResult,
    detect_emotion_keywords,
    get_emotion_analysis_prompt,
    parse_emotion_ai_response,
    get_fact_extraction_prompt,
    parse_fact_extraction_response,
    get_relationship_evolution_hint,
)
from .core.bot_control import (
    parse_control_command,
    is_command_message,
    should_respond,
)
from .core.factory import (
    select_ai_client,
    select_specific_ai_client,
    get_reconnect_policy,
    reconnect_wechat,
    apply_ai_runtime_settings,
    compute_api_signature,
    reload_ai_module,
)

from .types import MessageEvent, ReconnectPolicy
from .handlers.filter import should_reply
from .handlers.sender import send_message, send_reply_chunks
from .handlers.converters import normalize_new_messages
from .utils.common import as_float, as_int, get_file_mtime, iter_items
from .utils.config import load_config, get_model_alias, resolve_system_prompt
from .utils.logging import (
    setup_logging,
    get_logging_settings,
    get_log_behavior,
    format_log_text,
)
from .utils.message import (
    is_voice_message,
    build_reply_suffix,
    refine_reply_text,
    sanitize_reply_text,
    split_reply_naturally,
    STREAM_PUNCTUATION,
)
from .utils.config import get_model_alias
from .utils.tools import transcribe_voice_message, estimate_exchange_tokens
from .utils.ipc import IPCManager


from .bot_manager import get_bot_manager

class WeChatBot:
    def __init__(self, config_path: str, memory_manager: Optional[MemoryManager] = None):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.bot_cfg: Dict[str, Any] = {}
        self.api_cfg: Dict[str, Any] = {}
        self.ai_client: Optional[AIClient] = None
        self.memory: Optional[MemoryManager] = memory_manager
        self.vector_memory: Optional[VectorMemory] = None # 向量记忆
        self.export_rag: Optional[ExportChatRAG] = None
        self.export_rag_sync_task: Optional[asyncio.Task] = None
        self.wx_lock = asyncio.Lock()
        self.sem: Optional[asyncio.Semaphore] = None
        self.ipc = IPCManager()  # IPC 管理器
        self.bot_manager = get_bot_manager() # 获取 BotManager 实例以广播事件

        self.last_reply_ts: Dict[str, float] = {"ts": 0.0}
        self.pending_tasks: Set[asyncio.Task] = set()
        
        # 合并消息状态
        self.pending_merge_messages: Dict[str, List[str]] = {}
        self.pending_merge_events: Dict[str, MessageEvent] = {}
        self.pending_merge_first_event: Dict[str, MessageEvent] = {}
        self.pending_merge_tasks: Dict[str, asyncio.Task] = {}
        self.pending_merge_first_ts: Dict[str, float] = {}
        self.pending_merge_lock = asyncio.Lock()

        # 配置监控
        self.config_mtime: Optional[float] = None
        self.ai_module_mtime: Optional[float] = None
        self.api_signature: str = ""
        self.runtime_preset_name: str = ""
        
        # 日志标志
        self.log_message_content: bool = True
        self.log_reply_content: bool = True
        
        # 停止事件（由 BotManager 注入或自行创建）
        self._stop_event: Optional[asyncio.Event] = None
        self._is_paused: bool = False

        # 缓存的过滤配置
        self.ignore_names_set: Set[str] = set()
        self.ignore_keywords_list: List[str] = []

    async def initialize(self) -> Optional["WeChat"]:
        try:
            self.config_mtime = get_file_mtime(self.config_path)
            self.config = load_config(self.config_path)
        except Exception as exc:
            logging.error("无法加载配置文件: %s", exc)
            return None

        self._apply_config()
        
        # 初始化记忆模块
        if self.memory is None:
            db_path = self.bot_cfg.get("memory_db_path") or self.bot_cfg.get("sqlite_db_path") or "data/chat_memory.db"
            self.memory = MemoryManager(db_path)

        self._ensure_vector_memory()
        
        # 初始化 AI 客户端
        self.ai_client, preset_name = await select_ai_client(self.api_cfg, self.bot_cfg)
        if self.ai_client:
            self.api_signature = compute_api_signature(self.api_cfg)
            self.runtime_preset_name = preset_name or ""
            logging.info("AI 客户端初始化成功，使用预设: %s", preset_name)
            await self._schedule_export_rag_sync(force=False)
        else:
            logging.warning("AI 客户端初始化失败，未能选择有效预设")

        # 初始化微信客户端
        reconnect_policy = get_reconnect_policy(self.bot_cfg)
        self.wx = await reconnect_wechat("初始化", reconnect_policy)
        if self.wx is None:
            logging.error("微信初始化失败")
            return None
            
        return self.wx

    def _apply_config(self) -> None:
        self.bot_cfg = self.config.get("bot", {})
        self.api_cfg = self.config.get("api", {})
        
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
                if config_reload_sec > 0 and now - config_check_ts >= config_reload_sec:
                    config_check_ts = now
                    await self._check_config_reload(now)
                    # 更新本地变量以适应配置变更
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
                    wx = await reconnect_wechat("keepalive 超时", reconnect_policy)
                    if wx is None:
                        await asyncio.sleep(reconnect_policy.base_delay_sec)
                        continue
                    last_poll_ok_ts = time.time()

                # 轮询消息
                try:
                    async with self.wx_lock:
                        raw = await asyncio.to_thread(
                            wx.GetNextNewMessage,
                            filter_mute=bool(self.bot_cfg.get("filter_mute", False)),
                        )
                    last_poll_ok_ts = time.time()
                except Exception as exc:
                    logging.exception("获取消息异常：%s", exc)
                    reconnect_policy = get_reconnect_policy(self.bot_cfg)
                    wx = await reconnect_wechat("GetNextNewMessage 异常", reconnect_policy)
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
                    self.pending_tasks.add(task)
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

    async def _check_config_reload(self, now: float) -> None:
        # Check main config file
        new_mtime = get_file_mtime(self.config_path)
        
        # Check override file
        override_path = os.path.join("data", "config_override.json")
        new_override_mtime = get_file_mtime(override_path)
        
        should_reload = False
        
        if new_mtime and new_mtime != self.config_mtime:
            should_reload = True
            self.config_mtime = new_mtime
            
        # Also reload if override file changed (or was created/deleted)
        # Note: get_file_mtime returns None if file doesn't exist
        last_override_mtime = getattr(self, "override_mtime", None)
        if new_override_mtime != last_override_mtime:
            should_reload = True
            self.override_mtime = new_override_mtime

        if should_reload:
            try:
                new_config = load_config(self.config_path)
            except Exception as exc:
                logging.warning("配置重载失败: %s", exc)
                return

            self.config = new_config
            self._apply_config()
            self._ensure_vector_memory()
            
            # 重新检查 AI 客户端
            if self.bot_cfg.get("reload_ai_client_on_change", True):
                new_signature = compute_api_signature(self.api_cfg)
                if new_signature != self.api_signature:
                    new_client, new_preset = await select_ai_client(self.api_cfg, self.bot_cfg)
                    if new_client:
                        if self.ai_client and hasattr(self.ai_client, "close"):
                            await self.ai_client.close()
                        self.ai_client = new_client
                        self.api_signature = new_signature
                        self.runtime_preset_name = new_preset or ""
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
        new_signature = compute_api_signature(self.api_cfg)
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
                self.api_cfg, self.bot_cfg, active_preset
            )
        else:
            new_client, new_preset = await select_ai_client(self.api_cfg, self.bot_cfg)

        if not new_client:
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.warning("导出语料 RAG 同步失败: %s", exc)

    def get_export_rag_status(self) -> Dict[str, Any]:
        if not self.export_rag:
            return {
                "enabled": bool(self.bot_cfg.get("export_rag_enabled", False)),
                "base_dir": str(self.bot_cfg.get("export_rag_dir") or ""),
                "auto_ingest": bool(self.bot_cfg.get("export_rag_auto_ingest", True)),
                "indexed_contacts": 0,
                "indexed_chunks": 0,
                "last_scan_at": None,
                "last_scan_summary": {},
            }
        return self.export_rag.get_status()

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
            self.pending_tasks.add(task)
            task.add_done_callback(self.pending_tasks.discard)

    async def wait_and_reply(self, wx: "WeChat", chat_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        async with self.pending_merge_lock:
            messages = self.pending_merge_messages.pop(chat_id, [])
            event = self.pending_merge_events.pop(chat_id, None)
            first_event = self.pending_merge_first_event.pop(chat_id, None)
            self.pending_merge_tasks.pop(chat_id, None)
            self.pending_merge_first_ts.pop(chat_id, None)
        
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
                if event.msg_type == 1 and "[图片]" in event.content:
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
        
        # 记忆与上下文
        memory_context = []
        user_profile = None
        
        if self.memory:
            await self.memory.add_message(chat_id, "user", user_text)
            
            if self.bot_cfg.get("personalization_enabled", False):
                user_profile = await self.memory.get_user_profile(chat_id)
                await self.memory.increment_message_count(chat_id)

            limit = as_int(self.bot_cfg.get("memory_context_limit", 5), 5)
            if limit > 0:
                memory_context = await self.memory.get_recent_context(chat_id, limit)

            if self.export_rag and self.ai_client:
                export_results = await self.export_rag.search(
                    self.ai_client,
                    chat_id,
                    user_text,
                )
                export_message = self.export_rag.build_memory_message(export_results)
                if export_message:
                    memory_context.insert(0, export_message)

            # RAG 检索
            if self.vector_memory and self.ai_client:
                # 只有当用户输入较长或看起来像问题时才检索，节省开销
                if len(user_text) > 5 or "?" in user_text or "？" in user_text:
                    embedding = await self.ai_client.get_embedding(user_text)
                    results = await asyncio.to_thread(
                        self.vector_memory.search,
                        query=user_text if not embedding else None,
                        n_results=3,
                        filter_meta={"chat_id": chat_id, "source": "runtime_chat"},
                        query_embedding=embedding
                    )
                    if results:
                        rag_context = "\n".join([r['text'] for r in results])
                        logging.info(f"RAG 命中 [{chat_id}]: {len(results)} 条")
                        # 将 RAG 结果作为 System Message 注入
                        memory_context.insert(0, {
                            "role": "system",
                            "content": f"Relevant past memories:\n{rag_context}"
                        })

        # 情感分析
        current_emotion = None
        if self.bot_cfg.get("emotion_detection_enabled", False):
            current_emotion = await self._analyze_emotion(chat_id, user_text)
            if self.memory and current_emotion:
                await self.memory.update_emotion(chat_id, current_emotion.emotion)

        # 系统提示词
        system_prompt = resolve_system_prompt(
            event, self.bot_cfg, user_profile, current_emotion, memory_context
        )
        
        # 生成回复
        if not self.ai_client:
            return

        reply_text = await self.ai_client.generate_reply(
            chat_id, user_text, system_prompt, memory_context, image_path=image_path
        )
        
        try:
            if not reply_text:
                return

            # 后处理与发送
            await self._send_smart_reply(wx, event, reply_text)
        
            # IPC 记录出口消息
            self.ipc.log_message("Bot", reply_text, "outgoing", event.sender)
        
            # 广播事件
            asyncio.create_task(self.bot_manager.broadcast_event("message", {
                "direction": "outgoing",
                "sender": "Bot",
                "content": reply_text,
                "recipient": event.sender,
                "timestamp": time.time()
            }))
        
            # 更新记忆（助手）
            if self.memory:
                await self.memory.add_message(chat_id, "assistant", reply_text)
                
            # 异步更新向量数据库
            if self.vector_memory:
                asyncio.create_task(self._update_vector_db(chat_id, user_text, reply_text))

            # 事实提取（后台）
            if user_profile and self.bot_cfg.get("remember_facts_enabled", False):
                # 发后即忘的任务
                asyncio.create_task(
                    self._extract_facts_background(chat_id, user_text, reply_text, user_profile)
                )
        finally:
            if image_path and os.path.exists(image_path):
                await asyncio.to_thread(os.remove, image_path)

    async def _analyze_emotion(self, chat_id: str, text: str) -> Optional[EmotionResult]:
        mode = str(self.bot_cfg.get("emotion_detection_mode", "keywords")).lower()
        if mode == "ai" and self.ai_client:
            prompt = get_emotion_analysis_prompt(text)
            resp = await self.ai_client.generate_reply(
                f"__emotion__{chat_id}", 
                prompt,
                system_prompt="你是一个情感分析助手，只返回 JSON 格式的分析结果。"
            )
            if resp:
                result = parse_emotion_ai_response(resp)
                if result:

                    return result
        
        return detect_emotion_keywords(text)

    async def _update_vector_db(self, chat_id: str, user_text: str, reply_text: str) -> None:
        """后台更新向量数据库"""
        try:
            if not self.vector_memory:
                return

            user_embedding = None
            reply_embedding = None
            if self.ai_client:
                user_embedding = await self.ai_client.get_embedding(user_text)
                reply_embedding = await self.ai_client.get_embedding(reply_text)

            await asyncio.to_thread(
                self.vector_memory.add_text,
                user_text,
                metadata={
                    "chat_id": chat_id,
                    "role": "user",
                    "timestamp": time.time(),
                    "source": "runtime_chat",
                },
                id=f"{chat_id}_u_{time.time()}",
                embedding=user_embedding
            )
            
            await asyncio.to_thread(
                self.vector_memory.add_text,
                reply_text,
                metadata={
                    "chat_id": chat_id,
                    "role": "assistant",
                    "timestamp": time.time(),
                    "source": "runtime_chat",
                },
                id=f"{chat_id}_a_{time.time()}",
                embedding=reply_embedding
            )
        except Exception as e:
            logging.error(f"Vector DB update failed: {e}")

    async def _extract_facts_background(
        self, chat_id: str, user_text: str, assistant_reply: str, user_profile: Any
    ) -> None:
        """后台异步提取事实"""
        try:
            if not self.ai_client:
                return

            existing_facts = user_profile.context_facts
            prompt = get_fact_extraction_prompt(user_text, assistant_reply, existing_facts)
            
            # 使用 AI 分析
            resp = await self.ai_client.generate_reply(
                f"__facts__{chat_id}",
                prompt,
                system_prompt="你是一个信息提取助手，只返回 JSON 格式的结果。"
            )
            
            if not resp:
                return
                
            new_facts, relationship_hint, traits = parse_fact_extraction_response(resp)
            
            if not self.memory:
                return
                
            # 1. 保存新事实
            if new_facts:
                for fact in new_facts:
                    await self.memory.add_context_fact(chat_id, fact)
                logging.info(f"提取到新事实 [{chat_id}]: {new_facts}")
            
            # 2. 更新性格特征
            if traits:
                current_traits = user_profile.personality
                # 简单追加，实际可能需要更复杂的合并逻辑
                updated_traits = f"{current_traits} {','.join(traits)}".strip()
                # 限制长度防止无限增长
                if len(updated_traits) > 200:
                    updated_traits = updated_traits[-200:]
                await self.memory.update_user_profile(chat_id, personality=updated_traits)
            
            # 3. 关系演进（结合互动次数）
            if relationship_hint:
                # AI 建议的关系
                # 这里可以加个逻辑：只有当 AI 建议的关系比当前关系更"亲密"时才更新
                # 或者简单信任 AI
                pass
            
            # 基于规则的关系演进
            msg_count = user_profile.message_count
            current_rel = user_profile.relationship
            new_rel = get_relationship_evolution_hint(msg_count, current_rel)
            
            if new_rel and new_rel != current_rel:
                await self.memory.update_user_profile(chat_id, relationship=new_rel)
                logging.info(f"关系升级 [{chat_id}]: {current_rel} -> {new_rel}")
                
        except Exception as e:
            logging.error(f"事实提取任务失败: {e}")
        


    async def _send_smart_reply(self, wx: "WeChat", event: MessageEvent, reply_text: str) -> None:
        chunk_size = as_int(self.bot_cfg.get("reply_chunk_size", 500), 500)
        delay_sec = as_float(self.bot_cfg.get("reply_chunk_delay_sec", 0.0), 0.0)
        min_interval = as_float(self.bot_cfg.get("min_reply_interval_sec", 0.2), 0.2)
        
        emoji_policy = str(self.bot_cfg.get("emoji_policy", "wechat"))
        replacements = self.bot_cfg.get("emoji_replacements")
        
        refined_reply = refine_reply_text(reply_text)
        sanitized_reply = sanitize_reply_text(refined_reply, emoji_policy, replacements)
        reply_suffix = str(self.bot_cfg.get("reply_suffix") or "").strip()
        if reply_suffix:
            model_name = ""
            if self.ai_client:
                model_name = getattr(self.ai_client, "model", "") or ""
            alias = get_model_alias(self.ai_client)
            suffix = build_reply_suffix(reply_suffix, model_name, alias)
            sanitized_reply = f"{sanitized_reply}{suffix}"

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
                "sender": "API",
                "content": content,
                "recipient": target,
                "timestamp": time.time()
            }))
            
            # 记录到记忆
            if self.memory:
                # 尝试猜测 chat_id
                # 注意：这里 target 可能是昵称，memory 需要 wx_id
                # 暂时存 target，或者如果 access memory 失败也无所谓
                # 更好的做法是 bot 内部维护 target -> wx_id 映射，但现在没有
                # 先简单记录为 target
                chat_id = target
                # Check if group
                # logic to detect group vs friend is tricky without wx object details
                # Assume friend for now or just log
                await self.memory.add_message(chat_id, "assistant", content)

            return {'success': True, 'message': '发送成功'}
        except Exception as e:
            logging.error(f"消息发送失败: {e}")
            return {'success': False, 'message': f'发送失败: {str(e)}'}

