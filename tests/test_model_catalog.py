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
    assert "gpt-5.4-pro" in openai["models"]
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

    assert providers["qwen"]["default_model"] == "qwen3.5-plus"
    assert "MiniMax-M2.5" in providers["qwen"]["models"]
    assert "glm-5" in providers["qwen"]["models"]
    assert "kimi-k2.5" in providers["qwen"]["models"]
    assert providers["anthropic"]["default_model"] == "claude-sonnet-4-0"
    assert "claude-sonnet-4-6" in providers["anthropic"]["models"]
    assert providers["google"]["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert "gemini-3.1-pro-preview" in providers["google"]["models"]
    assert providers["doubao"]["default_model"] == "doubao-seed-1.8"
    assert "doubao-seed-2.0-pro" in providers["doubao"]["models"]
    assert providers["zhipu"]["default_model"] == "glm-5"
    assert "glm-4.7" in providers["zhipu"]["models"]
    assert "kimi-for-coding" in providers["kimi"]["models"]
    assert "kimi-k2-0905-preview" in providers["kimi"]["models"]
    assert providers["minimax"]["default_model"] == "MiniMax-M2.5"
    assert "MiniMax-M2.7" in providers["minimax"]["models"]
    assert "MiniMax-M2.5-highspeed" in providers["minimax"]["models"]
    assert providers["groq"]["default_model"] == "moonshotai/kimi-k2-instruct-0905"
    assert providers["perplexity"]["models"] == ["sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]
    assert providers["openrouter"]["default_model"] == "openrouter/auto"
    assert "google/gemini-3.1-pro-preview" in providers["openrouter"]["models"]
    assert "openai/gpt-5.4-pro" in providers["openrouter"]["models"]
    assert providers["together"]["default_model"] == "moonshotai/Kimi-K2.5"
    assert "openai/gpt-oss-120b" in providers["siliconflow"]["models"]
    assert providers["fireworks"]["default_model"] == "accounts/fireworks/models/deepseek-v3p1"
    assert "accounts/fireworks/models/qwen3-coder-480b-a35b-instruct" in providers["fireworks"]["models"]


def test_model_catalog_merges_existing_qwen_provider_with_latest_coding_plan_models(monkeypatch):
    monkeypatch.setattr(
        "backend.model_catalog.load_model_catalog",
        lambda: {
            "providers": [
                {
                    "id": "bailian",
                    "label": "Bailian",
                    "base_url": "https://coding.dashscope.aliyuncs.com/v1",
                    "models": ["qwen3-coder-next"],
                }
            ]
        },
    )

    catalog = get_model_catalog()
    qwen = next((provider for provider in catalog["providers"] if provider["id"] == "qwen"), None)

    assert qwen is not None
    assert "qwen3-coder-next" in qwen["models"]
    assert "MiniMax-M2.5" in qwen["models"]
    assert "glm-5" in qwen["models"]
    assert "kimi-k2.5" in qwen["models"]

    auth_methods = {item["id"]: item["type"] for item in qwen["auth_methods"]}
    assert auth_methods["qwen_oauth"] == "oauth"
    assert auth_methods["coding_plan_api_key"] == "api_key"


def test_model_catalog_preserves_chinese_provider_labels_and_aliases():
    catalog = get_model_catalog()
    providers = {provider["id"]: provider for provider in catalog["providers"]}

    assert providers["doubao"]["label"] == "Doubao (豆包)"
    assert "豆包" in providers["doubao"]["aliases"]
    assert providers["qwen"]["label"] == "Qwen (通义千问)"
    assert "通义" in providers["qwen"]["aliases"]
    assert "千问" in providers["qwen"]["aliases"]
    assert "百炼" in providers["qwen"]["aliases"]
    assert providers["zhipu"]["label"] == "Zhipu (智谱)"
    assert "智谱" in providers["zhipu"]["aliases"]
    assert "硅基" in providers["siliconflow"]["aliases"]


def test_static_provider_registry_contains_latest_provider_models():
    openai = get_provider_definition("openai")
    google = get_provider_definition("google")
    anthropic = get_provider_definition("anthropic")
    qwen = get_provider_definition("qwen")
    kimi = get_provider_definition("kimi")
    zhipu = get_provider_definition("zhipu")
    minimax = get_provider_definition("minimax")
    doubao = get_provider_definition("doubao")

    assert openai is not None
    assert "gpt-5.4-pro" in openai.supported_models

    assert google is not None
    assert "gemini-3.1-pro-preview" in google.supported_models
    assert "gemini-3-flash-preview" in google.supported_models

    assert anthropic is not None
    assert anthropic.default_model == "claude-sonnet-4-0"
    assert "claude-sonnet-4-6" in anthropic.supported_models
    assert "claude-haiku-4-5" in anthropic.supported_models

    assert qwen is not None
    assert "glm-5" in qwen.supported_models
    assert "MiniMax-M2.5" in qwen.supported_models
    assert "kimi-k2.5" in qwen.supported_models
    qwen_methods = {item.id: item for item in qwen.auth_methods}
    assert qwen_methods["qwen_oauth"].metadata["recommended_base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert qwen_methods["qwen_oauth"].metadata["recommended_model"] == "qwen3-coder-plus"
    assert qwen_methods["qwen_local"].metadata["recommended_model"] == "qwen3-coder-plus"

    assert kimi is not None
    assert "kimi-for-coding" in kimi.supported_models
    assert "kimi-k2-0905-preview" in kimi.supported_models

    assert zhipu is not None
    assert zhipu.default_model == "glm-5"
    assert "glm-4.7" in zhipu.supported_models

    assert minimax is not None
    assert minimax.default_model == "MiniMax-M2.5"
    assert "MiniMax-M2.7" in minimax.supported_models
    assert "MiniMax-M2.1" in minimax.supported_models

    assert doubao is not None
    assert doubao.default_model == "doubao-seed-1.8"
    assert "doubao-seed-code" in doubao.supported_models


def test_infer_provider_id_from_base_url_and_name():
    assert infer_provider_id(provider_id="bailian") == "qwen"
    assert infer_provider_id(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1") == "qwen"
    assert infer_provider_id(base_url="https://coding.dashscope.aliyuncs.com/v1", model="MiniMax-M2.5") == "qwen"
    assert infer_provider_id(base_url="https://coding.dashscope.aliyuncs.com/v1", model="glm-5") == "qwen"
    assert infer_provider_id(base_url="https://aiplatform.googleapis.com/v1beta1/projects/demo/locations/us-central1/publishers/google/models/gemini-2.5-flash") == "google"
    assert infer_provider_id(base_url="https://global-aiplatform.googleapis.com/v1/projects/demo/locations/global/publishers/anthropic/models", model="claude-sonnet-4-6") == "anthropic"
    assert infer_provider_id(base_url="https://open.bigmodel.cn/api/coding/paas/v4") == "zhipu"
    assert infer_provider_id(preset_name="Moonshot") == "kimi"
    assert infer_provider_id(base_url="https://api.anthropic.com/v1") == "anthropic"
    assert infer_provider_id(base_url="https://api.minimax.io/v1") == "minimax"
    assert infer_provider_id(base_url="https://api.minimaxi.com/v1") == "minimax"
    assert infer_provider_id(base_url="https://api.minimax.io/anthropic/v1", model="MiniMax-M2.5") == "minimax"
    assert infer_provider_id(base_url="https://api.minimaxi.com/anthropic/messages", model="MiniMax-M2.5") == "minimax"


def test_merge_provider_defaults_populates_missing_provider_fields():
    preset = {"name": "Qwen", "provider_id": "qwen", "model": "qwen3.5-plus"}
    merged = merge_provider_defaults(preset)
    assert merged["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert merged["provider_id"] == "qwen"


def test_merge_provider_defaults_canonicalizes_bailian_coding_plan_provider_id():
    preset = {
        "name": "Bailian Coding Plan",
        "provider_id": "bailian",
        "base_url": "https://coding.dashscope.aliyuncs.com/v1",
        "model": "MiniMax-M2.5",
    }
    merged = merge_provider_defaults(preset)

    assert merged["provider_id"] == "qwen"
    assert merged["base_url"] == "https://coding.dashscope.aliyuncs.com/v1"
    assert merged["model"] == "MiniMax-M2.5"


def test_merge_provider_defaults_uses_latest_google_defaults():
    preset = {"name": "Gemini", "provider_id": "google"}
    merged = merge_provider_defaults(preset)
    auth_methods = {item["id"]: item for item in merged["auth_methods"]}

    assert merged["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert merged["model"] == "gemini-2.5-flash"
    assert auth_methods["api_key"]["type"] == "api_key"
    assert auth_methods["google_oauth"]["type"] == "oauth"
    assert auth_methods["google_oauth"]["requires_fields"] == ["oauth_project_id"]
    assert auth_methods["gemini_cli_local"]["type"] == "local_import"
    assert auth_methods["gemini_cli_local"]["requires_fields"] == ["oauth_project_id"]


def test_merge_provider_defaults_canonicalizes_kimi_and_exposes_oauth_methods():
    preset = {"name": "Moonshot", "provider_id": "moonshot"}
    merged = merge_provider_defaults(preset)
    auth_methods = {item["id"]: item["type"] for item in merged["auth_methods"]}

    assert merged["provider_id"] == "kimi"
    assert merged["base_url"] == "https://api.moonshot.cn/v1"
    assert auth_methods["api_key"] == "api_key"
    assert auth_methods["coding_plan_api_key"] == "api_key"
    assert auth_methods["kimi_code_oauth"] == "oauth"
    assert auth_methods["kimi_code_local"] == "local_import"


def test_merge_provider_defaults_exposes_claude_local_auth():
    preset = {"name": "Claude", "provider_id": "anthropic"}
    merged = merge_provider_defaults(preset)
    auth_methods = {item["id"]: item["type"] for item in merged["auth_methods"]}

    assert merged["base_url"] == "https://api.anthropic.com/v1"
    assert auth_methods["api_key"] == "api_key"
    assert auth_methods["claude_code_oauth"] == "oauth"
    assert auth_methods["claude_code_local"] == "local_import"
    assert auth_methods["claude_vertex_local"] == "local_import"


def test_merge_provider_defaults_exposes_minimax_coding_plan():
    preset = {"name": "MiniMax", "provider_id": "minimax"}
    merged = merge_provider_defaults(preset)
    auth_methods = {item["id"]: item["type"] for item in merged["auth_methods"]}

    assert merged["base_url"] == "https://api.minimax.io/v1"
    assert auth_methods["api_key"] == "api_key"
    assert auth_methods["coding_plan_api_key"] == "api_key"


def test_merge_provider_defaults_exposes_zhipu_coding_plan():
    preset = {"name": "GLM Coding", "provider_id": "zhipu"}
    merged = merge_provider_defaults(preset)
    auth_methods = {item["id"]: item["type"] for item in merged["auth_methods"]}

    assert merged["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert auth_methods["api_key"] == "api_key"
    assert auth_methods["coding_plan_api_key"] == "api_key"


def test_model_catalog_exposes_method_runtime_metadata_for_coding_plan_and_oauth():
    catalog = get_model_catalog()
    providers = {provider["id"]: provider for provider in catalog["providers"]}

    qwen_methods = {item["id"]: item for item in providers["qwen"]["auth_methods"]}
    kimi_methods = {item["id"]: item for item in providers["kimi"]["auth_methods"]}
    zhipu_methods = {item["id"]: item for item in providers["zhipu"]["auth_methods"]}
    minimax_methods = {item["id"]: item for item in providers["minimax"]["auth_methods"]}

    assert qwen_methods["coding_plan_api_key"]["metadata"]["recommended_base_url"] == "https://coding.dashscope.aliyuncs.com/v1"
    assert qwen_methods["coding_plan_api_key"]["metadata"]["recommended_model"] == "qwen3-coder-next"
    assert qwen_methods["qwen_oauth"]["metadata"]["recommended_base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert qwen_methods["qwen_oauth"]["metadata"]["recommended_model"] == "qwen3-coder-plus"
    assert kimi_methods["kimi_code_oauth"]["metadata"]["recommended_base_url"] == "https://api.kimi.com/coding/v1"
    assert kimi_methods["kimi_code_oauth"]["metadata"]["recommended_model"] == "kimi-for-coding"
    assert zhipu_methods["coding_plan_api_key"]["metadata"]["recommended_base_url"] == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert "https://api.minimax.io/anthropic" in minimax_methods["coding_plan_api_key"]["metadata"]["regional_base_urls"]
