from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from backend.core.factory import build_ai_client, _validate_ollama_candidate
from backend.utils.config import build_api_candidates, is_placeholder_key

PROBE_TIMEOUT_CAP_SEC = 8.0


def _build_root_candidate(api_cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": "root_config",
        "base_url": api_cfg.get("base_url"),
        "api_key": api_cfg.get("api_key"),
        "model": api_cfg.get("model"),
        "embedding_model": api_cfg.get("embedding_model"),
        "timeout_sec": api_cfg.get("timeout_sec"),
        "timeout": api_cfg.get("timeout"),
        "max_retries": api_cfg.get("max_retries"),
        "temperature": api_cfg.get("temperature"),
        "max_tokens": api_cfg.get("max_tokens"),
        "alias": api_cfg.get("alias"),
        "allow_empty_key": bool(api_cfg.get("allow_empty_key", False)),
    }


def _select_probe_settings(api_cfg: Dict[str, Any], preset_name: str = "") -> Tuple[Optional[Dict[str, Any]], str, str]:
    wanted = str(preset_name or "").strip()
    if wanted:
        if wanted == "root_config":
            settings = _build_root_candidate(api_cfg)
        else:
            presets = api_cfg.get("presets", [])
            settings = next(
                (
                    dict(item)
                    for item in presets
                    if isinstance(item, dict) and str(item.get("name") or "").strip() == wanted
                ),
                None,
            )
        if not isinstance(settings, dict):
            return None, wanted, "未找到指定的预设配置"
        settings.setdefault("name", wanted)
        return settings, wanted, ""

    candidates = build_api_candidates(api_cfg)
    if not candidates:
        return None, "", "未找到可用的 API 预设"

    settings = dict(candidates[0])
    selected_name = str(settings.get("name") or "").strip()
    return settings, selected_name, ""


def _normalize_probe_settings(settings: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    normalized = dict(settings)
    normalized["name"] = str(normalized.get("name") or "").strip()
    normalized["base_url"] = str(normalized.get("base_url") or "").strip()
    normalized["model"] = str(normalized.get("model") or "").strip()

    api_key_raw = normalized.get("api_key")
    normalized["api_key"] = "" if api_key_raw is None else str(api_key_raw).strip()
    normalized["allow_empty_key"] = bool(normalized.get("allow_empty_key", False))

    if not normalized["base_url"] or not normalized["model"]:
        return None, "预设缺少 base_url 或 model，无法测试连接"
    if is_placeholder_key(normalized["api_key"]) and not normalized["allow_empty_key"]:
        return None, "API Key 未配置，无法测试连接"

    timeout_raw = normalized.get("timeout_sec")
    if timeout_raw in (None, ""):
        timeout_raw = normalized.get("timeout", 10.0)
    try:
        timeout_sec = float(timeout_raw)
    except (TypeError, ValueError):
        timeout_sec = 10.0
    if timeout_sec <= 0:
        timeout_sec = 10.0

    normalized["timeout_sec"] = min(timeout_sec, PROBE_TIMEOUT_CAP_SEC)
    normalized["max_retries"] = 0
    return normalized, ""


async def probe_config(config: Dict[str, Any], preset_name: str = "") -> Tuple[bool, str, str]:
    api_cfg = dict(config.get("api") or {})
    bot_cfg = dict(config.get("bot") or {})

    settings, selected_name, error_message = _select_probe_settings(api_cfg, preset_name)
    if settings is None:
        return False, selected_name or str(preset_name or "").strip(), error_message

    prepared, error_message = _normalize_probe_settings(settings)
    if prepared is None:
        return False, selected_name or str(preset_name or "").strip(), error_message

    ollama_issue = _validate_ollama_candidate(prepared)
    if ollama_issue:
        return False, selected_name or str(preset_name or "").strip(), ollama_issue

    client = build_ai_client(prepared, bot_cfg)
    try:
        ok, mode = await client.probe_fast()
    finally:
        if hasattr(client, "close"):
            await client.close()

    resolved_name = selected_name or str(prepared.get("name") or preset_name or "").strip()
    if ok:
        if mode == "models":
            return True, resolved_name, "连接测试成功（已验证服务可访问）"
        return True, resolved_name, "连接测试成功（已验证模型可调用）"
    return False, resolved_name, "连接测试失败，请检查配置或网络"
