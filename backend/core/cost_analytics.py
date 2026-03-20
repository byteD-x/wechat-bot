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


def _normalize_feedback(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"helpful", "unhelpful"}:
        return text
    return ""


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


def _build_retrieval_summary(retrieval: Dict[str, Any]) -> Dict[str, Any]:
    runtime_hit_count = _safe_int(retrieval.get("runtime_hit_count"), 0)
    export_rag_used = _parse_bool(retrieval.get("export_rag_used"), False)
    augmented = _parse_bool(
        retrieval.get("augmented"),
        default=runtime_hit_count > 0 or export_rag_used,
    )
    summary_parts: List[str] = []
    if augmented:
        summary_parts.append("retrieval enabled")
    if runtime_hit_count > 0:
        summary_parts.append(f"runtime hits {runtime_hit_count}")
    if export_rag_used:
        summary_parts.append("export rag used")
    return {
        "augmented": augmented,
        "runtime_hit_count": runtime_hit_count,
        "export_rag_used": export_rag_used,
        "summary_text": ", ".join(summary_parts),
    }


def _infer_review_reason(item: Dict[str, Any]) -> str:
    retrieval = dict(item.get("retrieval") or {})
    reply_text = str(item.get("reply_text") or "").strip()
    context_summary = dict(item.get("context_summary") or {})

    if not retrieval.get("augmented"):
        return "retrieval_not_used"
    if _safe_int(retrieval.get("runtime_hit_count"), 0) <= 1 and not _parse_bool(retrieval.get("export_rag_used"), False):
        return "retrieval_weak"
    if reply_text and len(reply_text) <= 24:
        return "reply_too_short"
    if not context_summary:
        return "context_thin"
    return "needs_manual_review"


def _infer_suggested_action(review_reason: str) -> str:
    normalized = str(review_reason or "").strip()
    if normalized == "retrieval_not_used":
        return "check_retrieval_toggle"
    if normalized == "retrieval_weak":
        return "tune_retrieval_threshold"
    if normalized == "reply_too_short":
        return "review_prompt_constraints"
    if normalized == "context_thin":
        return "enrich_context_sources"
    return "manual_review_required"


