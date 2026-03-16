"""
核心功能模块。

包含：
    - AIClient: OpenAI 兼容 API 客户端
    - MemoryManager: SQLite 记忆管理器
    - emotion: 情感检测功能

注意：该包会被大量子模块依赖。为优化“启动/打开机器人”的首屏响应速度，
这里采用 lazy import，避免在 import backend.core 时立即引入 httpx/langchain 等
较重依赖。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    # AI 客户端
    "AgentRuntime",
    "AIClient",
    # 记忆管理
    "MemoryManager",
    # 情感检测
    "EmotionResult",
    "detect_emotion_keywords",
    "get_emotion_response_guide",
    "get_emotion_analysis_prompt",
    "parse_emotion_ai_response",
    "get_fact_extraction_prompt",
    "parse_fact_extraction_response",
    # 人性化增强
    "get_time_period",
    "get_time_context",
    "get_time_aware_prompt_addition",
    "analyze_conversation_style",
    "get_style_adaptation_hint",
    "analyze_emotion_trend",
    "get_emotion_trend_hint",
    "get_relationship_evolution_hint",
]

_EMOTION_EXPORTS = {
    "EmotionResult",
    "detect_emotion_keywords",
    "get_emotion_response_guide",
    "get_emotion_analysis_prompt",
    "parse_emotion_ai_response",
    "get_fact_extraction_prompt",
    "parse_fact_extraction_response",
    "get_time_period",
    "get_time_context",
    "get_time_aware_prompt_addition",
    "analyze_conversation_style",
    "get_style_adaptation_hint",
    "analyze_emotion_trend",
    "get_emotion_trend_hint",
    "get_relationship_evolution_hint",
}


def __getattr__(name: str) -> Any:
    if name == "AgentRuntime":
        from .agent_runtime import AgentRuntime

        globals()[name] = AgentRuntime
        return AgentRuntime

    if name == "AIClient":
        from .ai_client import AIClient

        globals()[name] = AIClient
        return AIClient

    if name == "MemoryManager":
        try:
            from .memory import MemoryManager
        except ImportError as exc:
            _memory_import_error = exc

            class MemoryManager:  # type: ignore[no-redef]
                def __init__(self, *args, **kwargs):
                    raise RuntimeError(
                        "MemoryManager 依赖 aiosqlite：请先安装 requirements.txt（或单独安装 aiosqlite）。"
                    ) from _memory_import_error

        globals()[name] = MemoryManager
        return MemoryManager

    if name in _EMOTION_EXPORTS:
        from . import emotion as emotion_module

        value = getattr(emotion_module, name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
