import pytest

from backend.core.cost_analytics import CostAnalyticsService


class DummyPricingCatalog:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def get_snapshot(self):
        return {"providers": self.mapping}

    def refresh(self, providers=None):
        return {"success": True, "results": {}, "providers": list(providers or [])}

    def resolve_price(self, provider_id, model, *, prompt_tokens=None):
        provider_key = str(provider_id or "").strip().lower()
        model_key = str(model or "").strip()
        provider_entry = self.mapping.get(provider_key, {})
        model_entry = provider_entry.get(model_key)
        if model_entry is None:
            return None
        payload = dict(model_entry)
        payload.setdefault("provider_id", provider_key)
        payload.setdefault("provider_label", provider_key)
        payload.setdefault("model", model_key)
        payload.setdefault("source_url", "")
        payload.setdefault("price_verified_at", "2026-03-17")
        payload.setdefault("pricing_mode", "flat")
        return payload


class DummyMemory:
    def __init__(self, messages):
        self.messages = messages

    async def list_messages_for_analysis(self, **kwargs):
        chat_id = str(kwargs.get("chat_id") or "").strip()
        filtered = []
        for message in self.messages:
            if chat_id and str(message.get("wx_id") or "") != chat_id:
                continue
            filtered.append(message)
        return filtered


def _assistant_message(metadata=None, *, content="助手回复", created_at=1710000001, wx_id="friend:alice"):
    return {
        "id": 2,
        "wx_id": wx_id,
        "role": "assistant",
        "content": content,
        "created_at": created_at,
        "display_name": "Alice",
        "metadata": metadata or {},
    }


def _user_message(content="你好", *, created_at=1710000000, wx_id="friend:alice"):
    return {
        "id": 1,
        "wx_id": wx_id,
        "role": "user",
        "content": content,
        "created_at": created_at,
        "display_name": "Alice",
        "metadata": {},
    }


def test_enrich_records_prefers_metadata_pricing_snapshot():
    catalog = DummyPricingCatalog({
        "openai": {
            "gpt-5-mini": {
                "currency": "USD",
                "input_price_per_1m": 99.0,
                "output_price_per_1m": 199.0,
            }
        }
    })
    service = CostAnalyticsService(catalog)

    messages = [
        _user_message("你好，今天怎么样"),
        _assistant_message({
            "provider_id": "openai",
            "model": "gpt-5-mini",
            "tokens": {"user": 120, "reply": 80, "total": 200},
            "pricing": {
                "currency": "USD",
                "input_price_per_1m": 1.0,
                "output_price_per_1m": 2.0,
                "source_url": "https://example.com/openai",
                "price_verified_at": "2026-03-17",
            },
        }),
    ]

    records = service._enrich_records(messages, {})

    assert len(records) == 1
    record = records[0]
    assert record["pricing"]["input_price_per_1m"] == 1.0
    assert record["pricing"]["output_price_per_1m"] == 2.0
    assert record["estimated"]["pricing"] is False
    assert record["pricing_available"] is True
    assert record["cost"]["total_cost"] == pytest.approx(0.00028)


def test_enrich_records_falls_back_to_model_alias_before_unknown():
    service = CostAnalyticsService(DummyPricingCatalog())

    messages = [
        _user_message("你好"),
        _assistant_message({
            "provider_id": "openai",
            "preset": "prod-openai",
            "model_alias": "gpt-4o-mini",
            "tokens": {"user": 12, "reply": 8, "total": 20},
        }),
    ]

    records = service._enrich_records(messages, {})

    assert len(records) == 1
    assert records[0]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_summary_estimates_tokens_and_falls_back_to_token_only_when_unpriced():
    service = CostAnalyticsService(DummyPricingCatalog())
    memory = DummyMemory([
        _user_message("帮我写一个简短回复"),
        _assistant_message({
            "provider_id": "unknown-provider",
            "model": "unknown-model",
        }, content="当然可以，这是一条较长的回复内容。"),
    ])

    payload = await service.get_summary(memory, {"api": {"presets": []}}, include_estimated=True)

    overview = payload["overview"]
    assert overview["reply_count"] == 1
    assert overview["total_tokens"] > 0
    assert overview["estimated_reply_count"] == 1
    assert overview["unpriced_reply_count"] == 1
    assert overview["priced_reply_count"] == 0
    assert overview["currency_groups"] == []


