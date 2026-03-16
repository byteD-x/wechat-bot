"""
个性化 Prompt 管理模块。

包含：
    - PROMPT_OVERRIDES: 预加载的个性化 Prompt 字典
    - get_prompt_for_contact: 获取指定联系人的 Prompt
    - reload_prompts: 重新加载 Prompt
    - generate_personalized_prompt: 生成个性化 Prompt（异步）
"""

from __future__ import annotations

from typing import Any

__all__ = [
    # 从 overrides 导出
    "PROMPT_OVERRIDES",
    "get_prompt_for_contact",
    "reload_prompts",
    "list_contacts",
    "get_prompt_stats",
    # 从 generator 导出
    "generate_personalized_prompt",
]


def __getattr__(name: str) -> Any:
    # Avoid importing generator (AIClient/httpx/etc.) on module import.
    if name in {
        "PROMPT_OVERRIDES",
        "get_prompt_for_contact",
        "reload_prompts",
        "list_contacts",
        "get_prompt_stats",
    }:
        from . import overrides as overrides_module

        value = getattr(overrides_module, name)
        globals()[name] = value
        return value

    if name == "generate_personalized_prompt":
        from . import generator as generator_module

        value = getattr(generator_module, name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
