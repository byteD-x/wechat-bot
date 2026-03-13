from backend.model_catalog import get_model_catalog, infer_provider_id, merge_provider_defaults


def test_model_catalog_contains_latest_qwen_models():
    catalog = get_model_catalog()
    qwen = next((provider for provider in catalog["providers"] if provider["id"] == "qwen"), None)
    assert qwen is not None
    assert "qwen3.5-plus" in qwen["models"]
    assert "qwen3-coder-plus" in qwen["models"]


def test_infer_provider_id_from_base_url_and_name():
    assert infer_provider_id(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1") == "qwen"
    assert infer_provider_id(preset_name="Moonshot") == "moonshot"


def test_merge_provider_defaults_populates_missing_provider_fields():
    preset = {"name": "Qwen", "provider_id": "qwen", "model": "qwen3.5-plus"}
    merged = merge_provider_defaults(preset)
    assert merged["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert merged["provider_id"] == "qwen"