@pytest.mark.asyncio
async def test_summary_splits_mixed_currency_totals():
    catalog = DummyPricingCatalog({
        "openai": {
            "gpt-5-mini": {
                "currency": "USD",
                "input_price_per_1m": 1.0,
                "output_price_per_1m": 2.0,
            }
        },
        "qwen": {
            "qwen3.5-plus": {
                "currency": "CNY",
                "input_price_per_1m": 3.0,
                "output_price_per_1m": 6.0,
            }
        },
    })
    service = CostAnalyticsService(catalog)
    memory = DummyMemory([
        _user_message("hello", wx_id="friend:alice"),
        _assistant_message({
            "provider_id": "openai",
            "model": "gpt-5-mini",
            "tokens": {"user": 1000, "reply": 500, "total": 1500},
        }, wx_id="friend:alice"),
        _user_message("你好", wx_id="friend:bob", created_at=1710000100),
        _assistant_message({
            "provider_id": "qwen",
            "model": "qwen3.5-plus",
            "tokens": {"user": 1000, "reply": 1000, "total": 2000},
        }, wx_id="friend:bob", created_at=1710000101),
    ])

    payload = await service.get_summary(memory, {"api": {"presets": []}}, include_estimated=True)

    groups = payload["overview"]["currency_groups"]
    assert len(groups) == 2
    assert {item["currency"] for item in groups} == {"USD", "CNY"}


@pytest.mark.asyncio
async def test_session_details_respects_only_priced_filter():
    catalog = DummyPricingCatalog({
        "openai": {
            "gpt-5-mini": {
                "currency": "USD",
                "input_price_per_1m": 1.0,
                "output_price_per_1m": 2.0,
            }
        }
    })
    service = CostAnalyticsService(catalog)
    memory = DummyMemory([
        _user_message("hello"),
        _assistant_message({
            "provider_id": "openai",
            "model": "gpt-5-mini",
            "tokens": {"user": 100, "reply": 100, "total": 200},
        }, content="已定价回复"),
        {
            "id": 3,
            "wx_id": "friend:alice",
            "role": "assistant",
            "content": "未定价回复",
            "created_at": 1710000002,
            "display_name": "Alice",
            "metadata": {
                "provider_id": "unknown",
                "model": "unknown",
            },
        },
    ])

    payload = await service.get_session_details(
        memory,
        {"api": {"presets": []}},
        chat_id="friend:alice",
        only_priced=True,
        include_estimated=True,
    )

    assert payload["total"] == 1
    assert payload["records"][0]["pricing_available"] is True


@pytest.mark.asyncio
async def test_summary_keeps_zero_cost_currency_groups_for_priced_local_models():
    catalog = DummyPricingCatalog({
        "ollama": {
            "deepseek-v3.2:cloud": {
                "currency": "LOCAL",
                "input_price_per_1m": 0.0,
                "output_price_per_1m": 0.0,
            }
        }
    })
    service = CostAnalyticsService(catalog)
    memory = DummyMemory([
        _user_message("hello"),
        _assistant_message({
            "provider_id": "ollama",
            "model": "deepseek-v3.2:cloud",
            "tokens": {"user": 100, "reply": 200, "total": 300},
        }),
    ])

    payload = await service.get_summary(memory, {"api": {"presets": []}}, include_estimated=True)

    overview = payload["overview"]
    assert overview["priced_reply_count"] == 1
    assert overview["unpriced_reply_count"] == 0
    assert overview["currency_groups"] == [{"currency": "LOCAL", "total_cost": 0.0}]
    assert payload["models"][0]["currency_groups"] == [{"currency": "LOCAL", "total_cost": 0.0}]


