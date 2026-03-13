"""
工厂模块 - 负责对象创建和资源管理。

本模块提供了创建 AI 客户端、微信客户端以及管理重连策略的工厂函数。
"""

import asyncio
import importlib
import json
import logging
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING
from ..core.ai_client import AIClient
from ..types import ReconnectPolicy
from ..utils.common import as_int, as_float, as_optional_int, as_optional_str
from ..utils.config import normalize_system_prompt, build_api_candidates, get_setting, is_placeholder_key

__all__ = [
    "build_ai_client",
    "select_ai_client",
    "select_specific_ai_client",
    "get_reconnect_policy",
    "reconnect_wechat",
    "apply_ai_runtime_settings",
    "compute_api_signature",
    "reload_ai_module",
]

if TYPE_CHECKING:
    from wxauto import WeChat


# 全局变量用于 reload
from ..core import ai_client as ai_module_ref
_ai_module = ai_module_ref


def build_ai_client(settings: Dict[str, Any], bot_cfg: Dict[str, Any]) -> AIClient:
    """
    根据配置构建 AI 客户端实例。
    
    Args:
        settings: API 配置字典 (包含 base_url, api_key 等)
        bot_cfg: 机器人配置字典 (包含上下文设置等)
        
    Returns:
        AIClient: 初始化后的客户端实例
    """
    history_ttl_raw = bot_cfg.get("history_ttl_sec", 24 * 60 * 60)
    if history_ttl_raw is None:
        history_ttl_sec = None
    else:
        history_ttl_sec = as_float(
            history_ttl_raw,
            24 * 60 * 60,
            min_value=0.0,
        ) or None

    client = AIClient(
        base_url=str(settings.get("base_url") or "").strip(),
        api_key=str(settings.get("api_key") or "").strip(),
        model=str(settings.get("model") or "").strip(),
        timeout_sec=as_float(
            settings.get("timeout_sec", 10),
            10.0,
            min_value=0.0,
        ),
        max_retries=as_int(settings.get("max_retries", 2), 2, min_value=0),
        context_rounds=as_int(bot_cfg.get("context_rounds", 5), 5, min_value=0),
        context_max_tokens=as_optional_int(bot_cfg.get("context_max_tokens")),
        system_prompt=normalize_system_prompt(bot_cfg.get("system_prompt", "")),
        temperature=settings.get("temperature"),
        max_tokens=settings.get("max_tokens"),
        max_completion_tokens=as_optional_int(
            settings.get("max_completion_tokens")
        ),
        reasoning_effort=as_optional_str(settings.get("reasoning_effort")),
        model_alias=settings.get("alias"),
        embedding_model=as_optional_str(settings.get("embedding_model")), # 新增
        history_max_chats=as_int(
            bot_cfg.get("history_max_chats", 200), 200, min_value=1
        ),
        history_ttl_sec=history_ttl_sec,
    )
    client.model_alias = str(settings.get("alias") or "").strip()
    return client


async def select_ai_client(
    api_cfg: Dict[str, Any], bot_cfg: Dict[str, Any]
) -> Tuple[Optional[AIClient], Optional[str]]:
    """
    探测并选择可用的 AI 客户端预设。
    
    会按优先级遍历预设，直到找到一个可用 (probe 成功) 的配置。
    
    Returns:
        (client, preset_name): 成功则返回客户端和预设名，否则返回 (None, None)
    """
    candidates = build_api_candidates(api_cfg)
    if not candidates:
        logging.error("未找到可用的 API 配置。")
        return None, None

    for settings in candidates:
        name = settings.get("name", "preset")
        base_url = str(settings.get("base_url") or "").strip()
        model = str(settings.get("model") or "").strip()
        api_key = settings.get("api_key")
        if api_key is None:
            api_key = ""
        else:
            api_key = str(api_key).strip()
        allow_empty_key = bool(settings.get("allow_empty_key", False))

        if not base_url or not model:
            logging.warning("跳过预设 %s：缺少 base_url 或 model", name)
            continue
        if is_placeholder_key(api_key) and not allow_empty_key:
            logging.warning("跳过预设 %s：api_key 未配置或为占位符", name)
            continue

        settings = dict(settings)
        settings["base_url"] = base_url
        settings["model"] = model
        settings["api_key"] = api_key
        # 传递 embedding_model
        if "embedding_model" not in settings:
             settings["embedding_model"] = str(api_cfg.get("embedding_model") or "")

        client = build_ai_client(settings, bot_cfg)
        logging.info("正在探测预设：%s", name)
        if await client.probe():
            logging.info("已选择预设：%s", name)
            return client, name
        logging.warning("预设 %s 不可用，尝试下一个...", name)

    logging.error("没有可用的预设，请检查 API 配置。")
    return None, None


async def select_specific_ai_client(
    api_cfg: Dict[str, Any], bot_cfg: Dict[str, Any], preset_name: str
) -> Tuple[Optional[AIClient], Optional[str]]:
    """
    严格选择指定预设，不做自动回退。
    """
    wanted = str(preset_name or "").strip()
    presets = api_cfg.get("presets", [])
    if not wanted or not isinstance(presets, list):
        logging.error("未找到指定预设：%s", wanted or "<empty>")
        return None, None

    settings = next((p for p in presets if isinstance(p, dict) and p.get("name") == wanted), None)
    if not isinstance(settings, dict):
        logging.error("指定预设不存在：%s", wanted)
        return None, None

    base_url = str(settings.get("base_url") or "").strip()
    model = str(settings.get("model") or "").strip()
    api_key = settings.get("api_key")
    if api_key is None:
        api_key = ""
    else:
        api_key = str(api_key).strip()
    allow_empty_key = bool(settings.get("allow_empty_key", False))

    if not base_url or not model:
        logging.error("指定预设 %s 缺少 base_url 或 model", wanted)
        return None, None
    if is_placeholder_key(api_key) and not allow_empty_key:
        logging.error("指定预设 %s 的 api_key 未配置或为占位符", wanted)
        return None, None

    settings = dict(settings)
    settings["base_url"] = base_url
    settings["model"] = model
    settings["api_key"] = api_key
    if "embedding_model" not in settings:
        settings["embedding_model"] = str(api_cfg.get("embedding_model") or "")

    client = build_ai_client(settings, bot_cfg)
    logging.info("正在严格探测指定预设：%s", wanted)
    if await client.probe():
        logging.info("已选择指定预设：%s", wanted)
        return client, wanted

    logging.error("指定预设不可用：%s", wanted)
    return None, None