def _build_action_guidance(action: str) -> Dict[str, Any]:
    normalized = str(action or "").strip()
    if normalized == "check_retrieval_toggle":
        return {
            "summary": "先确认当前预设和运行时是否启用了检索增强。",
            "config_paths": ["agent.enabled", "agent.retriever_top_k", "agent.retriever_score_threshold"],
            "status_fields": ["status.reply_quality.retrieval_augmented", "status.system_metrics.reply_retrieval_hit_count"],
            "checks": [
                "确认当前 active preset 使用的是预期模型与检索策略。",
                "检查运行时回复是否持续没有 retrieval hits。",
                "确认没有因为预设切换或配置热重载导致检索增强被关闭。",
            ],
        }
    if normalized == "tune_retrieval_threshold":
        return {
            "summary": "优先调低检索阈值或增加召回数，确认命中不足是否来自召回过严。",
            "config_paths": ["agent.retriever_top_k", "agent.retriever_score_threshold", "agent.retriever_rerank_mode"],
            "status_fields": ["status.system_metrics.reply_retrieval_hit_count", "status.reply_quality.retrieval_hit_count"],
            "checks": [
                "对比低质量回复里的 runtime_hit_count 是否长期偏低。",
                "检查 rerank mode 是否过重或回退到了非预期模式。",
                "先做小幅阈值调整，再观察 review queue 是否下降。",
            ],
        }
    if normalized == "review_prompt_constraints":
        return {
            "summary": "先检查提示词约束是否过强，或回复长度上限是否把答案截短了。",
            "config_paths": ["api.presets", "bot.reply_suffix", "agent.system_prompt", "prompt_overrides.py"],
            "status_fields": ["status.reply_quality.empty_count", "status.reply_quality.helpful_count"],
            "checks": [
                "确认当前 preset 的 system prompt 没有过度要求简短回复。",
                "检查是否存在固定后缀或模板挤占了主要回复空间。",
                "用相同问题复测并对比 helpful / unhelpful 变化。",
            ],
        }
    if normalized == "enrich_context_sources":
        return {
            "summary": "先补会话上下文、记忆来源或导出语料，再观察回复是否仍然空洞。",
            "config_paths": ["agent.retriever_top_k", "bot.memory_window", "data/chat_exports"],
            "status_fields": ["status.reply_quality.retrieval_augmented", "status.system_metrics.reply_retrieval_hit_count"],
            "checks": [
                "确认当前联系人已有足够历史消息或导出语料可供检索。",
                "检查 context_summary 是否长期为空或过薄。",
                "补数据后再验证相同会话的 review reason 是否变化。",
            ],
        }
    return {
        "summary": "先做人工复盘，确认问题更接近检索、提示词还是上下文不足。",
        "config_paths": ["status.reply_quality", "status.system_metrics"],
        "status_fields": ["status.reply_quality", "status.system_metrics"],
        "checks": [
            "优先查看 review queue 里的上下文摘要和检索摘要。",
            "确认问题是否集中在特定 preset、provider 或会话。",
            "整理样本后再决定下一步调优方向。",
        ],
    }


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
        preset: str = "",
        review_reason: str = "",
        suggested_action: str = "",
        only_priced: bool = False,
        include_estimated: bool = True,
    ) -> Dict[str, Any]:
        records, filters = await self._list_records(
            memory,
            config,
            period=period,
            provider_id=provider_id,
            model=model,
            preset=preset,
            review_reason=review_reason,
            suggested_action=suggested_action,
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
            "review_queue": self._build_review_queue(records),
            "review_playbook": self._build_review_playbook(records),
        }

    async def get_sessions(
        self,
        memory,
        config: Dict[str, Any],
        *,
        period: str = "30d",
        provider_id: str = "",
        model: str = "",
        preset: str = "",
        review_reason: str = "",
        suggested_action: str = "",
        only_priced: bool = False,
        include_estimated: bool = True,
    ) -> Dict[str, Any]:
        records, filters = await self._list_records(
            memory,
            config,
            period=period,
            provider_id=provider_id,
            model=model,
            preset=preset,
            review_reason=review_reason,
            suggested_action=suggested_action,
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
        preset: str = "",
        review_reason: str = "",
        suggested_action: str = "",
        only_priced: bool = False,
        include_estimated: bool = True,
    ) -> Dict[str, Any]:
        records, filters = await self._list_records(
            memory,
            config,
            period=period,
            provider_id=provider_id,
            model=model,
            preset=preset,
            review_reason=review_reason,
            suggested_action=suggested_action,
            chat_id=chat_id,
            only_priced=only_priced,
            include_estimated=include_estimated,
        )
        details = sorted(records, key=lambda item: item["timestamp"], reverse=True)
        return {"success": True, "filters": filters, "chat_id": chat_id, "records": details, "total": len(details)}

    async def export_review_queue(
        self,
        memory,
        config: Dict[str, Any],
        *,
        period: str = "30d",
        provider_id: str = "",
        model: str = "",
        preset: str = "",
        review_reason: str = "",
        suggested_action: str = "",
        only_priced: bool = False,
        include_estimated: bool = True,
    ) -> Dict[str, Any]:
        records, filters = await self._list_records(
            memory,
            config,
            period=period,
            provider_id=provider_id,
            model=model,
            preset=preset,
            review_reason=review_reason,
            suggested_action=suggested_action,
            only_priced=only_priced,
            include_estimated=include_estimated,
        )
        items = self._build_review_queue(records, limit=max(1, len(records) or 1), include_full_text=True)
        return {
            "success": True,
            "filters": filters,
            "items": items,
            "total": len(items),
            "exported_at": int(time.time()),
            "playbook": self._build_review_playbook(records, review_queue=items),
        }

    async def _list_records(
        self,
        memory,
        config: Dict[str, Any],
        *,
        period: str,
        provider_id: str = "",
        model: str = "",
        preset: str = "",
        review_reason: str = "",
        suggested_action: str = "",
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
        normalized_preset = str(preset or "").strip().lower()
        normalized_review_reason = str(review_reason or "").strip().lower()
        normalized_suggested_action = str(suggested_action or "").strip().lower()
        filtered: List[Dict[str, Any]] = []
        for item in records:
            if normalized_provider and item["provider_id"] != normalized_provider:
                continue
            if normalized_model and item["model"].lower() != normalized_model:
                continue
            if normalized_preset and item["preset"].lower() != normalized_preset:
                continue
            if normalized_review_reason and item.get("review_reason", "").lower() != normalized_review_reason:
                continue
            if normalized_suggested_action and item.get("suggested_action", "").lower() != normalized_suggested_action:
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
            "preset": preset,
            "review_reason": review_reason,
            "suggested_action": suggested_action,
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
            reply_quality = dict(metadata.get("reply_quality") or {})
            feedback = _normalize_feedback(reply_quality.get("user_feedback"))
            retrieval_summary = _build_retrieval_summary(dict(metadata.get("retrieval") or {}))
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
            review_reason = _infer_review_reason({
                "retrieval": retrieval_summary,
                "reply_text": content,
                "context_summary": metadata.get("context_summary") or {},
            })
            records.append({
                "id": int(message.get("id") or 0),
                "chat_id": chat_id,
                "display_name": str(message.get("display_name") or chat_id),
                "timestamp": int(message.get("created_at") or 0),
                "user_text": user_text,
                "reply_text": content,
                "reply_preview": truncate_text(content.replace("\n", " "), 80),
                "user_preview": truncate_text(user_text.replace("\n", " "), 80),
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
                "reply_quality": {
                    "feedback": feedback,
                    "feedback_updated_at": str(reply_quality.get("feedback_updated_at") or ""),
                },
                "review_reason": review_reason,
                "suggested_action": _infer_suggested_action(review_reason),
                "retrieval": retrieval_summary,
                "context_summary": dict(metadata.get("context_summary") or {}),
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
        helpful_count = 0
        unhelpful_count = 0
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
            feedback = str(item.get("reply_quality", {}).get("feedback") or "")
            if feedback == "helpful":
                helpful_count += 1
            elif feedback == "unhelpful":
                unhelpful_count += 1

        top_models_by_currency = sorted(
            by_model_currency.values(),
            key=lambda entry: (entry["currency"], -entry["total_cost"], entry["model"]),
        )
        most_expensive_model = top_models_by_currency[0] if len({item["currency"] for item in top_models_by_currency}) == 1 and top_models_by_currency else None
        feedback_count = helpful_count + unhelpful_count
        feedback_coverage = round((feedback_count / len(records)) * 100, 1) if records else 0.0

        return {
            "reply_count": len(records),
            "session_count": len(session_ids),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "priced_reply_count": priced_reply_count,
            "unpriced_reply_count": unpriced_reply_count,
            "estimated_reply_count": estimated_reply_count,
            "helpful_count": helpful_count,
            "unhelpful_count": unhelpful_count,
            "feedback_count": feedback_count,
            "feedback_coverage": feedback_coverage,
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
                    "helpful_count": 0,
                    "unhelpful_count": 0,
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
            feedback = str(item.get("reply_quality", {}).get("feedback") or "")
            if feedback == "helpful":
                row["helpful_count"] += 1
            elif feedback == "unhelpful":
                row["unhelpful_count"] += 1

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
                    "helpful_count": 0,
                    "unhelpful_count": 0,
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
            feedback = str(item.get("reply_quality", {}).get("feedback") or "")
            if feedback == "helpful":
                row["helpful_count"] += 1
            elif feedback == "unhelpful":
                row["unhelpful_count"] += 1

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
        presets = sorted({item["preset"] for item in records if item["preset"]})
        review_queue = self._build_review_queue(records, limit=max(1, len(records)))
        review_reasons = sorted(
            {
                item["review_reason"]
                for item in review_queue
                if item.get("review_reason")
            }
        )
        suggested_actions = sorted(
            {
                item["suggested_action"]
                for item in review_queue
                if item.get("suggested_action")
            }
        )
        return {
            "providers": providers,
            "models": models,
            "presets": presets,
            "review_reasons": review_reasons,
            "suggested_actions": suggested_actions,
        }

    def _build_review_queue(
        self,
        records: List[Dict[str, Any]],
        *,
        limit: int = 10,
        include_full_text: bool = False,
    ) -> List[Dict[str, Any]]:
        queue: List[Dict[str, Any]] = []
        for item in records:
            if str(item.get("reply_quality", {}).get("feedback") or "") != "unhelpful":
                continue
            action = item.get("suggested_action") or _infer_suggested_action(item.get("review_reason") or _infer_review_reason(item))
            entry = {
                "id": item["id"],
                "chat_id": item["chat_id"],
                "display_name": item["display_name"],
                "timestamp": item["timestamp"],
                "model": item["model"],
                "provider_id": item["provider_id"],
                "preset": item["preset"],
                "reply_preview": item["reply_preview"],
                "user_preview": item["user_preview"],
                "feedback_updated_at": str(item.get("reply_quality", {}).get("feedback_updated_at") or ""),
                "retrieval": dict(item.get("retrieval") or {}),
                "context_summary": dict(item.get("context_summary") or {}),
                "review_reason": item.get("review_reason") or _infer_review_reason(item),
                "suggested_action": action,
                "action_guidance": _build_action_guidance(action),
                "cost": dict(item.get("cost") or {}),
                "currency": item["currency"],
            }
            if include_full_text:
                entry["user_text"] = item.get("user_text") or ""
                entry["reply_text"] = item.get("reply_text") or ""
            queue.append(entry)
        queue.sort(key=lambda entry: (-int(entry.get("timestamp") or 0), -int(entry.get("id") or 0)))
        return queue[: max(1, int(limit))]

    def _build_review_playbook(
        self,
        records: List[Dict[str, Any]],
        *,
        review_queue: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        queue = list(review_queue or self._build_review_queue(records, limit=max(1, len(records) or 1)))
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in queue:
            action = str(item.get("suggested_action") or "").strip()
            if not action:
                continue
            row = grouped.setdefault(
                action,
                {
                    "action": action,
                    "count": 0,
                    "review_reasons": set(),
                    "presets": set(),
                    "providers": set(),
                },
            )
            row["count"] += 1
            reason = str(item.get("review_reason") or "").strip()
            preset = str(item.get("preset") or "").strip()
            provider = str(item.get("provider_id") or "").strip()
            if reason:
                row["review_reasons"].add(reason)
            if preset:
                row["presets"].add(preset)
            if provider:
                row["providers"].add(provider)

        actions = []
        for row in grouped.values():
            actions.append(
                {
                    "action": row["action"],
                    "count": row["count"],
                    "review_reasons": sorted(row["review_reasons"]),
                    "presets": sorted(row["presets"]),
                    "providers": sorted(row["providers"]),
                    "guidance": _build_action_guidance(row["action"]),
                }
            )
        actions.sort(key=lambda item: (-int(item["count"]), item["action"]))
        return {
            "total_items": len(queue),
            "action_count": len(actions),
            "top_action": actions[0]["action"] if actions else "",
            "actions": actions,
        }
