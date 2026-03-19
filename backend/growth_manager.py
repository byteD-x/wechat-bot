from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from backend.core.export_rag import ExportChatRAG
from backend.core.factory import (
    get_last_ai_client_error,
    select_ai_client,
    select_specific_ai_client,
)
from backend.core.memory import MemoryManager
from backend.core.vector_memory import VectorMemory
from backend.shared_config import get_app_config_path
from backend.utils.common import as_float, get_file_mtime

logger = logging.getLogger(__name__)

SUPPORTED_GROWTH_TASK_TYPES = {
    "emotion",
    "contact_prompt",
    "vector_memory",
    "facts",
    "export_rag_sync",
}


class GrowthTaskManager:
    def __init__(self) -> None:
        from backend.core.config_service import get_config_service
        from backend.bot_manager import get_bot_manager

        self.config_service = get_config_service()
        self.bot_manager = get_bot_manager()
        self.config_path = get_app_config_path()
        self._lock = asyncio.Lock()

        self.is_running = False
        self.start_time: Optional[float] = None
        self.config_mtime: Optional[float] = None
        self.memory: Optional[MemoryManager] = None
        self.vector_memory: Optional[VectorMemory] = None
        self.export_rag: Optional[ExportChatRAG] = None
        self.ai_client: Optional[Any] = None
        self.runtime_preset_name: str = ""
        self._watch_task: Optional[asyncio.Task] = None

        self.config: Dict[str, Any] = {}
        self.bot_cfg: Dict[str, Any] = {}
        self.api_cfg: Dict[str, Any] = {}
        self.agent_cfg: Dict[str, Any] = {}
        self.services_cfg: Dict[str, Any] = {"growth_tasks_enabled": False}

    async def start(self, *, persist: bool = True, source: str = "manual") -> Dict[str, Any]:
        async with self._lock:
            if persist:
                snapshot = self.config_service.save_effective_config(
                    {"services": {"growth_tasks_enabled": True}},
                    config_path=self.config_path,
                    source=f"growth_start:{source}",
                )
            else:
                snapshot = self.config_service.get_snapshot(config_path=self.config_path, force_reload=True)

            if self.is_running:
                self._apply_snapshot(snapshot.to_dict())
                await self._notify_status_change()
                return {"success": True, "message": "成长任务已在运行", "already_running": True}

            try:
                await self._initialize_from_config(snapshot.to_dict())
            except Exception as exc:
                logger.warning("Failed to start growth task manager: %s", exc)
                await self._shutdown_components()
                self.is_running = False
                self.start_time = None
                await self._notify_status_change()
                return {"success": False, "message": f"成长任务启动失败: {exc}"}

            self.is_running = True
            self.start_time = time.time()
            self.config_mtime = get_file_mtime(self.config_path)
            self._ensure_watch_task()
            await self._notify_status_change()
            return {"success": True, "message": "成长任务已启动"}

    async def stop(self, *, persist: bool = True, source: str = "manual") -> Dict[str, Any]:
        async with self._lock:
            if persist:
                self.config_service.save_effective_config(
                    {"services": {"growth_tasks_enabled": False}},
                    config_path=self.config_path,
                    source=f"growth_stop:{source}",
                )
                self.services_cfg = {"growth_tasks_enabled": False}

            if not self.is_running:
                await self._notify_status_change()
                return {"success": True, "message": "成长任务已关闭", "already_stopped": True}

            await self._cancel_watch_task()
            await self._shutdown_components()
            self.is_running = False
            self.start_time = None
            self.runtime_preset_name = ""
            self.config_mtime = get_file_mtime(self.config_path)
            await self._notify_status_change()
            return {"success": True, "message": "成长任务已关闭"}

    async def reload_runtime_config(self, *, new_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        async with self._lock:
            config = dict(new_config or self.config_service.reload(config_path=self.config_path).to_dict())
            growth_enabled = bool((config.get("services") or {}).get("growth_tasks_enabled", False))
            if not growth_enabled:
                if self.is_running:
                    await self._cancel_watch_task()
                    await self._shutdown_components()
                    self.is_running = False
                    self.start_time = None
                    self.runtime_preset_name = ""
                self._apply_snapshot(config)
                await self._notify_status_change()
                return {"success": True, "message": "成长任务已禁用", "running": False}

            try:
                await self._initialize_from_config(config)
            except Exception as exc:
                logger.warning("Failed to reload growth task config: %s", exc)
                await self._notify_status_change()
                return {"success": False, "message": f"成长任务重载失败: {exc}", "running": self.is_running}

            self.is_running = True
            if self.start_time is None:
                self.start_time = time.time()
            self.config_mtime = get_file_mtime(self.config_path)
            self._ensure_watch_task()
            await self._notify_status_change()
            return {"success": True, "message": "成长任务配置已重载", "running": True}

    def get_status(self) -> Dict[str, Any]:
        runtime_status = {}
        runtime_controller = self._get_runtime_controller()
        if runtime_controller and hasattr(runtime_controller, "get_status"):
            try:
                runtime_status = dict(runtime_controller.get_status())
            except Exception:
                runtime_status = {}
        return {
            "growth_running": self.is_running,
            "growth_enabled": bool(self.services_cfg.get("growth_tasks_enabled", False)),
            "growth_uptime_sec": max(0.0, time.time() - self.start_time) if self.start_time else 0.0,
            "runtime_preset": self.runtime_preset_name,
            "growth_tasks_pending": int(runtime_status.get("growth_tasks_pending", 0) or 0),
            "last_growth_error": str(runtime_status.get("last_growth_error") or ""),
            "background_backlog_count": int(runtime_status.get("background_backlog_count", 0) or 0),
            "background_backlog_by_task": dict(runtime_status.get("background_backlog_by_task") or {}),
            "paused_growth_task_types": list(runtime_status.get("paused_growth_task_types") or []),
            "last_background_batch": dict(runtime_status.get("last_background_batch") or {}),
            "next_background_batch_at": runtime_status.get("next_background_batch_at"),
            "growth_mode": runtime_status.get("growth_mode", "deferred_until_batch"),
        }

    def _get_runtime_controller(self) -> Optional[Any]:
        if self.ai_client and hasattr(self.ai_client, "get_status"):
            return self.ai_client
        bot = getattr(self.bot_manager, "bot", None)
        bot_ai_client = getattr(bot, "ai_client", None)
        if bot_ai_client and hasattr(bot_ai_client, "get_status"):
            return bot_ai_client
        return None

    def _get_memory_controller(self) -> Optional[Any]:
        if self.memory is not None:
            return self.memory
        get_memory_manager = getattr(self.bot_manager, "get_memory_manager", None)
        if callable(get_memory_manager):
            try:
                return get_memory_manager()
            except Exception:
                return None
        return None

    def _normalize_task_type(self, task_type: str) -> str:
        normalized = str(task_type or "").strip()
        if normalized not in SUPPORTED_GROWTH_TASK_TYPES:
            raise ValueError(f"unsupported_task_type:{normalized or 'empty'}")
        return normalized

    async def list_growth_tasks(self) -> Dict[str, Any]:
        runtime_controller = self._get_runtime_controller()
        memory = self._get_memory_controller()
        if memory is None or not hasattr(memory, "get_background_backlog_stats"):
            return {"success": True, "tasks": []}

        stats = await memory.get_background_backlog_stats()
        backlog_by_task = dict(stats.get("by_task_type") or {})
        paused_task_types: set[str] = set()
        if runtime_controller and hasattr(runtime_controller, "get_status"):
            try:
                paused_task_types = set(
                    runtime_controller.get_status().get("paused_growth_task_types") or []
                )
            except Exception:
                paused_task_types = set()

        task_names = sorted(set(backlog_by_task.keys()) | paused_task_types)
        tasks = [
            {
                "task_type": task_type,
                "queued": int(backlog_by_task.get(task_type, 0) or 0),
                "paused": task_type in paused_task_types,
            }
            for task_type in task_names
        ]
        return {"success": True, "tasks": tasks}

    async def clear_growth_task(self, task_type: str) -> Dict[str, Any]:
        try:
            normalized_task_type = self._normalize_task_type(task_type)
        except ValueError:
            return {"success": False, "message": "不支持的成长任务类型", "task_type": str(task_type or "").strip()}
        runtime_controller = self._get_runtime_controller()
        if runtime_controller and hasattr(runtime_controller, "clear_background_backlog"):
            cleared = int(
                await runtime_controller.clear_background_backlog(task_type=normalized_task_type)
            )
        else:
            memory = self._get_memory_controller()
            if memory is None or not hasattr(memory, "list_background_backlog"):
                return {"success": False, "message": "成长任务队列不可用"}
            items = await memory.list_background_backlog()
            cleared = 0
            for item in items or []:
                if str(item.get("task_type") or "").strip() != normalized_task_type:
                    continue
                await memory.delete_background_backlog(
                    str(item.get("chat_id") or "").strip(),
                    normalized_task_type,
                )
                cleared += 1
        await self._notify_status_change()
        return {
            "success": True,
            "message": f"已清空 {cleared} 个任务",
            "task_type": normalized_task_type,
            "cleared": cleared,
        }

    async def run_growth_task_now(self, task_type: str) -> Dict[str, Any]:
        try:
            normalized_task_type = self._normalize_task_type(task_type)
        except ValueError:
            return {"success": False, "message": "不支持的成长任务类型", "task_type": str(task_type or "").strip()}
        runtime_controller = self._get_runtime_controller()
        if runtime_controller is None or not hasattr(runtime_controller, "run_background_backlog_now"):
            return {"success": False, "message": "当前没有可用的成长任务运行时"}
        result = await runtime_controller.run_background_backlog_now(task_type=normalized_task_type)
        await self._notify_status_change()
        success = bool((result or {}).get("success", True))
        return {
            "success": success,
            "message": "已触发立即执行" if success else "立即执行失败",
            "task_type": normalized_task_type,
            "result": dict(result or {}),
        }

    async def pause_growth_task(self, task_type: str) -> Dict[str, Any]:
        try:
            normalized_task_type = self._normalize_task_type(task_type)
        except ValueError:
            return {"success": False, "message": "不支持的成长任务类型", "task_type": str(task_type or "").strip()}
        runtime_controller = self._get_runtime_controller()
        if runtime_controller is None or not hasattr(runtime_controller, "pause_background_task_type"):
            return {"success": False, "message": "当前没有可用的成长任务运行时"}
        paused_task_types = runtime_controller.pause_background_task_type(normalized_task_type)
        await self._notify_status_change()
        return {
            "success": True,
            "message": "该类任务已暂停",
            "task_type": normalized_task_type,
            "paused_growth_task_types": list(paused_task_types or []),
        }

    async def resume_growth_task(self, task_type: str) -> Dict[str, Any]:
        try:
            normalized_task_type = self._normalize_task_type(task_type)
        except ValueError:
            return {"success": False, "message": "不支持的成长任务类型", "task_type": str(task_type or "").strip()}
        runtime_controller = self._get_runtime_controller()
        if runtime_controller is None or not hasattr(runtime_controller, "resume_background_task_type"):
            return {"success": False, "message": "当前没有可用的成长任务运行时"}
        paused_task_types = runtime_controller.resume_background_task_type(normalized_task_type)
        await self._notify_status_change()
        return {
            "success": True,
            "message": "该类任务已恢复",
            "task_type": normalized_task_type,
            "paused_growth_task_types": list(paused_task_types or []),
        }

    def _apply_snapshot(self, config: Dict[str, Any]) -> None:
        self.config = dict(config or {})
        self.api_cfg = dict(self.config.get("api") or {})
        self.bot_cfg = dict(self.config.get("bot") or {})
        self.agent_cfg = dict(self.config.get("agent") or {})
        self.services_cfg = dict(self.config.get("services") or {"growth_tasks_enabled": False})

    async def _initialize_from_config(self, config: Dict[str, Any]) -> None:
        self._apply_snapshot(config)
        await self._shutdown_components()

        db_path = (
            self.bot_cfg.get("memory_db_path")
            or self.bot_cfg.get("sqlite_db_path")
            or "data/chat_memory.db"
        )
        self.memory = MemoryManager(
            db_path,
            ttl_sec=self.bot_cfg.get("memory_ttl_sec"),
            cleanup_interval_sec=float(self.bot_cfg.get("memory_cleanup_interval_sec", 0.0) or 0.0),
        )
        initialize_memory = getattr(self.memory, "initialize", None)
        if callable(initialize_memory):
            maybe_result = initialize_memory()
            if asyncio.iscoroutine(maybe_result):
                await maybe_result

        if self._vector_memory_requested():
            self.vector_memory = VectorMemory()
            self.export_rag = ExportChatRAG(self.vector_memory)
            self.export_rag.update_config(self.bot_cfg)
        else:
            self.vector_memory = None
            self.export_rag = None

        growth_agent_cfg = dict(self.agent_cfg)
        growth_agent_cfg["enabled"] = True
        active_preset = str(self.api_cfg.get("active_preset") or "").strip()
        if active_preset:
            client, preset_name = await select_specific_ai_client(
                self.api_cfg,
                self.bot_cfg,
                active_preset,
                growth_agent_cfg,
            )
        else:
            client, preset_name = await select_ai_client(self.api_cfg, self.bot_cfg, growth_agent_cfg)
        if not client:
            raise RuntimeError(get_last_ai_client_error() or "未找到可用的 AI 预设")
        if not hasattr(client, "update_runtime_dependencies"):
            if hasattr(client, "close"):
                await client.close()
            raise RuntimeError("当前配置未启用可用的成长任务运行时")

        self.ai_client = client
        self.runtime_preset_name = preset_name or active_preset
        self.ai_client.update_runtime_dependencies(self._runtime_dependencies())

    def _runtime_dependencies(self) -> Dict[str, Any]:
        return {
            "memory": self.memory,
            "vector_memory": self.vector_memory,
            "export_rag": self.export_rag,
        }

    def _vector_memory_requested(self) -> bool:
        if not bool(self.bot_cfg.get("vector_memory_enabled", True)):
            return False
        return bool(
            self.bot_cfg.get("rag_enabled", False)
            or self.bot_cfg.get("export_rag_enabled", False)
        )

    def _ensure_watch_task(self) -> None:
        if self._watch_task and not self._watch_task.done():
            return
        self._watch_task = asyncio.create_task(self._watch_loop())

    async def _cancel_watch_task(self) -> None:
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            await asyncio.gather(self._watch_task, return_exceptions=True)
        self._watch_task = None

    async def _watch_loop(self) -> None:
        try:
            while True:
                interval = max(
                    0.5,
                    as_float(self.bot_cfg.get("config_reload_sec", 2.0), 2.0, min_value=0.0),
                )
                await asyncio.sleep(interval)
                next_mtime = get_file_mtime(self.config_path)
                if next_mtime == self.config_mtime:
                    continue
                self.config_mtime = next_mtime
                await self.reload_runtime_config()
        except asyncio.CancelledError:
            raise

    async def _shutdown_components(self) -> None:
        if self.ai_client and hasattr(self.ai_client, "close"):
            await self.ai_client.close()
        self.ai_client = None
        if self.memory and hasattr(self.memory, "close"):
            await self.memory.close()
        self.memory = None
        self.vector_memory = None
        self.export_rag = None

    async def _notify_status_change(self) -> None:
        self.bot_manager._invalidate_status_cache()
        await self.bot_manager.notify_status_change()


_GROWTH_TASK_MANAGER: Optional[GrowthTaskManager] = None


def get_growth_manager() -> GrowthTaskManager:
    global _GROWTH_TASK_MANAGER
    if _GROWTH_TASK_MANAGER is None:
        _GROWTH_TASK_MANAGER = GrowthTaskManager()
    return _GROWTH_TASK_MANAGER
