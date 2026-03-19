"""Helpers for config diffing, effect hints, and audit summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from backend.config_schemas import AgentConfig, ApiConfig, BotConfig, LoggingConfig, ServicesConfig


DORMANT_CONFIG_PATHS: set[str] = set()

_EXACT_EFFECTS: Dict[str, Dict[str, str]] = {
    "bot.config_reload_mode": {
        "mode": "live",
        "component": "config_watcher",
        "note": "立即更新配置监听模式",
    },
    "bot.config_reload_debounce_ms": {
        "mode": "live",
        "component": "config_watcher",
        "note": "立即更新配置监听防抖时间",
    },
    "bot.config_reload_sec": {
        "mode": "live",
        "component": "config_watcher",
        "note": "立即更新轮询检查间隔",
    },
    "bot.transport_backend": {
        "mode": "reinit",
        "component": "wechat_transport",
        "note": "需要重建微信传输层",
    },
    "bot.required_wechat_version": {
        "mode": "reinit",
        "component": "wechat_transport",
        "note": "需要重新校验微信版本",
    },
    "bot.silent_mode_required": {
        "mode": "reinit",
        "component": "wechat_transport",
        "note": "需要重建微信传输层",
    },
    "bot.reload_ai_client_module": {
        "mode": "reinit",
        "component": "ai_client",
        "note": "需要重载 AI 客户端模块并重建客户端",
    },
    "bot.group_include_sender": {
        "mode": "live",
        "component": "agent_runtime",
        "note": "下次构建 prompt 时立即生效",
    },
    "bot.profile_update_frequency": {
        "mode": "live",
        "component": "agent_runtime",
        "note": "下次用户画像后台更新时立即生效",
    },
    "bot.contact_prompt_update_frequency": {
        "mode": "live",
        "component": "agent_runtime",
        "note": "下次联系人专属 Prompt 后台更新时立即生效",
    },
    "bot.daily_token_limit": {
        "mode": "live",
        "component": "usage_guard",
        "note": "下次 AI 调用前立即按新上限判断",
    },
    "bot.token_warning_threshold": {
        "mode": "live",
        "component": "usage_guard",
        "note": "下次统计 token 用量时立即生效",
    },
    "bot.emotion_log_enabled": {
        "mode": "live",
        "component": "emotion_runtime",
        "note": "下次情绪分析时立即生效",
    },
    "bot.voice_to_text_fail_reply": {
        "mode": "live",
        "component": "bot_runtime",
        "note": "下次语音转文字失败时生效",
    },
}

_PREFIX_EFFECTS: Sequence[Tuple[str, Dict[str, str]]] = (
    (
        "api.",
        {"mode": "reinit", "component": "ai_client", "note": "需要重建 AI 客户端"},
    ),
    (
        "agent.",
        {"mode": "reinit", "component": "ai_client", "note": "需要重建 AI 运行时"},
    ),
    (
        "logging.",
        {"mode": "live", "component": "logging", "note": "运行中会重新应用日志配置"},
    ),
    (
        "bot.reply_",
        {"mode": "live", "component": "bot_runtime", "note": "新回复策略立即生效"},
    ),
    (
        "bot.random_delay_",
        {"mode": "live", "component": "bot_runtime", "note": "下次发送消息时生效"},
    ),
    (
        "bot.filter_",
        {"mode": "live", "component": "bot_runtime", "note": "过滤规则立即生效"},
    ),
    (
        "bot.ignore_",
        {"mode": "live", "component": "bot_runtime", "note": "过滤规则立即生效"},
    ),
    (
        "bot.whitelist",
        {"mode": "live", "component": "bot_runtime", "note": "白名单规则立即生效"},
    ),
    (
        "bot.memory_",
        {"mode": "live", "component": "memory", "note": "运行中会更新记忆配置"},
    ),
    (
        "bot.natural_split_",
        {"mode": "live", "component": "bot_runtime", "note": "下次发送回复时生效"},
    ),
    (
        "bot.vector_memory_",
        {"mode": "live", "component": "rag", "note": "运行中会更新向量记忆配置"},
    ),
    (
        "bot.export_rag_",
        {"mode": "live", "component": "rag", "note": "运行中会更新导出语料 RAG 配置"},
    ),
    (
        "bot.keepalive_",
        {"mode": "live", "component": "bot_runtime", "note": "运行中会更新保活策略"},
    ),
    (
        "bot.reconnect_",
        {"mode": "live", "component": "bot_runtime", "note": "下次重连时使用新策略"},
    ),
)


def _declared_paths() -> set[str]:
    sections = {
        "api": ApiConfig,
        "bot": BotConfig,
        "logging": LoggingConfig,
        "agent": AgentConfig,
        "services": ServicesConfig,
    }
    paths: set[str] = set()
    paths.add("schema_version")
    for section, model in sections.items():
        for field in model.model_fields:
            paths.add(f"{section}.{field}")
    return paths


DECLARED_CONFIG_PATHS = _declared_paths()


def flatten_config_paths(data: Any, prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flat.update(flatten_config_paths(value, next_prefix))
            elif isinstance(value, list):
                flat[next_prefix] = value
            else:
                flat[next_prefix] = value
    return flat


def diff_config_paths(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    old_flat = flatten_config_paths(before)
    new_flat = flatten_config_paths(after)
    changed = [
        path for path in sorted(set(old_flat) | set(new_flat))
        if old_flat.get(path) != new_flat.get(path)
    ]
    return changed


def get_effect_for_path(path: str) -> Dict[str, str]:
    normalized = str(path or "").strip()
    if normalized in DORMANT_CONFIG_PATHS:
        return {
            "mode": "unused",
            "component": "unknown",
            "note": "当前版本未发现运行时代码消费该配置项",
        }
    if normalized in _EXACT_EFFECTS:
        return dict(_EXACT_EFFECTS[normalized])
    for prefix, effect in _PREFIX_EFFECTS:
        if normalized.startswith(prefix):
            return dict(effect)
    return {
        "mode": "unknown",
        "component": "unknown",
        "note": "未定义明确生效策略，建议结合日志或测试确认",
    }


def build_reload_plan(changed_paths: Iterable[str]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str, str], List[str]] = {}
    for path in changed_paths:
        effect = get_effect_for_path(path)
        key = (effect["mode"], effect["component"], effect["note"])
        grouped.setdefault(key, []).append(path)

    order = {"unused": 0, "live": 1, "reinit": 2, "restart": 3, "unknown": 4}
    plan: List[Dict[str, Any]] = []
    for (mode, component, note), paths in sorted(
        grouped.items(),
        key=lambda item: (order.get(item[0][0], 99), item[0][1], item[0][2]),
    ):
        plan.append(
            {
                "mode": mode,
                "component": component,
                "note": note,
                "paths": sorted(paths),
            }
        )
    return plan


def _load_override_config(override_path: str) -> Dict[str, Any]:
    file_path = Path(override_path)
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _find_unknown_override_paths(override_config: Dict[str, Any]) -> List[str]:
    flat = flatten_config_paths(override_config)
    return sorted(path for path in flat if path not in DECLARED_CONFIG_PATHS)


def build_config_audit(
    config: Dict[str, Any],
    *,
    override_path: str = "",
) -> Dict[str, Any]:
    flat = flatten_config_paths(config)
    override_config = _load_override_config(override_path) if override_path else {}
    dormant_paths = sorted(path for path in flat if path in DORMANT_CONFIG_PATHS)
    unknown_override_paths = _find_unknown_override_paths(override_config)
    return {
        "declared_paths": len(DECLARED_CONFIG_PATHS),
        "active_paths": len(flat),
        "dormant_paths": dormant_paths,
        "unknown_override_paths": unknown_override_paths,
    }
