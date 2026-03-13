import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from backend.config import CONFIG, _apply_config_overrides


def test_apply_config_overrides_merges_new_default_presets(tmp_path):
    override_dir = tmp_path / "data"
    override_dir.mkdir(parents=True, exist_ok=True)
    override_file = override_dir / "config_override.json"
    override_file.write_text(
        json.dumps(
            {
                "api": {
                    "active_preset": "Doubao",
                    "presets": [
                        {
                            "name": "OpenAI",
                            "model": "gpt-4o-mini",
                            "api_key": "YOUR_OPENAI_KEY",
                        },
                        {
                            "name": "Doubao",
                            "model": "doubao-seed-1-8-251228",
                            "api_key": "test-key",
                        },
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = deepcopy(CONFIG)
    with patch("os.path.join", return_value=str(override_file)):
        _apply_config_overrides(config)

    preset_names = [preset.get("name") for preset in config["api"]["presets"] if isinstance(preset, dict)]
    assert "OpenAI" in preset_names
    assert "Doubao" in preset_names
    assert "Ollama" in preset_names
