from __future__ import annotations

import math
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.model_catalog import infer_provider_id
from backend.utils.common import truncate_text

from .pricing_catalog import PricingCatalog, get_pricing_catalog


def _estimate_text_tokens(text: str) -> int:
    raw = str(text or "")
    if not raw:
        return 0
    ascii_count = sum(1 for char in raw if ord(char) < 128)
    cjk_count = max(0, len(raw) - ascii_count)
    ascii_tokens = max(1, ascii_count // 4) if ascii_count > 0 else 0
    return max(1, cjk_count + ascii_tokens)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_period(period: str) -> Tuple[str, Optional[int], Optional[int]]:
    now = datetime.now()
    normalized = str(period or "30d").strip().lower()
    if normalized == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return normalized, int(start.timestamp()), int(now.timestamp())
    if normalized == "7d":
        start = now - timedelta(days=7)
        return normalized, int(start.timestamp()), int(now.timestamp())
    if normalized == "30d":
        start = now - timedelta(days=30)
        return normalized, int(start.timestamp()), int(now.timestamp())
    return "all", None, int(now.timestamp())


def _build_preset_index(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    api_cfg = dict(config.get("api", {}) or {})
    presets = api_cfg.get("presets") or []
    mapping: Dict[str, Dict[str, Any]] = {}
    if isinstance(presets, list):
        for preset in presets:
            if not isinstance(preset, dict):
                continue
            name = str(preset.get("name") or "").strip()
            if not name:
                continue
            provider_id = infer_provider_id(
                provider_id=preset.get("provider_id"),
                preset_name=name,
                base_url=preset.get("base_url"),
                model=preset.get("model"),
            )
            mapping[name] = {
                "provider_id": provider_id or "",
                "model": str(preset.get("model") or "").strip(),
                "base_url": str(preset.get("base_url") or "").strip(),
            }
    return mapping


def _as_currency_groups(totals: Dict[str, float]) -> List[Dict[str, Any]]:
    items = []
    for currency, total in totals.items():
        rounded = round(float(total or 0.0), 8)
        items.append({"currency": currency, "total_cost": rounded})
    items.sort(key=lambda item: item["currency"])
    return items


def _merge_costs(target: Dict[str, float], currency: str, amount: Optional[float]) -> None:
    value = _safe_float(amount)
    if value is None:
        return
    target[currency or "UNKNOWN"] = round(target.get(currency or "UNKNOWN", 0.0) + value, 8)


class CostAnalyticsService:
    def __init__(self, pricing_catalog: Optional[PricingCatalog] = None) -> None:
        self.pricing_catalog = pricing_catalog or get_pricing_catalog()

    async def get_pricing_snapshot(self) -> Dict[str, Any]:
        return self.pricing_catalog.get_snapshot()

    async def refresh_pricing(self, providers: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        return self.pricing_catalog.refresh(providers=providers)

    async def get_summary(
        self,
        memory,
        config: Dict[str, Any],
        *,
        period: str = "30d",
        provider_id: str = "",
        model: str = "",
        only_priced: bool = False,
        include_estimated: bool = True,
    ) -> Dict[str, Any]:
        records, filters = await self._list_records(
            memory,
            config,
            period=period,
            provider_id=provider_id,
            model=model,
            only_priced=only_priced,
            include_estimated=include_estimated,
        )
        overview = self._build_overview(records)
        models = self._build_model_breakdown(records)
        options = self._build_options(records)
        return {
            "success": True,
            "filters": filters,
            "overview": overview,
            "models": models,
            "options": options,
        }

    async def get_sessions(
        self,
        memory,
        config: Dict[str, Any],
        *,
        period: str = "30d",
        provider_id: str = "",
        model: str = "",
        only_priced: bool = False,
        include_estimated: bool = True,
    ) -> Dict[str, Any]:
        records, filters = await self._list_records(
            memory,
            config,
            period=period,
            provider_id=provider_id,
            model=model,
            only_priced=only_priced,
            include_estimated=include_estimated,
        )
        sessions = self._build_session_summaries(records)
        return {"success": True, "filters": filters, "sessions": sessions, "total": len(sessions)}

    async def get_session_details(
        self,
        memory,
        config: Dict[str, Any],
        *,
        chat_id: str,
        period: str = "30d",
        provider_id: str = "",
        model: str = "",
        only_priced: bool = False,
        include_estimated: bool = True,
    ) -> Dict[str, Any]:
        records, filters = await self._list_records(
            memory,
            config,
            period=period,
            provider_id=provider_id,
            model=model,
            chat_id=chat_id,
            only_priced=only_priced,
            include_estimated=include_estimated,
        )
        details = sorted(records, key=lambda item: item["timestamp"], reverse=True)
        return {"success": True, "filters": filters, "chat_id": chat_id, "records": details, "total": len(details)}

    async def _list_records(
        self,
        memory,
        config: Dict[str, Any],
        *,
        period: str,
        provider_id: str = "",
        model: str = "",
        chat_id: str = "",
        only_priced: bool = False,
        include_estimated: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        normalized_period, start_ts, end_ts = _normalize_period(period)
        messages = await memory.list_messages_for_analysis(
            chat_id=chat_id,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
        )
        presets = _build_preset_index(config)
        records = self._enrich_records(messages, presets)

        normalized_provider = str(provider_id or "").strip().lower()
        normalized_model = str(model or "").strip().lower()
        filtered: List[Dict[str, Any]] = []
        for item in records:
            if normalized_provider and item["provider_id"] != normalized_provider:
                continue
            if normalized_model and item["model"].lower() != normalized_model:
                continue
            if only_priced and not item["pricing_available"]:
                continue
            if not include_estimated and (item["estimated"]["tokens"] or item["estimated"]["pricing"]):
                continue
            filtered.append(item)

        filters = {
            "period": normalized_period,
            "provider_id": normalized_provider,
            "model": model,
            "chat_id": chat_id,
            "only_priced": only_priced,
            "include_estimated": include_estimated,
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
        }
        return filtered, filters

    def _enrich_records(
        self,
        messages: List[Dict[str, Any]],
        preset_index: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        previous_user_by_chat: Dict[str, Dict[str, Any]] = {}

        for message in messages:
            chat_id = str(message.get("wx_id") or "").strip()
            role = str(message.get("role") or "").strip().lower()
            content = str(message.get("content") or "")
            metadata = dict(message.get("metadata") or {})

            if role == "user":
                previous_user_by_chat[chat_id] = {
                    "content": content,
                    "timestamp": int(message.get("created_at") or 0),
                }
                continue
            if role != "assistant":
                continue

            token_meta = metadata.get("tokens") or {}
            previous_user = previous_user_by_chat.get(chat_id) or {}
            user_text = str(previous_user.get("content") or "")
            prompt_tokens = _safe_int(token_meta.get("user"), -1)
            completion_tokens = _safe_int(token_meta.get("reply"), -1)
            total_tokens = _safe_int(token_meta.get("total"), -1)
            token_estimated = False

            if prompt_tokens < 0:
                prompt_tokens = _estimate_text_tokens(user_text) if user_text else 0
                token_estimated = True
            if completion_tokens < 0:
                completion_tokens = _estimate_text_tokens(content)
                token_estimated = True
            if total_tokens < 0:
                total_tokens = prompt_tokens + completion_tokens
                token_estimated = True

            preset_name = str(metadata.get("preset") or "").strip()
            model_name = str(metadata.get("model") or "").strip()
            model_alias = str(metadata.get("model_alias") or "").strip()
            preset_info = preset_index.get(preset_name) or {}
            provider = str(metadata.get("provider_id") or "").strip().lower()
            if not provider:
                provider = str(preset_info.get("provider_id") or "").strip().lower()
            if not model_name:
                model_name = model_alias
            if not model_name:
                model_name = str(preset_info.get("model") or "").strip()
            if not model_name:
                model_name = preset_name
            if not provider:
                provider = infer_provider_id(
                    provider_id=None,
                    preset_name=preset_name,
                    base_url=preset_info.get("base_url"),
                    model=model_name,
                ) or ""

            pricing_meta = metadata.get("pricing") or {}
            pricing = None
            pricing_estimated = False
            if pricing_meta and "input_price_per_1m" in pricing_meta and "output_price_per_1m" in pricing_meta:
                pricing = {
                    "currency": str(pricing_meta.get("currency") or "USD"),
                    "input_price_per_1m": float(pricing_meta.get("input_price_per_1m") or 0.0),
                    "output_price_per_1m": float(pricing_meta.get("output_price_per_1m") or 0.0),
                    "source_url": str(pricing_meta.get("source_url") or metadata.get("source_url") or ""),
                    "price_verified_at": str(pricing_meta.get("price_verified_at") or metadata.get("price_verified_at") or ""),
                    "pricing_mode": str(pricing_meta.get("pricing_mode") or "flat"),
                }
            elif provider and model_name:
                pricing = self.pricing_catalog.resolve_price(
                    provider,
                    model_name,
                    prompt_tokens=prompt_tokens,
                )
                pricing_estimated = pricing is not None

            cost_meta = metadata.get("cost") or {}
            input_cost = _safe_float(cost_meta.get("input_cost"))
            output_cost = _safe_float(cost_meta.get("output_cost"))
            total_cost = _safe_float(cost_meta.get("total_cost"))
            if pricing and total_cost is None:
                input_cost = round((prompt_tokens / 1_000_000) * float(pricing.get("input_price_per_1m") or 0.0), 8)
                output_cost = round((completion_tokens / 1_000_000) * float(pricing.get("output_price_per_1m") or 0.0), 8)
                total_cost = round((input_cost or 0.0) + (output_cost or 0.0), 8)

            currency = str((pricing or {}).get("currency") or "USD")
            pricing_available = pricing is not None and total_cost is not None
            records.append({
                "id": int(message.get("id") or 0),
                "chat_id": chat_id,
                "display_name": str(message.get("display_name") or chat_id),
                "timestamp": int(message.get("created_at") or 0),
                "reply_text": content,
                "reply_preview": truncate_text(content.replace("\n", " "), 80),
                "model": model_name or "未识别模型",
                "provider_id": provider or "",
                "provider_label": str((pricing or {}).get("provider_label") or provider or ""),
                "preset": preset_name,
                "tokens": {
                    "user": prompt_tokens,
                    "reply": completion_tokens,
                    "total": total_tokens,
                },
                "pricing": pricing,
                "pricing_available": pricing_available,
                "currency": currency,
                "cost": {
                    "input_cost": input_cost,
                    "output_cost": output_cost,
                    "total_cost": total_cost,
                },
                "estimated": {
                    "tokens": token_estimated,
                    "pricing": pricing_estimated,
                },
                "source_url": str((pricing or {}).get("source_url") or metadata.get("source_url") or ""),
                "price_verified_at": str((pricing or {}).get("price_verified_at") or metadata.get("price_verified_at") or ""),
            })
        return records

    def _build_overview(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        prompt_tokens = sum(item["tokens"]["user"] for item in records)
        completion_tokens = sum(item["tokens"]["reply"] for item in records)
        total_tokens = sum(item["tokens"]["total"] for item in records)
        session_ids = {item["chat_id"] for item in records}
        cost_totals: Dict[str, float] = {}
        by_model_currency: Dict[Tuple[str, str], Dict[str, Any]] = {}

        priced_reply_count = 0
        unpriced_reply_count = 0
        estimated_reply_count = 0
        for item in records:
            total_cost = item["cost"]["total_cost"]
            currency = item["currency"]
            if total_cost is None:
                unpriced_reply_count += 1
            else:
                priced_reply_count += 1
                _merge_costs(cost_totals, currency, total_cost)
                key = (currency, item["model"])
                if key not in by_model_currency:
                    by_model_currency[key] = {"currency": currency, "model": item["model"], "total_cost": 0.0}
                by_model_currency[key]["total_cost"] = round(by_model_currency[key]["total_cost"] + float(total_cost), 8)
            if item["estimated"]["tokens"] or item["estimated"]["pricing"]:
                estimated_reply_count += 1

        top_models_by_currency = sorted(
            by_model_currency.values(),
            key=lambda entry: (entry["currency"], -entry["total_cost"], entry["model"]),
        )
        most_expensive_model = top_models_by_currency[0] if len({item["currency"] for item in top_models_by_currency}) == 1 and top_models_by_currency else None

        return {
            "reply_count": len(records),
            "session_count": len(session_ids),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "priced_reply_count": priced_reply_count,
            "unpriced_reply_count": unpriced_reply_count,
            "estimated_reply_count": estimated_reply_count,
            "currency_groups": _as_currency_groups(cost_totals),
            "most_expensive_model": most_expensive_model,
            "top_models_by_currency": top_models_by_currency,
        }

    def _build_model_breakdown(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for item in records:
            key = (item["provider_id"], item["model"])
            if key not in grouped:
                grouped[key] = {
                    "provider_id": item["provider_id"],
                    "model": item["model"],
                    "reply_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "priced_reply_count": 0,
                    "unpriced_reply_count": 0,
                    "estimated_reply_count": 0,
                    "_costs": defaultdict(float),
                }
            row = grouped[key]
            row["reply_count"] += 1
            row["prompt_tokens"] += item["tokens"]["user"]
            row["completion_tokens"] += item["tokens"]["reply"]
            row["total_tokens"] += item["tokens"]["total"]
            if item["cost"]["total_cost"] is None:
                row["unpriced_reply_count"] += 1
            else:
                row["priced_reply_count"] += 1
                _merge_costs(row["_costs"], item["currency"], item["cost"]["total_cost"])
            if item["estimated"]["tokens"] or item["estimated"]["pricing"]:
                row["estimated_reply_count"] += 1

        rows = []
        for row in grouped.values():
            costs = dict(row.pop("_costs"))
            row["currency_groups"] = _as_currency_groups(costs)
            rows.append(row)
        rows.sort(key=lambda item: (-item["total_tokens"], item["provider_id"], item["model"]))
        return rows

    def _build_session_summaries(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in records:
            chat_id = item["chat_id"]
            if chat_id not in grouped:
                grouped[chat_id] = {
                    "chat_id": chat_id,
                    "display_name": item["display_name"],
                    "reply_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "priced_reply_count": 0,
                    "unpriced_reply_count": 0,
                    "estimated_reply_count": 0,
                    "last_timestamp": 0,
                    "_costs": defaultdict(float),
                }
            row = grouped[chat_id]
            row["display_name"] = item["display_name"] or row["display_name"]
            row["reply_count"] += 1
            row["prompt_tokens"] += item["tokens"]["user"]
            row["completion_tokens"] += item["tokens"]["reply"]
            row["total_tokens"] += item["tokens"]["total"]
            row["last_timestamp"] = max(row["last_timestamp"], item["timestamp"])
            if item["cost"]["total_cost"] is None:
                row["unpriced_reply_count"] += 1
            else:
                row["priced_reply_count"] += 1
                _merge_costs(row["_costs"], item["currency"], item["cost"]["total_cost"])
            if item["estimated"]["tokens"] or item["estimated"]["pricing"]:
                row["estimated_reply_count"] += 1

        sessions = []
        for row in grouped.values():
            costs = dict(row.pop("_costs"))
            row["currency_groups"] = _as_currency_groups(costs)
            sessions.append(row)
        sessions.sort(key=lambda item: (-item["last_timestamp"], item["display_name"]))
        return sessions

    def _build_options(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        providers = sorted(
            {item["provider_id"] for item in records if item["provider_id"]},
        )
        models = sorted({item["model"] for item in records if item["model"] and item["model"] != "未识别模型"})
        return {"providers": providers, "models": models}
