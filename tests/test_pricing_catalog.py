from backend.core.pricing_catalog import PricingCatalog


def test_refresh_returns_provider_failure_without_raising(tmp_path, monkeypatch):
    catalog = PricingCatalog(data_path=str(tmp_path / "pricing_catalog.json"))

    def _boom():
        raise RuntimeError("mock refresh failure")

    monkeypatch.setattr(catalog, "_refresh_openai_locked", _boom)

    payload = catalog.refresh(providers=["openai"])

    assert payload["success"] is True
    assert payload["results"]["openai"]["success"] is False
    assert payload["results"]["openai"]["message"] == "mock refresh failure"


def test_repo_snapshot_resolves_seeded_prices_for_supported_models():
    catalog = PricingCatalog()

    cases = [
        ("qwen", "qwen3.5-flash"),
        ("qwen", "qwen-flash-latest"),
        ("perplexity", "sonar-pro"),
        ("together", "deepseek-ai/DeepSeek-V3.1"),
        ("fireworks", "accounts/fireworks/models/deepseek-v3p1"),
        ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"),
    ]

    for provider_id, model in cases:
        pricing = catalog.resolve_price(provider_id, model, prompt_tokens=1024)
        assert pricing is not None, f"missing price for {provider_id}/{model}"
        assert pricing["input_price_per_1m"] >= 0
        assert pricing["output_price_per_1m"] >= 0
