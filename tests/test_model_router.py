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
    assert "rag_augmented" in decision["reasons"]
    assert "long_or_grounded_context" in decision["reasons"]


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
    assert "tight_latency_budget" in decision["reasons"]
    assert "fallback_limited" in decision["reasons"]
