from backend.model_catalog import get_model_catalog, infer_provider_id, merge_provider_defaults
from backend.model_auth.providers.registry import get_provider_definition


def test_model_catalog_contains_latest_qwen_models():
    catalog = get_model_catalog()
    qwen = next((provider for provider in catalog["providers"] if provider["id"] == "qwen"), None)
    assert qwen is not None
    assert "qwen3.5-plus" in qwen["models"]
    assert "qwen3-coder-next" in qwen["models"]
    assert "qwen3-coder-plus" in qwen["models"]


def test_model_catalog_contains_latest_openai_models_and_ids():
    catalog = get_model_catalog()
    openai = next((provider for provider in catalog["providers"] if provider["id"] == "openai"), None)

    assert openai is not None
    assert openai["default_model"] == "gpt-5.4-mini"
    assert "gpt-5.4" in openai["models"]
    assert "gpt-5.4-mini" in openai["models"]
    assert "gpt-5.4-nano" in openai["models"]
    assert "gpt-5.3-codex" in openai["models"]

    auth_methods = {item["id"]: item["type"] for item in openai["auth_methods"]}
    assert auth_methods["api_key"] == "api_key"
    assert auth_methods["codex_local"] == "local_import"


def test_model_catalog_contains_latest_multi_provider_models():
    catalog = get_model_catalog()
    providers = {provider["id"]: provider for provider in catalog["providers"]}

    assert providers["google"]["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert "gemini-2.5-flash-lite" in providers["google"]["models"]
    assert providers["doubao"]["default_model"] == "doubao-seed-1.8"
    assert "doubao-seed-2.0-pro" in providers["doubao"]["models"]
    assert providers["zhipu"]["default_model"] == "glm-5"
    assert "glm-4.7" in providers["zhipu"]["models"]
    assert "kimi-k2-0905-preview" in providers["moonshot"]["models"]
    assert providers["groq"]["default_model"] == "moonshotai/kimi-k2-instruct-0905"
    assert providers["perplexity"]["models"] == ["sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]
    assert providers["openrouter"]["default_model"] == "openrouter/auto"
    assert "google/gemini-3.1-pro-preview" in providers["openrouter"]["models"]
    assert providers["fireworks"]["default_model"] == "accounts/fireworks/models/deepseek-v3p1"
    assert "accounts/fireworks/models/qwen3-coder-480b-a35b-instruct" in providers["fireworks"]["models"]


def test_static_provider_registry_contains_latest_provider_models():
    google = get_provider_definition("google")
    anthropic = get_provider_definition("anthropic")
    kimi = get_provider_definition("kimi")
    zhipu = get_provider_definition("zhipu")
    minimax = get_provider_definition("minimax")
    doubao = get_provider_definition("doubao")

    assert google is not None
    assert "gemini-2.5-flash-lite" in google.supported_models

    assert anthropic is not None
    assert anthropic.default_model == "claude-sonnet-4-0"
    assert "claude-opus-4-1" in anthropic.supported_models
    assert "claude-sonnet-4-5" not in anthropic.supported_models

    assert kimi is not None
    assert "kimi-k2-0905-preview" in kimi.supported_models

    assert zhipu is not None
    assert zhipu.default_model == "glm-5"
    assert "glm-4.7" in zhipu.supported_models

    assert minimax is not None
    assert minimax.default_model == "MiniMax-M2.5"
    assert "MiniMax-M2.1" in minimax.supported_models

    assert doubao is not None
    assert doubao.default_model == "doubao-seed-1.8"
    assert "doubao-seed-code" in doubao.supported_models


def test_infer_provider_id_from_base_url_and_name():
    assert infer_provider_id(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1") == "qwen"
    assert infer_provider_id(base_url="https://aiplatform.googleapis.com/v1beta1/projects/demo/locations/us-central1/publishers/google/models/gemini-2.5-flash") == "google"
    assert infer_provider_id(preset_name="Moonshot") == "moonshot"


def test_merge_provider_defaults_populates_missing_provider_fields():
    preset = {"name": "Qwen", "provider_id": "qwen", "model": "qwen3.5-plus"}
    merged = merge_provider_defaults(preset)
    assert merged["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert merged["provider_id"] == "qwen"


def test_merge_provider_defaults_uses_latest_google_defaults():
    preset = {"name": "Gemini", "provider_id": "google"}
    merged = merge_provider_defaults(preset)
    auth_methods = {item["id"]: item["type"] for item in merged["auth_methods"]}

    assert merged["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert merged["model"] == "gemini-2.5-flash"
    assert auth_methods["api_key"] == "api_key"
    assert auth_methods["google_oauth"] == "oauth"
    assert auth_methods["gemini_cli_local"] == "local_import"
