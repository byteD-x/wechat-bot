"""
机器人生命周期管理器

提供机器人的启动、停止、暂停、恢复等生命周期管理功能。
使用单例模式确保全局唯一实例。
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


class BotManager:
    """
    机器人生命周期管理器（单例）
    
    负责管理 WeChatBot 实例的完整生命周期，包括：
    - 启动和停止
    - 暂停和恢复
    - 状态查询
    - 资源清理
    """
    
    _instance: Optional['BotManager'] = None
    _lock = asyncio.Lock()
    
    def __new__(cls) -> 'BotManager':
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
        self.stats = {
            'today_replies': 0,
            'today_tokens': 0,
            'total_replies': 0
        }

        self._status_cache: Optional[Dict[str, Any]] = None
        self._status_cache_time: float = 0.0
        self._status_cache_ttl: float = 0.5
        self._stats_cache: Optional[Dict[str, Any]] = None
        self._stats_cache_time: float = 0.0
        self._stats_cache_ttl: float = 2.0
        
        # 共享组件
        self.memory_manager = None
        
        # 配置路径
        self.config_path = os.path.join(
            os.path.dirname(__file__), 'config.py'
        )
        
        logger.info("BotManager 初始化完成")
    
    @classmethod
    def get_instance(cls) -> 'BotManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def get_memory_manager(self):
        """获取或初始化共享记忆管理器"""
        if self.memory_manager is None:
            from backend.config import CONFIG
            from backend.core.memory import MemoryManager
            bot_cfg = CONFIG.get('bot', {})
            db_path = bot_cfg.get('memory_db_path') or bot_cfg.get('sqlite_db_path') or 'data/chat_memory.db'
            self.memory_manager = MemoryManager(db_path)
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
                return {'success': False, 'message': '机器人已在运行'}
            
            try:
                from backend.bot import WeChatBot
                import time
                
                # 使用提供的配置路径或默认路径
                path = config_path or self.config_path
                
                # 重置停止事件
                self.stop_event.clear()
                
                # 创建机器人实例
                self.bot = WeChatBot(path, memory_manager=self.get_memory_manager())
                
                # 注入停止事件（让 bot 可以检查是否需要停止）
                self.bot._stop_event = self.stop_event
                
                # 创建运行任务
                self.task = asyncio.create_task(self._run_bot())
                
                self.is_running = True
                self.is_paused = False
                self.start_time = time.time()
                self._invalidate_status_cache()
                
                logger.info("机器人启动成功")
                return {'success': True, 'message': '机器人已启动'}
                
            except Exception as e:
                logger.error(f"机器人启动失败: {e}")
                self.is_running = False
                self.bot = None
                self.task = None
                self._invalidate_status_cache()
                return {'success': False, 'message': f'启动失败: {str(e)}'}
    
    async def _run_bot(self):
        """内部运行逻辑"""
        try:
            await self.bot.run()
        except asyncio.CancelledError:
            logger.info("机器人任务被取消")
        except Exception as e:
            logger.error(f"机器人运行错误: {e}")
        finally:
            self.is_running = False
            self.start_time = None
            self._invalidate_status_cache()
            logger.info("机器人已停止")
    
    async def stop(self) -> Dict[str, Any]:
        """
        停止机器人
        
        Returns:
            包含 success 和 message 的字典
        """
        async with self._lock:
            if not self.is_running:
                return {'success': False, 'message': '机器人未在运行'}
            
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
                    if hasattr(self.bot, 'shutdown'):
                        await self.bot.shutdown()
                    self.bot = None
                
                self.task = None
                self.is_running = False
                self.is_paused = False
                self.start_time = None
                self._invalidate_status_cache()
                
                logger.info("机器人停止成功")
                return {'success': True, 'message': '机器人已停止'}
                
            except Exception as e:
                logger.error(f"停止机器人失败: {e}")
                return {'success': False, 'message': f'停止失败: {str(e)}'}
    
    async def pause(self) -> Dict[str, Any]:
        """暂停机器人"""
        if not self.is_running:
            return {'success': False, 'message': '机器人未在运行'}
        
        if self.is_paused:
            return {'success': False, 'message': '机器人已暂停'}
        
        self.is_paused = True
        self._invalidate_status_cache()
        
        # 通知 bot 暂停（如果支持）
        if self.bot and hasattr(self.bot, 'pause'):
            self.bot.pause()
        
        logger.info("机器人已暂停")
        return {'success': True, 'message': '机器人已暂停'}
    
    async def resume(self) -> Dict[str, Any]:
        """恢复机器人"""
        if not self.is_running:
            return {'success': False, 'message': '机器人未在运行'}
        
        if not self.is_paused:
            return {'success': False, 'message': '机器人未暂停'}
        
        self.is_paused = False
        self._invalidate_status_cache()
        
        # 通知 bot 恢复（如果支持）
        if self.bot and hasattr(self.bot, 'resume'):
            self.bot.resume()
        
        logger.info("机器人已恢复")
        return {'success': True, 'message': '机器人已恢复'}
    
    async def restart(self) -> Dict[str, Any]:
        """重启机器人"""
        await self.stop()
        return await self.start()

    async def reload_runtime_config(
        self,
        *,
        new_config: Optional[Dict[str, Any]] = None,
        force_ai_reload: bool = False,
        strict_active_preset: bool = False,
    ) -> Dict[str, Any]:
        """
        立即将最新配置应用到运行中的机器人。
        """
        if not self.is_running or not self.bot:
            return {'success': False, 'message': '机器人未运行，无法立即切换', 'skipped': True}

        if not hasattr(self.bot, 'reload_runtime_config'):
            return {'success': False, 'message': '当前机器人实例不支持立即重载', 'skipped': True}

        return await self.bot.reload_runtime_config(
            new_config=new_config,
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
             return {'success': False, 'message': '机器人未运行'}
             
        if self.is_paused:
             return {'success': False, 'message': '机器人已暂停'}
             
        if hasattr(self.bot, 'send_text_message'):
             return await self.bot.send_text_message(target, content)
        
        return {'success': False, 'message': '机器人实例不支持发送消息'}

    def get_usage(self) -> Dict[str, Any]:
        """获取使用统计"""
        return self._get_stats()

    def _get_stats(self) -> Dict[str, Any]:
        import time

        now = time.time()
        if self._stats_cache and (now - self._stats_cache_time) < self._stats_cache_ttl:
            return dict(self._stats_cache)

        stats = self.stats.copy()
        if self.bot and hasattr(self.bot, 'get_stats'):
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
        import time

        now = time.time()
        if self._status_cache and (now - self._status_cache_time) < self._status_cache_ttl:
            return dict(self._status_cache)
        
        uptime = '--'
        if self.is_running and self.start_time:
            elapsed = int(time.time() - self.start_time)
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        # 尝试从 bot 获取统计数据
        stats = self._get_stats()
        
        status = {
            'running': self.is_running,
            'is_paused': self.is_paused,
            'uptime': uptime,
            'today_replies': stats.get('today_replies', 0),
            'today_tokens': stats.get('today_tokens', 0),
            'total_replies': stats.get('total_replies', 0)
        }
        if self.bot and hasattr(self.bot, 'get_export_rag_status'):
            try:
                status['export_rag'] = self.bot.get_export_rag_status()
            except Exception:
                status['export_rag'] = None
        else:
            try:
                from backend.config import CONFIG
                bot_cfg = CONFIG.get('bot', {})
                status['export_rag'] = {
                    'enabled': bool(bot_cfg.get('export_rag_enabled', False)),
                    'base_dir': str(bot_cfg.get('export_rag_dir') or ''),
                    'auto_ingest': bool(bot_cfg.get('export_rag_auto_ingest', True)),
                    'indexed_contacts': 0,
                    'indexed_chunks': 0,
                    'last_scan_at': None,
                    'last_scan_summary': {},
                }
            except Exception:
                status['export_rag'] = None
        self._status_cache = status
        self._status_cache_time = now
        return dict(status)

    def _invalidate_status_cache(self) -> None:
        self._status_cache = None
        self._status_cache_time = 0.0
        self._stats_cache = None
        self._stats_cache_time = 0.0

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
            "timestamp": asyncio.get_event_loop().time()
        }
        
        # 移除已关闭的队列
        closed = []
        for q in self._event_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                closed.append(q)
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
        
        try:
            while True:
                # 等待新事件
                event = await queue.get()
                
                # SSE 格式: data: <json>\n\n
                import json
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self._event_queues.discard(queue)
            
            
# 便捷访问函数
def get_bot_manager() -> BotManager:
    """获取 BotManager 实例"""
    return BotManager.get_instance()
