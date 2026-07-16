from backend.core.model_router import ModelRouter


def test_model_router_marks_short_request_as_cost_sensitive():
    decision = ModelRouter().route(
        provider_id="OpenAI",
        model="gpt-4o-mini",
        user_text="hello",
        rag_augmented=False,
        timeout_sec=10,
        deadline_sec=0,
    ).to_dict()

    assert decision["selected_provider"] == "openai"
    assert decision["selected_model"] == "gpt-4o-mini"
    assert decision["task_complexity"] == "simple"
    assert decision["estimated_input_chars"] == 5
    assert decision["cost_priority"] is True
    assert decision["latency_priority"] is False
    assert decision["fallback_allowed"] is True
    assert decision["governance_action"] == "cost_optimized_current_runtime"
    assert decision["degradation_recommended"] is False
    assert "cost_sensitive" in decision["reasons"]


def test_model_router_marks_long_rag_request_as_complex():
    decision = ModelRouter().route(
        provider_id="qwen",
        model="qwen-plus",
        user_text="x" * 1200,
        rag_augmented=True,
        timeout_sec=12,
        deadline_sec=0,
    ).to_dict()

    assert decision["task_complexity"] == "complex"
    assert decision["rag_augmented"] is True
    assert decision["cost_priority"] is False
    assert decision["degradation_recommended"] is True
    assert decision["governance_action"] == "fallback_recommended"
    assert "rag_augmented" in decision["reasons"]
    assert "long_or_grounded_context" in decision["reasons"]
    assert "degradation_recommended" in decision["reasons"]


def test_model_router_limits_fallback_under_tight_latency_budget():
    decision = ModelRouter({"tight_deadline_sec": 2.5}).route(
        provider_id="ollama",
        model="llama3",
        user_text="quick reply",
        rag_augmented=False,
        timeout_sec=20,
        deadline_sec=2.0,
    ).to_dict()

    assert decision["latency_priority"] is True
    assert decision["fallback_allowed"] is False
    assert decision["throttle_recommended"] is False
    assert decision["governance_action"] == "cost_optimized_current_runtime"
    assert "tight_latency_budget" in decision["reasons"]
    assert "fallback_limited" in decision["reasons"]


def test_model_router_recommends_queueing_standard_request_under_tight_latency():
    decision = ModelRouter({"tight_deadline_sec": 2.5}).route(
        provider_id="qwen",
        model="qwen-plus",
        user_text="请结合知识库说明模型认证中心和成本统计的排障链路。" * 8,
        rag_augmented=True,
        timeout_sec=20,
        deadline_sec=2.0,
    ).to_dict()

    assert decision["task_complexity"] == "standard"
    assert decision["latency_priority"] is True
    assert decision["fallback_allowed"] is False
    assert decision["throttle_recommended"] is True
    assert decision["governance_action"] == "queue_or_shorten_request"
    assert "throttle_or_shorten_recommended" in decision["reasons"]


def test_model_router_recommends_manual_review_for_oversized_input():
    decision = ModelRouter({"max_input_chars": 32}).route(
        provider_id="openai",
        model="gpt-4o",
        user_text="x" * 64,
        rag_augmented=False,
        timeout_sec=30,
        deadline_sec=0,
    ).to_dict()

    assert decision["manual_review_recommended"] is True
    assert decision["fallback_allowed"] is False
    assert decision["governance_action"] == "manual_review_before_call"
    assert "input_limit_exceeded" in decision["reasons"]
    assert "manual_review_recommended" in decision["reasons"]
