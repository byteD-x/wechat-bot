"""
Centralized provider and model catalog for the settings UI.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

MODEL_CATALOG_UPDATED_AT = "2026-03-13"

_PROVIDERS = [
    {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_key_url": "https://platform.openai.com/api-keys",
        "aliases": ["openai", "gpt"],
        "default_model": "gpt-5-mini",
        "models": [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
        ],
    },
    {
        "id": "doubao",
        "label": "Doubao (豆包)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key_url": "https://console.volcengine.com/ark",
        "aliases": ["doubao", "豆包", "ark", "volc"],
        "default_model": "doubao-seed-1-8-251228",
        "models": [
            "doubao-seed-1-8-251228",
            "doubao-seed-1-6-250615",
            "doubao-seed-1-6-thinking-250615",
            "doubao-seed-1-6-flash-250715",
        ],
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_url": "https://platform.deepseek.com/api_keys",
        "aliases": ["deepseek"],
        "default_model": "deepseek-chat",
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    },
    {
        "id": "qwen",
        "label": "Qwen (通义千问)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_url": "https://dashscope.console.aliyun.com/apiKey",
        "aliases": ["qwen", "通义", "千问", "dashscope", "百炼"],
        "default_model": "qwen3.5-plus",
        "models": [
            "qwen-max-latest",
            "qwen-plus-latest",
            "qwen-flash-latest",
            "qwen3-max",
            "qwen3.5-plus",
            "qwen3.5-flash",
            "qwen3-coder-plus",
            "qwen3-coder-flash",
        ],
    },
    {
        "id": "zhipu",
        "label": "Zhipu (智谱)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "aliases": ["zhipu", "glm", "智谱"],
        "default_model": "glm-4.5-air",
        "models": [
            "glm-5-plus",
            "glm-5-air",
            "glm-5-flash",
            "glm-4.6",
            "glm-4.5-air",
            "glm-4.5-flash",
        ],
    },
    {
        "id": "moonshot",
        "label": "Moonshot (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_url": "https://platform.moonshot.cn/console/api-keys",
        "aliases": ["moonshot", "kimi"],
        "default_model": "kimi-k2-turbo-preview",
        "models": [
            "kimi-k2-turbo-preview",
            "kimi-k2-0711-preview",
            "kimi-thinking-preview",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
    },
    {
        "id": "groq",
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_url": "https://console.groq.com/keys",
        "aliases": ["groq"],
        "default_model": "qwen/qwen3-32b",
        "models": [
            "qwen/qwen3-32b",
            "openai/gpt-oss-120b",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "deepseek-r1-distill-llama-70b",
        ],
    },
    {
        "id": "siliconflow",
        "label": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_url": "https://cloud.siliconflow.cn/account/ak",
        "aliases": ["siliconflow", "silicon", "硅基"],
        "default_model": "deepseek-ai/DeepSeek-V3",
        "models": [
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen3-32B",
            "THUDM/GLM-4.5-Air",
        ],
    },
    {
        "id": "mistral",
        "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "api_key_url": "https://console.mistral.ai/api-keys/",
        "aliases": ["mistral"],
        "default_model": "mistral-medium-latest",
        "models": [
            "mistral-medium-latest",
            "mistral-small-latest",
            "codestral-latest",
            "ministral-8b-latest",
        ],
    },
    {
        "id": "perplexity",
        "label": "Perplexity",
        "base_url": "https://api.perplexity.ai",
        "api_key_url": "https://www.perplexity.ai/settings/api",
        "aliases": ["perplexity", "sonar"],
        "default_model": "sonar-pro",
        "models": [
            "sonar",
            "sonar-pro",
            "sonar-reasoning",
            "sonar-reasoning-pro",
        ],
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_url": "https://openrouter.ai/keys",
        "aliases": ["openrouter"],
        "default_model": "openai/gpt-5-mini",
        "models": [
            "openai/gpt-5-mini",
            "google/gemini-2.5-flash",
            "deepseek/deepseek-chat-v3.1",
            "qwen/qwen3-32b",
        ],
    },
    {
        "id": "together",
        "label": "Together",
        "base_url": "https://api.together.xyz/v1",
        "api_key_url": "https://api.together.xyz/settings/api-keys",
        "aliases": ["together"],
        "default_model": "Qwen/Qwen3-32B",
        "models": [
            "Qwen/Qwen3-32B",
            "deepseek-ai/DeepSeek-V3.1",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ],
    },
    {
        "id": "fireworks",
        "label": "Fireworks",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_key_url": "https://fireworks.ai/account/api-keys",
        "aliases": ["fireworks"],
        "default_model": "accounts/fireworks/models/qwen3-30b-a3b",
        "models": [
            "accounts/fireworks/models/qwen3-30b-a3b",
            "accounts/fireworks/models/deepseek-v3p1",
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
        ],
    },
    {
        "id": "ollama",
        "label": "Ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key_url": "https://ollama.com/",
        "aliases": ["ollama"],
        "default_model": "qwen3",
        "allow_empty_key": True,
        "models": [
            "qwen3",
            "llama3.1",
            "gemma3",
            "mistral",
        ],
    },
]


def get_model_catalog() -> Dict[str, Any]:
    return {
        "updated_at": MODEL_CATALOG_UPDATED_AT,
        "providers": deepcopy(_PROVIDERS),
    }


def get_provider_by_id(provider_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not provider_id:
        return None

    wanted = str(provider_id).strip().lower()
    for provider in _PROVIDERS:
        if provider["id"] == wanted:
            return deepcopy(provider)
    return None


def infer_provider_id(
    *,
    provider_id: Optional[str] = None,
    preset_name: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[str]:
    if provider_id:
        provider = get_provider_by_id(provider_id)
        if provider:
            return provider["id"]

    lower_name = str(preset_name or "").strip().lower()
    lower_base_url = str(base_url or "").strip().lower()
    lower_model = str(model or "").strip().lower()

    for provider in _PROVIDERS:
        if lower_base_url and lower_base_url.startswith(provider["base_url"].lower()):
            return provider["id"]

        for alias in provider.get("aliases", []):
            alias_lower = alias.lower()
            if lower_name and alias_lower in lower_name:
                return provider["id"]
            if lower_model and alias_lower in lower_model:
                return provider["id"]

        if lower_model and lower_model in {m.lower() for m in provider.get("models", [])}:
            return provider["id"]

    return None


def merge_provider_defaults(preset: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(preset or {})
    provider_id = infer_provider_id(
        provider_id=merged.get("provider_id"),
        preset_name=merged.get("name"),
        base_url=merged.get("base_url"),
        model=merged.get("model"),
    )

    if not provider_id:
        return merged

    provider = get_provider_by_id(provider_id)
    if not provider:
        return merged

    merged["provider_id"] = provider_id
    merged.setdefault("base_url", provider.get("base_url"))
    merged.setdefault("allow_empty_key", bool(provider.get("allow_empty_key", False)))
    merged.setdefault("model", provider.get("default_model"))
    return merged
