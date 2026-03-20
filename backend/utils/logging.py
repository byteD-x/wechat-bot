"""
日志工具模块 - 负责日志配置和格式化。
"""

import logging
import os
import json
import re
import traceback
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Tuple, Any, Literal

from .common import as_int


__all__ = [
    "setup_logging",
    "get_logging_settings",
    "get_log_behavior",
    "format_log_text",
    "format_log_fields",
    "build_stage_log_message",
    "JSONFormatter",
    "HealthcheckAccessLogFilter",
    "configure_http_access_log_filters",
]


class JSONFormatter(logging.Formatter):
    """JSON 格式日志格式化器"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            # "path": record.pathname,
            # "line": record.lineno,
        }
        
        if record.exc_info:
            # 格式化异常信息
            log_obj["exception"] = "".join(traceback.format_exception(*record.exc_info))
            
        # 合并 extra 字段 (如果存在)
        if hasattr(record, "extra_data"):
            log_obj.update(record.extra_data)
            
        return json.dumps(log_obj, ensure_ascii=False)


class HealthcheckAccessLogFilter(logging.Filter):
    """Hide high-frequency local polling access logs from the shared log stream."""

    _NOISY_PATH_PATTERN = re.compile(
        r"\bGET\s+/(api/(status|logs|messages))\b",
        re.IGNORECASE,
    )
    _LOCAL_HOST_PATTERN = re.compile(r"\b(127\.0\.0\.1|::1|localhost)\b", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        text = str(message or "")
        if not self._NOISY_PATH_PATTERN.search(text):
            return True
        return not self._LOCAL_HOST_PATTERN.search(text)


def configure_http_access_log_filters() -> None:
    filter_type = HealthcheckAccessLogFilter
    for logger_name in ("hypercorn.access", "quart.serving", "werkzeug"):
        target_logger = logging.getLogger(logger_name)
        if any(isinstance(item, filter_type) for item in target_logger.filters):
            continue
        target_logger.addFilter(filter_type())


def setup_logging(
    level: str,
    log_file: Optional[str] = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    format_type: Literal['text', 'json'] = 'text',
) -> None:
    """
    配置全局日志系统。
    
    支持同时输出到控制台和回滚文件日志。
    """
    # 移除现有 handlers 以避免重复
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)
            
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    
    if log_file:
        log_path = os.path.abspath(log_file)
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        try:
            handlers.append(
                RotatingFileHandler(
                    log_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
            )
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "日志文件不可写，已回退为仅控制台日志: %s",
                exc,
            )
        
    # 设置格式化器
    if format_type == 'json':
        formatter = JSONFormatter("%Y-%m-%d %H:%M:%S")
    else:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        
    for handler in handlers:
        handler.setFormatter(formatter)
        
    logging.basicConfig(
        level=level.upper(),
        handlers=handlers,
        force=True,
    )


def get_logging_settings(config: Dict[str, Any]) -> Tuple[str, Optional[str], int, int, str]:
    """从配置字典中提取日志相关设置。"""
    logging_cfg = config.get("logging", {})
    level = str(logging_cfg.get("level", "INFO"))
    log_file = logging_cfg.get("file")
    max_bytes = as_int(
        logging_cfg.get("max_bytes", 5 * 1024 * 1024),
        5 * 1024 * 1024,
        min_value=1024,
    )
    backup_count = as_int(logging_cfg.get("backup_count", 5), 5, min_value=0)
    format_type = str(logging_cfg.get("format", "text"))
    return level, log_file, max_bytes, backup_count, format_type


def get_log_behavior(config: Dict[str, Any]) -> Tuple[bool, bool]:
    """获取日志记录行为配置（是否记录消息内容/回复内容）。"""
    logging_cfg = config.get("logging", {})
    log_message_content = bool(logging_cfg.get("log_message_content", True))
    log_reply_content = bool(logging_cfg.get("log_reply_content", True))
    return log_message_content, log_reply_content


def format_log_text(text: str, enabled: bool, max_len: int = 120) -> str:
    """格式化日志文本，支持脱敏/隐藏和截断。"""
    from .common import truncate_text
    if not enabled:
        return "[hidden]"
    return truncate_text(text, max_len=max_len)


def format_log_fields(fields: Dict[str, Any], max_len: int = 160) -> str:
    """Format structured log fields as a compact key-value string."""
    from .common import truncate_text

    parts: List[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (dict, list, tuple, set)):
            try:
                text = json.dumps(value, ensure_ascii=False)
            except Exception:
                text = str(value)
        else:
            text = str(value)

        normalized = " ".join(text.split())
        parts.append(f"{key}={truncate_text(normalized, max_len=max_len)}")
    return " | ".join(parts)


def build_stage_log_message(stage: str, **fields: Any) -> str:
    """Build a human-readable stage log message."""
    prefix = f"[{str(stage or '').strip() or 'stage'}]"
    detail = format_log_fields(fields)
    return prefix if not detail else f"{prefix} {detail}"