@pytest.mark.asyncio
async def test_summary_includes_feedback_distribution_and_review_queue():
    service = CostAnalyticsService(DummyPricingCatalog())
    memory = DummyMemory([
        _user_message("这个答复哪里有问题？", wx_id="friend:alice"),
        _assistant_message({
            "provider_id": "openai",
            "preset": "default",
            "model": "gpt-5-mini",
            "tokens": {"user": 100, "reply": 120, "total": 220},
            "reply_quality": {
                "user_feedback": "unhelpful",
                "feedback_updated_at": "2026-03-20T10:00:00+08:00",
            },
            "retrieval": {
                "augmented": True,
                "runtime_hit_count": 2,
                "export_rag_used": True,
            },
        }, content="这是一条需要复盘的回复", created_at=1710000003, wx_id="friend:alice"),
        _user_message("这个回答不错", created_at=1710000100, wx_id="friend:bob"),
        _assistant_message({
            "provider_id": "openai",
            "preset": "fallback",
            "model": "gpt-5-mini",
            "tokens": {"user": 80, "reply": 90, "total": 170},
            "reply_quality": {
                "user_feedback": "helpful",
            },
        }, content="这是一条有帮助的回复", created_at=1710000101, wx_id="friend:bob"),
    ])

    payload = await service.get_summary(memory, {"api": {"presets": []}}, include_estimated=True)

    overview = payload["overview"]
    assert overview["helpful_count"] == 1
    assert overview["unhelpful_count"] == 1
    assert overview["feedback_count"] == 2
    assert overview["feedback_coverage"] == 100.0

    sessions = await service.get_sessions(memory, {"api": {"presets": []}}, include_estimated=True)
    session_map = {item["chat_id"]: item for item in sessions["sessions"]}
    assert session_map["friend:alice"]["unhelpful_count"] == 1
    assert session_map["friend:bob"]["helpful_count"] == 1

    details = await service.get_session_details(
        memory,
        {"api": {"presets": []}},
        chat_id="friend:alice",
        include_estimated=True,
    )
    assert details["records"][0]["reply_quality"]["feedback"] == "unhelpful"
    assert details["records"][0]["retrieval"]["runtime_hit_count"] == 2
    assert details["records"][0]["user_preview"] == "这个答复哪里有问题？"

    review_queue = payload["review_queue"]
    assert len(review_queue) == 1
    assert review_queue[0]["chat_id"] == "friend:alice"
    assert payload["options"]["presets"] == ["default", "fallback"]
    assert payload["options"]["review_reasons"] == ["reply_too_short"]
    assert payload["options"]["suggested_actions"] == ["review_prompt_constraints"]
    assert payload["review_playbook"]["total_items"] == 1
    assert payload["review_playbook"]["top_action"] == "review_prompt_constraints"
    assert payload["review_playbook"]["actions"][0]["count"] == 1
    assert "summary" in payload["review_playbook"]["actions"][0]["guidance"]
    assert review_queue[0]["retrieval"]["export_rag_used"] is True
    assert review_queue[0]["review_reason"] == "reply_too_short"
    assert review_queue[0]["suggested_action"] == "review_prompt_constraints"
    assert "config_paths" in review_queue[0]["action_guidance"]
    assert review_queue[0]["user_preview"] == "这个答复哪里有问题？"

    filtered = await service.get_summary(
        memory,
        {"api": {"presets": []}},
        preset="default",
        review_reason="reply_too_short",
        suggested_action="review_prompt_constraints",
        include_estimated=True,
    )
    assert filtered["overview"]["reply_count"] == 1
    assert filtered["review_queue"][0]["preset"] == "default"

    export_payload = await service.export_review_queue(
        memory,
        {"api": {"presets": []}},
        preset="default",
        review_reason="reply_too_short",
        suggested_action="review_prompt_constraints",
        include_estimated=True,
    )
    assert export_payload["total"] == 1
    assert export_payload["items"][0]["user_text"] == "这个答复哪里有问题？"
    assert export_payload["items"][0]["reply_text"] == "这是一条需要复盘的回复"
    assert export_payload["items"][0]["review_reason"] == "reply_too_short"
    assert export_payload["items"][0]["suggested_action"] == "review_prompt_constraints"
    assert export_payload["items"][0]["action_guidance"]["summary"]
    assert export_payload["items"][0]["context_summary"] == {}
    assert export_payload["playbook"]["top_action"] == "review_prompt_constraints"
    assert export_payload["playbook"]["actions"][0]["review_reasons"] == ["reply_too_short"]
    assert export_payload["playbook"]["actions"][0]["guidance"]["checks"]
