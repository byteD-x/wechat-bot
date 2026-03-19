"""
配置工具模块 - 负责相关配置的加载、解析和规范化。
"""

import importlib.util
import json
import logging
from typing import Any, Dict, List, Optional

from .common import as_int, as_float, as_optional_int, as_optional_str, iter_items, truncate_text

__all__ = [
    "normalize_system_prompt",
    "load_config_py",
    "load_config_json",
    "load_config",
    "get_setting",
    "is_placeholder_key",
    "build_api_candidates",
    "get_model_alias",
    "resolve_system_prompt",
]


def normalize_system_prompt(value: Any) -> str:
    """
    规范化 system_prompt 配置。
    支持字符串或字符串列表（自动合并）。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(v).strip() for v in value if v)
    return str(value).strip()


def load_config_py(path: str) -> Dict[str, Any]:
    """动态加载 .py 配置文件，返回 CONFIG 字典。"""
    spec = importlib.util.spec_from_file_location("config_module", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load config from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "CONFIG", {})


def load_config_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Config JSON must be an object: {path}")
    return data


def load_config(path: str) -> Dict[str, Any]:
    """加载配置文件（目前仅支持 .py），并使用 Pydantic 验证。"""
    raw_config = (
        load_config_json(path)
        if str(path or "").strip().lower().endswith(".json")
        else load_config_py(path)
    )

    # 验证并规范化
    try:
        # Lazy import: Pydantic schema validation is relatively heavy, and most
        # modules only need lightweight helpers (e.g. normalize_system_prompt).
        from backend.config_schemas import AppConfig

        # Pydantic 验证
        app_config = AppConfig(**raw_config)
        # 转换回字典，使用 mode='json' 确保枚举等类型被序列化为基本类型
        validated_config = app_config.model_dump(mode="json")
        return validated_config
    except Exception as e:
        logging.error(f"配置验证失败: {e}。将使用原始配置。")
        return raw_config


def get_setting(
    settings: Dict[str, Any], key: str, default: Any = None, type_func: Any = None
) -> Any:
    """安全获取配置项，支持类型转换。"""
    val = settings.get(key, default)
    if type_func and val is not None:
        return type_func(val)
    return val


def is_placeholder_key(key: Optional[str]) -> bool:
    """检查 API Key 是否为占位符。"""
    if not key:
        return True
    k = key.strip()
    return k.startswith("YOUR_") or ("KEY" in k and len(k) < 10)


def build_api_candidates(api_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构建 API 候选列表，支持多预设。"""
    # 按照 active_preset > 其他 presets > root_config 顺序构建候选列表
    candidates = []
    seen_candidates = set()

    def append_candidate(candidate: Dict[str, Any], *, fallback_name: str = "") -> None:
        if not isinstance(candidate, dict):
            return
        normalized = dict(candidate)
        name = str(normalized.get("name") or fallback_name or "").strip()
        if name:
            normalized["name"] = name
        dedupe_key = name or json.dumps(
            {
                "provider_id": normalized.get("provider_id"),
                "base_url": normalized.get("base_url"),
                "model": normalized.get("model"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if dedupe_key in seen_candidates:
            return
        seen_candidates.add(dedupe_key)
        candidates.append(normalized)

    active_name = str(api_cfg.get("active_preset") or "").strip()
    presets_data = api_cfg.get("presets", [])

    # 统一转换为字典映射 {name: config}
    presets_map = {}
    if isinstance(presets_data, list):
        for p in presets_data:
            if isinstance(p, dict) and p.get("name"):
                presets_map[str(p["name"])] = p
    elif isinstance(presets_data, dict):
        presets_map = presets_data

    # 1. Active Preset (只取匹配的一个)
    if active_name and active_name in presets_map:
        append_candidate(dict(presets_map[active_name]), fallback_name=active_name)

    # 2. 其他预设，当前激活项不可用时允许自动回退
    for name, cfg in presets_map.items():
        if name == active_name:
            continue
        append_candidate(dict(cfg), fallback_name=name)

    # 2. 根配置 (作为后备或旧版本兼容)
    # 只有当 api_key 不是占位符时才添加，或者是 root_config 模式
    # 这里我们宽松一点，只要 base_url 存在就添加，后续由 validate 过滤
    root_candidate = {
        "name": "root_config",
        "base_url": api_cfg.get("base_url"),
        "api_key": api_cfg.get("api_key"),
        "model": api_cfg.get("model"),
        "embedding_model": api_cfg.get("embedding_model"),
        "timeout_sec": api_cfg.get("timeout_sec"),
        "max_retries": api_cfg.get("max_retries"),
        "temperature": api_cfg.get("temperature"),
        "max_tokens": api_cfg.get("max_tokens"),
        "alias": api_cfg.get("alias"),
    }

    if root_candidate.get("base_url"):
        append_candidate(root_candidate, fallback_name="root_config")

    return candidates


def get_model_alias(ai_client: Any) -> str:
    """获取 AI 客户端的模型别名或名称。"""
    if hasattr(ai_client, "model_alias") and ai_client.model_alias:
        return str(ai_client.model_alias)
    if hasattr(ai_client, "model"):
        return str(ai_client.model)
    return "unknown"


def resolve_system_prompt(
    event: Any,
    bot_cfg: Dict[str, Any],
    user_profile: Optional[Dict[str, Any]],
    emotion: Optional[Any],
    context: List[Any],
) -> str:
    """
    解析最终的 System Prompt。

    支持逻辑：
    1. 特定会话覆盖 (Overrides)
    2. 基础 Prompt 规范化
    3. 注入用户画像 (如果启用)
    4. 注入当前情绪 (如果启用)
    """
    base_prompt = bot_cfg.get("system_prompt", "")
    overrides = bot_cfg.get("system_prompt_overrides", {})

    # 1. 覆盖检查
    # 匹配精确名称或简单部分匹配（暂时保持简单）
    chat_name = getattr(event, "chat_name", "")
    if chat_name in overrides:
        base_prompt = overrides[chat_name]

    contact_prompt = ""
    if isinstance(user_profile, dict):
        contact_prompt = str(user_profile.get("contact_prompt") or "").strip()
    elif user_profile is not None:
        contact_prompt = str(getattr(user_profile, "contact_prompt", "") or "").strip()
    if contact_prompt:
        base_prompt = contact_prompt

    # 2. 规范化
    system_prompt = normalize_system_prompt(base_prompt)

    template = system_prompt
    has_history_placeholder = "{history_context}" in template
    has_profile_placeholder = "{user_profile}" in template
    has_emotion_placeholder = "{emotion_hint}" in template
    has_time_placeholder = "{time_hint}" in template
    has_style_placeholder = "{style_hint}" in template

    def _build_profile_text(profile: Any) -> str:
        profile_map: Dict[str, Any] = {}
        if profile is None:
            return ""
        if isinstance(profile, dict):
            profile_map = dict(profile)
        elif hasattr(profile, "model_dump"):
            try:
                profile_map = dict(profile.model_dump(mode="json"))
            except Exception:
                profile_map = {}
        elif hasattr(profile, "dict"):
            try:
                profile_map = dict(profile.dict())
            except Exception:
                profile_map = {}
        else:
            try:
                profile_map = dict(getattr(profile, "__dict__", {}) or {})
            except Exception:
                profile_map = {}
        profile_summary = str(profile_map.get("profile_summary") or "").strip()
        if profile_summary:
            return profile_summary
        profile_map.pop("raw_item", None)
        profile_text = "\n".join(
            f"- {k}: {v}" for k, v in profile_map.items() if k and v not in (None, "")
        )
        return profile_text.strip()

    def _build_history_context(items: List[Any], max_items: int = 6) -> str:
        lines: List[str] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in ("user", "assistant"):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            content = truncate_text(content, 160)
            prefix = "User" if role == "user" else "Assistant"
            lines.append(f"{prefix}: {content}")
        if not lines:
            return ""
        if max_items > 0:
            lines = lines[-max_items:]
        return "\n".join(lines).strip()

    def _build_emotion_hint(value: Any) -> str:
        if value is None:
            return ""
        emotion_label = str(getattr(value, "emotion", "") or str(value) or "").strip()
        if not emotion_label:
            return ""
        parts = [f"【当前情绪】{emotion_label}"]
        confidence = getattr(value, "confidence", None)
        if confidence is not None:
            try:
                parts.append(f"【置信度】{float(confidence):.2f}")
            except Exception:
                parts.append(f"【置信度】{confidence}")
        intensity = getattr(value, "intensity", None)
        if intensity is not None:
            try:
                parts.append(f"【强度】{int(intensity)}/5")
            except Exception:
                parts.append(f"【强度】{intensity}")
        suggested_tone = str(getattr(value, "suggested_tone", "") or "").strip()
        if suggested_tone:
            parts.append(f"【建议语气】{suggested_tone}")
        return "\n".join(parts).strip()

    profile_text = (
        _build_profile_text(user_profile)
        if bot_cfg.get("profile_inject_in_prompt", False)
        else ""
    )
    history_context_text = _build_history_context(context) if has_history_placeholder else ""
    emotion_hint_text = (
        _build_emotion_hint(emotion)
        if bot_cfg.get("emotion_inject_in_prompt", False)
        else ""
    )

    time_hint_text = ""
    if has_time_placeholder:
        try:
            from backend.core.emotion import get_time_aware_prompt_addition

            time_hint_text = str(get_time_aware_prompt_addition() or "").strip()
        except Exception:
            time_hint_text = ""

    style_hint_text = ""
    if has_style_placeholder:
        try:
            from backend.core.emotion import analyze_conversation_style, get_style_adaptation_hint

            style_info = analyze_conversation_style(
                [item for item in (context or []) if isinstance(item, dict)]
            )
            hint = str(get_style_adaptation_hint(style_info) or "").strip()
            if hint:
                style_hint_text = f"【对话风格】{hint}"
        except Exception:
            style_hint_text = ""

    # Replace placeholders (if present) to avoid leaking template markers to the model.
    if has_history_placeholder:
        system_prompt = system_prompt.replace("{history_context}", history_context_text)
    if has_profile_placeholder:
        system_prompt = system_prompt.replace("{user_profile}", profile_text)
    if has_emotion_placeholder:
        replacement = (emotion_hint_text + "\n") if emotion_hint_text else ""
        system_prompt = system_prompt.replace("{emotion_hint}", replacement)
    if has_time_placeholder:
        replacement = (time_hint_text + "\n") if time_hint_text else ""
        system_prompt = system_prompt.replace("{time_hint}", replacement)
    if has_style_placeholder:
        replacement = (style_hint_text + "\n") if style_hint_text else ""
        system_prompt = system_prompt.replace("{style_hint}", replacement)

    # Backward compatible injection for prompts without placeholders.
    if (
        not has_profile_placeholder
        and bot_cfg.get("profile_inject_in_prompt", False)
        and profile_text
    ):
        system_prompt += f"\n\n[User Profile]\n{profile_text}"
    if (
        not has_emotion_placeholder
        and bot_cfg.get("emotion_inject_in_prompt", False)
        and emotion_hint_text
    ):
        system_prompt += f"\n\n[Current Emotion]\n{emotion_hint_text}"

    return system_prompt
