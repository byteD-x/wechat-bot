"""
工厂模块 - 负责对象创建和资源管理。

本模块提供了创建 AI 客户端、微信客户端以及管理重连策略的工厂函数。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

import httpx

from backend.model_auth.services import hydrate_runtime_settings
from backend.model_auth.services.migration import _build_runtime_preset, _iter_runtime_profiles, _provider_map
from ..types import ReconnectPolicy
from .config_service import get_config_service
from .oauth_support import OAuthSupportError, resolve_oauth_settings
from ..utils.common import as_int, as_float, as_optional_int, as_optional_str
from ..utils.config import normalize_system_prompt, build_api_candidates, get_setting, is_placeholder_key

__all__ = [
    "build_ai_client",
    "build_agent_runtime",
    "select_ai_client",
    "select_specific_ai_client",
    "get_reconnect_policy",
    "get_last_ai_client_error",
    "get_last_transport_error",
    "reconnect_wechat",
    "apply_ai_runtime_settings",
    "compute_api_signature",
    "reload_ai_module",
]

if TYPE_CHECKING:
    from ..core.ai_client import AIClient
    from ..core.agent_runtime import AgentRuntime


# 全局变量用于 reload
_ai_module = None
_last_ai_client_error = ""
_last_transport_error = ""


def _set_last_transport_error(detail: str) -> None:
    global _last_transport_error
    _last_transport_error = str(detail or "").strip()


def _set_last_ai_client_error(detail: str) -> None:
    global _last_ai_client_error
    _last_ai_client_error = str(detail or "").strip()


def get_last_ai_client_error() -> str:
    return _last_ai_client_error


def get_last_transport_error() -> str:
    return _last_transport_error


def _resolve_embedding_model(
    settings: Dict[str, Any],
    api_cfg: Dict[str, Any],
    bot_cfg: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    bot_cfg = dict(bot_cfg or {})
    override_model = str(bot_cfg.get("vector_memory_embedding_model") or "").strip()
    if override_model and not is_placeholder_key(override_model):
        return override_model

    if "embedding_model" in settings:
        return settings.get("embedding_model")

    api_key = str(settings.get("api_key") or "").strip()
    allow_empty_key = bool(settings.get("allow_empty_key", False))
    if allow_empty_key and not api_key:
        # Avoid inheriting a remote embedding config for local no-key presets.
        return None

    return api_cfg.get("embedding_model")


def _is_ollama_candidate(settings: Dict[str, Any]) -> bool:
    provider_id = str(settings.get("provider_id") or "").strip().lower()
    name = str(settings.get("name") or "").strip().lower()
    base_url = str(settings.get("base_url") or "").strip().lower()
    return (
        provider_id == "ollama"
        or "ollama" in name
        or "127.0.0.1:11434" in base_url
        or "localhost:11434" in base_url
    )


def _normalize_ollama_tags_url(base_url: str) -> str:
    raw = str(base_url or "http://127.0.0.1:11434/v1").strip()
    if not raw:
        raw = "http://127.0.0.1:11434/v1"

    parsed = urlsplit(raw)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    path = path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    path = f"{path}/api/tags" if path else "/api/tags"
    return urlunsplit((scheme, netloc, path, "", ""))


def _fetch_ollama_models(base_url: str, timeout_sec: float = 3.0) -> list[Dict[str, Any]]:
    response = httpx.get(_normalize_ollama_tags_url(base_url), timeout=timeout_sec)
    response.raise_for_status()
    payload = response.json()
    models = payload.get("models") or []
    return [dict(item) for item in models if isinstance(item, dict)]


def _split_ollama_models(models: list[Dict[str, Any]]) -> Tuple[list[str], list[str], list[str]]:
    local_chat_models: list[str] = []
    remote_models: list[str] = []
    embedding_models: list[str] = []
    for item in models:
        name = str(item.get("model") or item.get("name") or "").strip()
        if not name:
            continue
        lower_name = name.lower()
        if str(item.get("remote_host") or "").strip():
            remote_models.append(name)
            continue
        if "embed" in lower_name or "embedding" in lower_name:
            embedding_models.append(name)
            continue
        local_chat_models.append(name)
    return local_chat_models, remote_models, embedding_models


def _validate_ollama_candidate(settings: Dict[str, Any]) -> str:
    if not _is_ollama_candidate(settings):
        return ""

    settings = dict(settings)
    auth_mode = str(settings.get("auth_mode") or "api_key").strip().lower() or "api_key"
    base_url = str(settings.get("base_url") or "").strip()
    model = str(settings.get("model") or "").strip()
    if auth_mode != "oauth" and (not base_url or not model):
        return ""

    try:
        models = _fetch_ollama_models(base_url)
    except Exception as exc:
        logging.warning("获取 Ollama 模型列表失败，继续按原模型探测：%s", exc)
        return ""

    local_chat_models, remote_models, embedding_models = _split_ollama_models(models)
    matched = next(
        (
            item
            for item in models
            if str(item.get("model") or item.get("name") or "").strip() == model
        ),
        None,
    )
    if matched is None:
        available = ", ".join(local_chat_models[:5] or remote_models[:5] or embedding_models[:5]) or "无"
        return f"Ollama 未找到模型 {model}，当前可见模型：{available}"

    lower_name = model.lower()
    if "embed" in lower_name or "embedding" in lower_name:
        local_hint = ", ".join(local_chat_models[:5]) if local_chat_models else "未检测到本地聊天模型"
        return f"Ollama 模型 {model} 是 embedding 模型，不能用于聊天回复；{local_hint}"

    return ""


def _describe_runtime_candidate(settings: Dict[str, Any]) -> str:
    name = str(settings.get("name") or "preset").strip() or "preset"
    profile_id = str(settings.get("provider_auth_profile_id") or "").strip()
    if profile_id:
        return f"{name} [{profile_id}]"
    return name


def _expand_provider_auth_runtime_variants(
    api_cfg: Dict[str, Any],
    settings: Dict[str, Any],
) -> list[Dict[str, Any]]:
    candidate = dict(settings or {})
    if str(candidate.get("name") or "").strip() == "root_config":
        return [candidate]
    center = api_cfg.get("provider_auth_center") if isinstance(api_cfg.get("provider_auth_center"), dict) else {}
    provider_id = str(candidate.get("provider_id") or "").strip().lower()
    if not center or not provider_id:
        return [candidate]
    entry = _provider_map(center).get(provider_id) or {}
    if not bool((entry.get("metadata") or {}).get("project_to_runtime")):
        return [candidate]
    variants: list[Dict[str, Any]] = []
    runtime_name = str(candidate.get("name") or entry.get("legacy_preset_name") or provider_id).strip() or provider_id
    for profile, context in _iter_runtime_profiles(entry):
        variant = _build_runtime_preset(entry, profile, context)
        variant["name"] = runtime_name
        variants.append(variant)
    if not variants:
        return [candidate]
    requested_profile_id = str(candidate.get("provider_auth_profile_id") or "").strip()
    if requested_profile_id:
        variants.sort(
            key=lambda item: 0 if str(item.get("provider_auth_profile_id") or "").strip() == requested_profile_id else 1
        )
    return variants


def _prepare_runtime_settings_candidate(
    settings: Dict[str, Any],
    api_cfg: Dict[str, Any],
    bot_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    prepared = hydrate_runtime_settings(dict(settings or {}))
    candidate_name = _describe_runtime_candidate(prepared)
    auth_mode = str(prepared.get("auth_mode") or "api_key").strip().lower() or "api_key"
    runtime_api_key = prepared.get("api_key")
    if runtime_api_key is None:
        runtime_api_key = ""
    elif not callable(runtime_api_key):
        runtime_api_key = str(runtime_api_key).strip()
    allow_empty_key = bool(prepared.get("allow_empty_key", False))
    base_url = str(prepared.get("base_url") or "").strip()
    model = str(prepared.get("model") or "").strip()

    if auth_mode != "oauth" and (not base_url or not model):
        raise ValueError(f"\u9884\u8bbe {candidate_name} \u7f3a\u5c11 base_url \u6216 model")
    if auth_mode != "oauth" and not callable(runtime_api_key) and is_placeholder_key(runtime_api_key) and not allow_empty_key:
        raise ValueError(f"\u9884\u8bbe {candidate_name} \u7684 api_key \u672a\u914d\u7f6e\u6216\u4ecd\u4e3a\u5360\u4f4d\u7b26")

    prepared["base_url"] = base_url
    prepared["model"] = model
    prepared["api_key"] = runtime_api_key
    prepared["embedding_model"] = _resolve_embedding_model(prepared, api_cfg, bot_cfg)
    if "embedding_model" not in prepared:
        prepared["embedding_model"] = str(api_cfg.get("embedding_model") or "")

    try:
        prepared = resolve_oauth_settings(prepared).settings
    except OAuthSupportError as exc:
        raise ValueError(f"\u9884\u8bbe {candidate_name} OAuth \u4e0d\u53ef\u7528\uff1a{exc}") from exc

    base_url = str(prepared.get("base_url") or "").strip()
    model = str(prepared.get("model") or "").strip()
    if not base_url or not model:
        raise ValueError(f"\u9884\u8bbe {candidate_name} \u5728\u8ba4\u8bc1\u89e3\u6790\u540e\u4ecd\u7f3a\u5c11 base_url \u6216 model")
    prepared["base_url"] = base_url
    prepared["model"] = model

    candidate_issue = _validate_ollama_candidate(prepared)
    if candidate_issue:
        raise ValueError(candidate_issue)
    return prepared


def _build_runtime_client_for_settings(
    settings: Dict[str, Any],
    bot_cfg: Dict[str, Any],
    agent_cfg: Optional[Dict[str, Any]] = None,
) -> Any:
    runtime_enabled = True if agent_cfg is None else bool(agent_cfg.get("enabled", True))
    return (
        build_agent_runtime(settings, bot_cfg, agent_cfg)
        if runtime_enabled
        else build_ai_client(settings, bot_cfg)
    )


async def _select_specific_candidate_variants(
    api_cfg: Dict[str, Any],
    bot_cfg: Dict[str, Any],
    settings: Dict[str, Any],
    preset_name: str,
    agent_cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Any], Optional[str]]:
    for variant in _expand_provider_auth_runtime_variants(api_cfg, settings):
        candidate_name = _describe_runtime_candidate(variant)
        try:
            variant = _prepare_runtime_settings_candidate(variant, api_cfg, bot_cfg)
        except ValueError as exc:
            _set_last_ai_client_error(str(exc))
            logging.error("\u6307\u5b9a\u9884\u8bbe %s \u4e0d\u53ef\u7528\uff1a%s", candidate_name, exc)
            continue
        try:
            client = _build_runtime_client_for_settings(variant, bot_cfg, agent_cfg)
        except Exception as exc:
            reason = f"\u6307\u5b9a\u9884\u8bbe {candidate_name} \u521d\u59cb\u5316\u5931\u8d25\uff1a{exc}"
            _set_last_ai_client_error(reason)
            logging.error("\u6307\u5b9a\u9884\u8bbe %s \u521d\u59cb\u5316\u5931\u8d25\uff1a%s", candidate_name, exc)
            continue
        logging.info("\u6b63\u5728\u4e25\u683c\u63a2\u6d4b\u6307\u5b9a\u9884\u8bbe\uff1a%s", candidate_name)
        probe_ok = False
        try:
            probe_ok = bool(await client.probe())
        except Exception as exc:
            reason = f"\u6307\u5b9a\u9884\u8bbe {candidate_name} \u63a2\u6d4b\u5f02\u5e38\uff1a{exc}"
            _set_last_ai_client_error(reason)
            logging.error("\u6307\u5b9a\u9884\u8bbe %s \u63a2\u6d4b\u5f02\u5e38\uff1a%s", candidate_name, exc)
        if probe_ok:
            _set_last_ai_client_error("")
            logging.info("\u5df2\u9009\u62e9\u6307\u5b9a\u9884\u8bbe\uff1a%s", candidate_name)
            return client, preset_name
        _set_last_ai_client_error(f"\u6307\u5b9a\u9884\u8bbe {candidate_name} \u63a2\u6d4b\u5931\u8d25")
        logging.error("\u6307\u5b9a\u9884\u8bbe\u4e0d\u53ef\u7528\uff1a%s", candidate_name)
        if hasattr(client, "close"):
            await client.close()
    return None, None


def build_ai_client(settings: Dict[str, Any], bot_cfg: Dict[str, Any]) -> AIClient:
    """
    根据配置构建 AI 客户端实例。
    
    Args:
        settings: API 配置字典 (包含 base_url, api_key 等)
        bot_cfg: 机器人配置字典 (包含上下文设置等)
        
    Returns:
        AIClient: 初始化后的客户端实例
    """
    from ..core.ai_client import AIClient

    history_ttl_raw = bot_cfg.get("history_ttl_sec", 24 * 60 * 60)
    if history_ttl_raw is None:
        history_ttl_sec = None
    else:
        history_ttl_sec = as_float(
            history_ttl_raw,
            24 * 60 * 60,
            min_value=0.0,
        ) or None

    runtime_api_key = settings.get("api_key")
    if runtime_api_key is None:
        runtime_api_key = ""
    elif not callable(runtime_api_key):
        runtime_api_key = str(runtime_api_key).strip()

    client = AIClient(
        base_url=str(settings.get("base_url") or "").strip(),
        api_key=runtime_api_key,
        extra_headers=settings.get("extra_headers"),
        auth_refresh_hook=settings.get("auth_refresh_hook"),
        auth_transport=str(settings.get("auth_transport") or "").strip() or None,
        transport_metadata=settings.get("resolved_auth_metadata"),
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


def build_agent_runtime(
    settings: Dict[str, Any],
    bot_cfg: Dict[str, Any],
    agent_cfg: Optional[Dict[str, Any]] = None,
) -> AgentRuntime:
    """根据配置构建 LangChain/LangGraph 运行时。"""
    from ..core.agent_runtime import AgentRuntime

    return AgentRuntime(settings=settings, bot_cfg=bot_cfg, agent_cfg=agent_cfg)


async def select_ai_client(
    api_cfg: Dict[str, Any],
    bot_cfg: Dict[str, Any],
    agent_cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Any], Optional[str]]:
    """
    探测并选择可用的 AI 客户端预设。
    
    会按优先级遍历预设，直到找到一个可用 (probe 成功) 的配置。
    
    Returns:
        (client, preset_name): 成功则返回客户端和预设名，否则返回 (None, None)
    """
    candidates = build_api_candidates(api_cfg)
    if not candidates:
        _set_last_ai_client_error("未找到可用的 API 配置")
        logging.error("未找到可用的 API 配置。")
        return None, None

    for candidate in candidates:
        preset_name = str(candidate.get("name") or "preset").strip() or "preset"
        for settings in _expand_provider_auth_runtime_variants(api_cfg, candidate):
            candidate_name = _describe_runtime_candidate(settings)
            try:
                settings = _prepare_runtime_settings_candidate(settings, api_cfg, bot_cfg)
            except ValueError as exc:
                _set_last_ai_client_error(str(exc))
                logging.warning("\u8df3\u8fc7\u9884\u8bbe %s\uff1a%s", candidate_name, exc)
                continue
            try:
                client = _build_runtime_client_for_settings(settings, bot_cfg, agent_cfg)
            except Exception as exc:
                reason = f"\u9884\u8bbe {candidate_name} \u521d\u59cb\u5316\u5931\u8d25\uff1a{exc}"
                _set_last_ai_client_error(reason)
                logging.warning("\u8df3\u8fc7\u9884\u8bbe %s\uff1a\u521d\u59cb\u5316\u5931\u8d25\uff1a%s", candidate_name, exc)
                continue
            logging.info("\u6b63\u5728\u63a2\u6d4b\u9884\u8bbe\uff1a%s", candidate_name)
            probe_ok = False
            try:
                probe_ok = bool(await client.probe())
            except Exception as exc:
                reason = f"\u9884\u8bbe {candidate_name} \u63a2\u6d4b\u5f02\u5e38\uff1a{exc}"
                _set_last_ai_client_error(reason)
                logging.warning("\u9884\u8bbe %s \u63a2\u6d4b\u5f02\u5e38\uff1a%s", candidate_name, exc)
            if probe_ok:
                _set_last_ai_client_error("")
                logging.info("\u5df2\u9009\u62e9\u9884\u8bbe\uff1a%s", candidate_name)
                return client, preset_name
            _set_last_ai_client_error(f"\u9884\u8bbe {candidate_name} \u63a2\u6d4b\u5931\u8d25")
            logging.warning("\u9884\u8bbe %s \u4e0d\u53ef\u7528\uff0c\u5c1d\u8bd5\u4e0b\u4e00\u4e2a\u5019\u9009\u3002", candidate_name)
            if hasattr(client, "close"):
                await client.close()

    if not get_last_ai_client_error():
        _set_last_ai_client_error("没有可用的预设，请检查 API 配置")
    logging.error("没有可用的预设，请检查 API 配置。")
    return None, None


async def select_specific_ai_client(
    api_cfg: Dict[str, Any],
    bot_cfg: Dict[str, Any],
    preset_name: str,
    agent_cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Any], Optional[str]]:
    """
    严格选择指定预设，不做自动回退。
    """
    wanted = str(preset_name or "").strip()
    presets = api_cfg.get("presets", [])
    if not wanted or not isinstance(presets, list):
        _set_last_ai_client_error(f"未找到指定预设：{wanted or '<empty>'}")
        logging.error("未找到指定预设：%s", wanted or "<empty>")
        return None, None

    settings = next((p for p in presets if isinstance(p, dict) and p.get("name") == wanted), None)
    if isinstance(settings, dict):
        return await _select_specific_candidate_variants(api_cfg, bot_cfg, settings, wanted, agent_cfg)
    _set_last_ai_client_error(f"指定预设不存在：{wanted}")
    logging.error("指定预设不存在：%s", wanted)
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


async def reconnect_wechat(
    reason: str,
    policy: ReconnectPolicy,
    *,
    bot_cfg: Optional[Dict[str, Any]] = None,
    ai_client: Optional[Any] = None,
) -> Optional[Any]:
    """Reconnect the supported WCFerry transport with bounded retries."""
    if bot_cfg is None:
        config_path = None
        try:
            from backend.bot_manager import get_bot_manager

            config_path = get_bot_manager().config_path
        except Exception:
            config_path = None
        try:
            bot_cfg = get_config_service().get_snapshot(config_path=config_path).bot
        except Exception:
            bot_cfg = {}

    bot_cfg = dict(bot_cfg or {})

    from ..transports import TransportUnavailableError, WcferryTransport

    logging.warning("Preparing WeChat reconnect: %s", reason)
    for attempt in range(policy.max_retries + 1):
        try:
            client = await asyncio.to_thread(
                WcferryTransport,
                bot_cfg,
                ai_client=ai_client,
            )
            _set_last_transport_error("")
            logging.info("WCFerry transport initialized: %s", client.backend_name)
            return client
        except TransportUnavailableError as exc:
            _set_last_transport_error(str(exc))
            if attempt >= policy.max_retries:
                logging.error("WCFerry transport unavailable: %s", exc)
                break
            wait = min(policy.max_delay_sec, policy.base_delay_sec * (1.5**attempt))
            logging.warning(
                "WCFerry transport unavailable (attempt %s): %s; retrying in %s seconds",
                attempt + 1,
                exc,
                round(wait, 2),
            )
            await asyncio.sleep(wait)
        except Exception as exc:
            _set_last_transport_error(str(exc))
            if attempt >= policy.max_retries:
                logging.exception("WCFerry transport failed: %s", exc)
                break
            wait = min(policy.max_delay_sec, policy.base_delay_sec * (1.5**attempt))
            logging.warning(
                "WCFerry transport failed (attempt %s): %s; retrying in %s seconds",
                attempt + 1,
                exc,
                round(wait, 2),
            )
            await asyncio.sleep(wait)

    logging.error("WeChat reconnect failed after multiple attempts.")
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
        value = _resolve_embedding_model({}, api_cfg, bot_cfg)
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
    if _ai_module is None:
        from ..core import ai_client as ai_module_ref

        _ai_module = ai_module_ref
    _ai_module = importlib.reload(_ai_module)
