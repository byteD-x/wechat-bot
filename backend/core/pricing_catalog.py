from __future__ import annotations

import copy
import html
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import httpx

logger = logging.getLogger(__name__)

_CATALOG_VERSION = "2026-03-17"
_DEFAULT_CATALOG_PATH = os.path.join("data", "pricing_catalog.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _normalize_model_key(value: str) -> str:
    return str(value or "").strip().lower()


def _build_default_catalog() -> Dict[str, Any]:
    verified_at = _CATALOG_VERSION
    return {
        "version": _CATALOG_VERSION,
        "updated_at": verified_at,
        "providers": {
            "openai": {
                "label": "OpenAI",
                "currency": "USD",
                "source_url": "https://openai.com/api/pricing/",
                "refresh_supported": True,
                "notes": "优先读取 OpenAI 官方定价页；未解析到的模型保留本地快照。",
                "models": {
                    "gpt-5": {
                        "input_price_per_1m": 1.25,
                        "output_price_per_1m": 10.0,
                        "source_url": "https://openai.com/api/pricing/",
                        "price_verified_at": verified_at,
                    },
                    "gpt-5-mini": {
                        "input_price_per_1m": 0.25,
                        "output_price_per_1m": 2.0,
                        "source_url": "https://openai.com/api/pricing/",
                        "price_verified_at": verified_at,
                    },
                    "gpt-5-nano": {
                        "input_price_per_1m": 0.05,
                        "output_price_per_1m": 0.4,
                        "source_url": "https://openai.com/api/pricing/",
                        "price_verified_at": verified_at,
                    },
                    "gpt-4.1": {
                        "input_price_per_1m": 2.0,
                        "output_price_per_1m": 8.0,
                        "source_url": "https://openai.com/api/pricing/",
                        "price_verified_at": verified_at,
                    },
                    "gpt-4.1-mini": {
                        "input_price_per_1m": 0.4,
                        "output_price_per_1m": 1.6,
                        "source_url": "https://openai.com/api/pricing/",
                        "price_verified_at": verified_at,
                    },
                    "gpt-4o": {
                        "input_price_per_1m": 2.5,
                        "output_price_per_1m": 10.0,
                        "source_url": "https://openai.com/api/pricing/",
                        "price_verified_at": verified_at,
                    },
                    "gpt-4o-mini": {
                        "input_price_per_1m": 0.15,
                        "output_price_per_1m": 0.6,
                        "source_url": "https://openai.com/api/pricing/",
                        "price_verified_at": verified_at,
                    },
                },
            },
            "deepseek": {
                "label": "DeepSeek",
                "currency": "USD",
                "source_url": "https://api-docs.deepseek.com/quick_start/pricing-details-usd",
                "refresh_supported": True,
                "models": {
                    "deepseek-chat": {
                        "input_price_per_1m": 0.27,
                        "output_price_per_1m": 1.10,
                        "source_url": "https://api-docs.deepseek.com/quick_start/pricing-details-usd",
                        "price_verified_at": verified_at,
                    },
                    "deepseek-reasoner": {
                        "input_price_per_1m": 0.55,
                        "output_price_per_1m": 2.19,
                        "source_url": "https://api-docs.deepseek.com/quick_start/pricing-details-usd",
                        "price_verified_at": verified_at,
                    },
                },
            },
            "groq": {
                "label": "Groq",
                "currency": "USD",
                "source_url": "https://console.groq.com/docs/models",
                "refresh_supported": True,
                "models": {
                    "qwen/qwen3-32b": {
                        "input_price_per_1m": 0.29,
                        "output_price_per_1m": 0.59,
                        "source_url": "https://console.groq.com/docs/models",
                        "price_verified_at": verified_at,
                    },
                    "openai/gpt-oss-120b": {
                        "input_price_per_1m": 0.15,
                        "output_price_per_1m": 0.60,
                        "source_url": "https://console.groq.com/docs/models",
                        "price_verified_at": verified_at,
                    },
                    "openai/gpt-oss-20b": {
                        "input_price_per_1m": 0.10,
                        "output_price_per_1m": 0.50,
                        "source_url": "https://console.groq.com/docs/models",
                        "price_verified_at": verified_at,
                    },
                },
            },
            "openrouter": {
                "label": "OpenRouter",
                "currency": "USD",
                "source_url": "https://openrouter.ai/docs/faq",
                "refresh_supported": True,
                "notes": "OpenRouter 官方 FAQ 说明平台不额外加价，实际价格以模型页为准。",
                "models": {
                    "openai/gpt-5-mini": {
                        "input_price_per_1m": 0.25,
                        "output_price_per_1m": 2.0,
                        "source_url": "https://openrouter.ai/openai/gpt-5-mini/pricing",
                        "price_verified_at": verified_at,
                    },
                },
            },
            "ollama": {
                "label": "Ollama",
                "currency": "LOCAL",
                "source_url": "https://ollama.com/",
                "refresh_supported": False,
                "notes": "本地模型默认按 0 成本处理。",
                "models": {
                    "*": {
                        "input_price_per_1m": 0.0,
                        "output_price_per_1m": 0.0,
                        "source_url": "https://ollama.com/",
                        "price_verified_at": verified_at,
                    }
                },
            },
            "qwen": {
                "label": "Qwen",
                "currency": "CNY",
                "source_url": "https://help.aliyun.com/zh/model-studio/billing/",
                "refresh_supported": False,
                "notes": "首版保留官方快照，复杂分档模型后续可手工覆盖。",
                "models": {
                    "qwen-max-latest": {
                        "input_price_per_1m": 11.743,
                        "output_price_per_1m": 46.971,
                        "source_url": "https://help.aliyun.com/zh/model-studio/billing/",
                        "price_verified_at": verified_at,
                    },
                    "qwen3-max": {
                        "tiers": [
                            {"max_input_tokens": 32000, "input_price_per_1m": 2.5, "output_price_per_1m": 10.0},
                            {"max_input_tokens": 128000, "input_price_per_1m": 4.0, "output_price_per_1m": 16.0},
                            {"max_input_tokens": 1000000, "input_price_per_1m": 7.0, "output_price_per_1m": 28.0},
                        ],
                        "source_url": "https://help.aliyun.com/zh/model-studio/billing/",
                        "price_verified_at": verified_at,
                    },
                    "qwen-plus-latest": {
                        "tiers": [
                            {"max_input_tokens": 128000, "input_price_per_1m": 0.8, "output_price_per_1m": 4.8},
                            {"max_input_tokens": 1000000, "input_price_per_1m": 2.0, "output_price_per_1m": 12.0},
                            {"max_input_tokens": 8000000, "input_price_per_1m": 4.0, "output_price_per_1m": 24.0},
                        ],
                        "source_url": "https://help.aliyun.com/zh/model-studio/billing/",
                        "price_verified_at": verified_at,
                    },
                    "qwen3.5-plus": {
                        "tiers": [
                            {"max_input_tokens": 128000, "input_price_per_1m": 0.8, "output_price_per_1m": 4.8},
                            {"max_input_tokens": 1000000, "input_price_per_1m": 2.0, "output_price_per_1m": 12.0},
                            {"max_input_tokens": 8000000, "input_price_per_1m": 4.0, "output_price_per_1m": 24.0},
                        ],
                        "source_url": "https://help.aliyun.com/zh/model-studio/billing/",
                        "price_verified_at": verified_at,
                    },
                    "qwen3-coder-plus": {
                        "input_price_per_1m": 3.5,
                        "output_price_per_1m": 7.0,
                        "source_url": "https://help.aliyun.com/zh/model-studio/billing/",
                        "price_verified_at": verified_at,
                    },
                    "qwen3-coder-flash": {
                        "tiers": [
                            {"max_input_tokens": 32000, "input_price_per_1m": 1.0, "output_price_per_1m": 4.0},
                            {"max_input_tokens": 128000, "input_price_per_1m": 1.5, "output_price_per_1m": 6.0},
                            {"max_input_tokens": 1000000, "input_price_per_1m": 2.5, "output_price_per_1m": 10.0},
                            {"max_input_tokens": 8000000, "input_price_per_1m": 5.0, "output_price_per_1m": 25.0},
                        ],
                        "source_url": "https://help.aliyun.com/zh/model-studio/billing/",
                        "price_verified_at": verified_at,
                    },
                },
            },
            "doubao": {
                "label": "Doubao",
                "currency": "CNY",
                "source_url": "https://www.volcengine.com/docs/84458/1585097",
                "refresh_supported": False,
                "notes": "官方模型价格分档复杂，首版保留手工覆盖入口但不内置自动定价。",
                "models": {},
            },
        },
    }


class PricingCatalog:
    def __init__(self, data_path: str = _DEFAULT_CATALOG_PATH) -> None:
        self.data_path = data_path
        self._lock = threading.RLock()
        self._catalog = _build_default_catalog()
        self._load_local_snapshot()

    def _load_local_snapshot(self) -> None:
        if not os.path.exists(self.data_path):
            return
        try:
            with open(self.data_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if isinstance(payload, dict):
                self._catalog = _deep_merge(self._catalog, payload)
        except Exception as exc:
            logger.warning("Failed to load pricing catalog snapshot: %s", exc)

    def _save_local_snapshot(self) -> None:
        os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as file:
            json.dump(self._catalog, file, ensure_ascii=False, indent=2)

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            snapshot = copy.deepcopy(self._catalog)
            snapshot["data_path"] = os.path.abspath(self.data_path)
            return snapshot

    def resolve_price(
        self,
        provider_id: str,
        model: str,
        *,
        prompt_tokens: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        provider_key = str(provider_id or "").strip().lower()
        model_key = _normalize_model_key(model)
        if not provider_key or not model_key:
            return None
        with self._lock:
            provider = copy.deepcopy(self._catalog.get("providers", {}).get(provider_key) or {})
        if not provider:
            return None
        models = provider.get("models") or {}
        entry = copy.deepcopy(models.get(model_key) or models.get(model) or {})
        if not entry and provider_key == "ollama":
            entry = copy.deepcopy(models.get("*") or {})
        if not entry:
            return None

        resolved = {
            "provider_id": provider_key,
            "provider_label": provider.get("label") or provider_key,
            "model": model,
            "currency": provider.get("currency") or "USD",
            "source_url": entry.get("source_url") or provider.get("source_url") or "",
            "price_verified_at": entry.get("price_verified_at") or provider.get("updated_at") or "",
            "refresh_supported": bool(provider.get("refresh_supported", False)),
            "notes": provider.get("notes") or "",
        }
        tiers = entry.get("tiers") or []
        if isinstance(tiers, list) and tiers:
            token_count = max(0, int(prompt_tokens or 0))
            selected = None
            for tier in tiers:
                max_input = int(tier.get("max_input_tokens") or 0)
                if max_input <= 0 or token_count <= max_input:
                    selected = tier
                    break
            selected = selected or tiers[-1]
            resolved["input_price_per_1m"] = float(selected.get("input_price_per_1m") or 0.0)
            resolved["output_price_per_1m"] = float(selected.get("output_price_per_1m") or 0.0)
            resolved["pricing_mode"] = "tiered"
            resolved["matched_tier"] = copy.deepcopy(selected)
            resolved["tiers"] = copy.deepcopy(tiers)
            return resolved

        if "input_price_per_1m" not in entry or "output_price_per_1m" not in entry:
            return None
        resolved["input_price_per_1m"] = float(entry.get("input_price_per_1m") or 0.0)
        resolved["output_price_per_1m"] = float(entry.get("output_price_per_1m") or 0.0)
        resolved["pricing_mode"] = "flat"
        return resolved

    def refresh(self, providers: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        wanted = {
            str(item or "").strip().lower()
            for item in (providers or self._catalog.get("providers", {}).keys())
            if str(item or "").strip()
        }
        results: Dict[str, Any] = {}
        with self._lock:
            for provider_id in wanted:
                try:
                    if provider_id == "openai":
                        results[provider_id] = self._refresh_openai_locked()
                    elif provider_id == "deepseek":
                        results[provider_id] = self._refresh_deepseek_locked()
                    elif provider_id == "groq":
                        results[provider_id] = self._refresh_groq_locked()
                    elif provider_id == "openrouter":
                        results[provider_id] = self._refresh_openrouter_locked()
                    else:
                        results[provider_id] = {
                            "success": False,
                            "message": "该提供商当前仅支持内置官方快照或手工覆盖。",
                        }
                except Exception as exc:
                    logger.warning("刷新价格目录失败 provider=%s: %s", provider_id, exc)
                    results[provider_id] = {"success": False, "message": str(exc)}
            self._catalog["updated_at"] = _now_iso()
            self._save_local_snapshot()
        return {"success": True, "results": results, "updated_at": self._catalog["updated_at"]}

    @staticmethod
    def _to_plain_text(raw: str) -> str:
        text = html.unescape(str(raw or ""))
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _refresh_openai_locked(self) -> Dict[str, Any]:
        url = "https://openai.com/api/pricing/"
        text = self._to_plain_text(httpx.get(url, timeout=20, follow_redirects=True).text)
        provider = self._catalog["providers"]["openai"]
        verified_at = _now_iso()
        aliases = {
            "gpt-5": "GPT-5",
            "gpt-5-mini": "GPT-5 mini",
            "gpt-5-nano": "GPT-5 nano",
            "gpt-4.1": "GPT-4.1",
            "gpt-4.1-mini": "GPT-4.1 mini",
            "gpt-4o": "GPT-4o",
            "gpt-4o-mini": "GPT-4o mini",
        }
        refreshed = 0
        for model_name, heading in aliases.items():
            match = re.search(
                rf"{re.escape(heading)}.*?Input:\s*\$([0-9.]+)\s*/\s*1M tokens.*?Output:\s*\$([0-9.]+)\s*/\s*1M tokens",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not match:
                continue
            provider["models"][model_name] = {
                "input_price_per_1m": float(match.group(1)),
                "output_price_per_1m": float(match.group(2)),
                "source_url": url,
                "price_verified_at": verified_at,
            }
            refreshed += 1

        if refreshed <= 0:
            raise RuntimeError("未从 OpenAI 官方页面解析到价格。")
        provider["updated_at"] = verified_at
        return {"success": True, "message": "OpenAI 官方价格已刷新。", "models": refreshed}

    def _refresh_deepseek_locked(self) -> Dict[str, Any]:
        url = "https://api-docs.deepseek.com/quick_start/pricing-details-usd"
        text = self._to_plain_text(httpx.get(url, timeout=15, follow_redirects=True).text)
        verified_at = _now_iso()
        provider = self._catalog["providers"]["deepseek"]
        aliases = {
            "deepseek-chat": "deepseek-chat",
            "deepseek-reasoner": "deepseek-reasoner",
        }
        refreshed = 0
        for model_name, heading in aliases.items():
            match = re.search(
                rf"{re.escape(heading)}.*?\$([0-9.]+)\s+\$([0-9.]+)\s+\$([0-9.]+)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not match:
                continue
            provider["models"][model_name] = {
                "input_price_per_1m": float(match.group(2)),
                "output_price_per_1m": float(match.group(3)),
                "source_url": url,
                "price_verified_at": verified_at,
            }
            refreshed += 1
        if refreshed <= 0:
            raise RuntimeError("未从 DeepSeek 官方页面解析到价格。")
        provider["updated_at"] = verified_at
        return {"success": True, "message": "DeepSeek 官方价格已刷新。", "models": refreshed}

    def _refresh_groq_locked(self) -> Dict[str, Any]:
        provider = self._catalog["providers"]["groq"]
        refreshed = 0
        verified_at = _now_iso()
        for model_name in list((provider.get("models") or {}).keys()):
            url = f"https://console.groq.com/docs/model/{model_name}"
            text = self._to_plain_text(httpx.get(url, timeout=20, follow_redirects=True).text)
            model_match = re.search(
                r"PRICING\s+Input\s+\$([0-9.]+).*?Output\s+\$([0-9.]+)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not model_match:
                continue
            provider["models"][model_name] = {
                "input_price_per_1m": float(model_match.group(1)),
                "output_price_per_1m": float(model_match.group(2)),
                "source_url": url,
                "price_verified_at": verified_at,
            }
            refreshed += 1
        if refreshed <= 0:
            raise RuntimeError("未从 Groq 官方页面解析到价格。")
        provider["updated_at"] = verified_at
        return {"success": True, "message": "Groq 官方价格已刷新。", "models": refreshed}

    def _refresh_openrouter_locked(self) -> Dict[str, Any]:
        provider = self._catalog["providers"]["openrouter"]
        refreshed = 0
        verified_at = _now_iso()
        for model_name in list((provider.get("models") or {}).keys()):
            url = f"https://openrouter.ai/{model_name}/pricing"
            text = self._to_plain_text(httpx.get(url, timeout=20, follow_redirects=True).text)
            match = re.search(
                r"\$([0-9.]+)\s*/M input tokens.*?\$([0-9.]+)\s*/M output tokens",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not match:
                continue
            provider["models"][model_name] = {
                "input_price_per_1m": float(match.group(1)),
                "output_price_per_1m": float(match.group(2)),
                "source_url": url,
                "price_verified_at": verified_at,
            }
            refreshed += 1
        if refreshed <= 0:
            raise RuntimeError("未从 OpenRouter 官方模型页解析到价格。")
        provider["updated_at"] = verified_at
        return {"success": True, "message": "OpenRouter 官方价格已刷新。", "models": refreshed}


_pricing_catalog: Optional[PricingCatalog] = None


def get_pricing_catalog(data_path: str = _DEFAULT_CATALOG_PATH) -> PricingCatalog:
    global _pricing_catalog
    if _pricing_catalog is None or _pricing_catalog.data_path != data_path:
        _pricing_catalog = PricingCatalog(data_path=data_path)
    return _pricing_catalog