def get_reconnect_policy(bot_cfg: Dict[str, Any]) -> ReconnectPolicy:
    """从配置中加载重连策略。"""
    max_retries = as_int(bot_cfg.get("reconnect_max_retries", 3), 3, min_value=0)
    base_delay = as_float(
        bot_cfg.get("reconnect_backoff_sec", 2.0), 2.0, min_value=0.5
    )
    max_delay = as_float(
        bot_cfg.get("reconnect_max_delay_sec", 20.0), 20.0, min_value=1.0
    )
    return ReconnectPolicy(
        max_retries=max_retries,
        base_delay_sec=base_delay,
        max_delay_sec=max_delay,
    )


async def reconnect_wechat(reason: str, policy: ReconnectPolicy) -> Optional["WeChat"]:
    """
    尝试重连微信客户端。
    
    Args:
        reason: 重连原因（用于日志）
        policy: 重连策略配置
        
    Returns:
        WeChat: 成功返回实例，失败返回 None
    """
    try:
        from wxauto import WeChat
    except ImportError:
        return None

    logging.warning("准备重连微信：%s", reason)
    for attempt in range(policy.max_retries + 1):
        try:
            wx = WeChat()
            logging.info("微信重连成功。")
            return wx
        except Exception as exc:
            wait = min(policy.max_delay_sec, policy.base_delay_sec * (1.5**attempt))
            logging.warning(
                "微信重连失败（第 %s 次）：%s，%s 秒后重试",
                attempt + 1,
                exc,
                round(wait, 2),
            )
            await asyncio.sleep(wait)
    logging.error("微信重连多次失败，请检查客户端状态。")
    return None


def apply_ai_runtime_settings(
    ai_client: AIClient,
    api_cfg: Dict[str, Any],
    bot_cfg: Dict[str, Any],
    allow_api_override: bool,
) -> None:
    """
    将运行时配置应用到现有的 AI 客户端实例。
    
    用于支持热重载，无需重建客户端即可更新参数。
    """
    if allow_api_override:
        ai_client.base_url = str(api_cfg.get("base_url") or ai_client.base_url).rstrip("/")
        ai_client.api_key = str(api_cfg.get("api_key") or ai_client.api_key)
        ai_client.model = str(api_cfg.get("model") or ai_client.model)
        if "embedding_model" in api_cfg:
            value = api_cfg.get("embedding_model")
            if value is None:
                ai_client.embedding_model = None
            else:
                v = str(value).strip()
                ai_client.embedding_model = v if v else None
        if api_cfg.get("alias"):
            ai_client.model_alias = str(api_cfg.get("alias") or ai_client.model_alias)
    ai_client.timeout_sec = min(
        as_float(api_cfg.get("timeout_sec", ai_client.timeout_sec), ai_client.timeout_sec),
        10.0,
    )
    ai_client.max_retries = min(
        as_int(api_cfg.get("max_retries", ai_client.max_retries), ai_client.max_retries, min_value=0),
        2,
    )
    ai_client.temperature = api_cfg.get("temperature", ai_client.temperature)
    ai_client.max_tokens = api_cfg.get("max_tokens", ai_client.max_tokens)
    max_completion_tokens = api_cfg.get(
        "max_completion_tokens", ai_client.max_completion_tokens
    )
    ai_client.max_completion_tokens = as_optional_int(max_completion_tokens)
    ai_client.reasoning_effort = as_optional_str(
        api_cfg.get("reasoning_effort", ai_client.reasoning_effort)
    )
    ai_client.context_rounds = as_int(
        bot_cfg.get("context_rounds", ai_client.context_rounds),
        ai_client.context_rounds,
        min_value=0,
    )
    context_max_tokens = bot_cfg.get(
        "context_max_tokens", ai_client.context_max_tokens
    )
    ai_client.context_max_tokens = as_optional_int(context_max_tokens)
    ai_client.history_max_chats = as_int(
        bot_cfg.get("history_max_chats", ai_client.history_max_chats),
        ai_client.history_max_chats,
        min_value=1,
    )
    history_ttl = bot_cfg.get("history_ttl_sec", ai_client.history_ttl_sec)
    if history_ttl is None:
        ai_client.history_ttl_sec = None
    else:
        ai_client.history_ttl_sec = as_float(history_ttl, 0.0, min_value=0.0) or None
    ai_client.system_prompt = normalize_system_prompt(
        bot_cfg.get("system_prompt", ai_client.system_prompt)
    )


def compute_api_signature(api_cfg: Dict[str, Any]) -> str:
    """计算 API 配置的签名（用于检测变更）。"""
    try:
        return json.dumps(api_cfg, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(api_cfg)


async def reload_ai_module(ai_client: Optional[AIClient] = None) -> None:
    """
    重新加载 AI 模块。
    
    用于开发调试，在不重启主进程的情况下更新 AI 客户端代码。
    """
    global _ai_module
    if ai_client and hasattr(ai_client, "close"):
        await ai_client.close()
    _ai_module = importlib.reload(_ai_module)
