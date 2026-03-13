
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from quart import Quart

# Mock wxauto before importing api
import sys
sys.modules["wxauto"] = MagicMock()

# Import app
from backend.api import app
import backend.api as api_module

@pytest.fixture
def client():
    app.config['TESTING'] = True
    return app.test_client()

@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager.get_status.return_value = {"running": True}
    manager.start = AsyncMock(return_value={"status": "started"})
    manager.stop = AsyncMock(return_value={"status": "stopped"})
    manager.pause = AsyncMock(return_value={"status": "paused"})
    manager.resume = AsyncMock(return_value={"status": "resumed"})
    manager.restart = AsyncMock(return_value={"status": "restarted"})
    manager.reload_runtime_config = AsyncMock(return_value={"success": True, "message": "运行中的 AI 已立即切换到 DeepSeek", "runtime_preset": "DeepSeek"})
    manager.is_running = True
    manager.bot = MagicMock()

    # Mock MemoryManager
    mem_mgr = MagicMock()
    async def async_get_messages(*args, **kwargs):
        return []
    mem_mgr.get_global_recent_messages = MagicMock(side_effect=async_get_messages)
    manager.get_memory_manager.return_value = mem_mgr
    
    # Replace the manager in the api module
    original_manager = api_module.manager
    api_module.manager = manager
    yield manager
    # Restore
    api_module.manager = original_manager

@pytest.mark.asyncio
async def test_api_status(client, mock_manager):
    response = await client.get('/api/status')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["running"] is True
    mock_manager.get_status.assert_called_once()

@pytest.mark.asyncio
async def test_api_start(client, mock_manager):
    response = await client.post('/api/start')
    assert response.status_code == 200
    mock_manager.start.assert_called_once()

@pytest.mark.asyncio
async def test_api_stop(client, mock_manager):
    response = await client.post('/api/stop')
    assert response.status_code == 200
    mock_manager.stop.assert_called_once()

@pytest.mark.asyncio
async def test_api_messages(client, mock_manager):
    response = await client.get('/api/messages?limit=10')
    assert response.status_code == 200
    mock_manager.get_memory_manager.assert_called()
    mock_manager.get_memory_manager().get_global_recent_messages.assert_called_with(limit=10)

@pytest.mark.asyncio
async def test_api_send(client, mock_manager):
    mock_manager.send_message = AsyncMock(return_value={"success": True})
    response = await client.post('/api/send', json={"target": "User", "content": "Hello"})
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    mock_manager.send_message.assert_called_with("User", "Hello")

@pytest.mark.asyncio
async def test_api_usage(client, mock_manager):
    mock_manager.get_usage.return_value = {"total_tokens": 100}
    response = await client.get('/api/usage')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["stats"]["total_tokens"] == 100

@pytest.mark.asyncio
async def test_api_messages_error(client, mock_manager):
    mock_manager.get_memory_manager().get_global_recent_messages.side_effect = Exception("DB Error")
    response = await client.get('/api/messages?limit=10')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is False
    assert "DB Error" in data["message"]

@pytest.mark.asyncio
async def test_api_send_error(client, mock_manager):
    mock_manager.send_message.side_effect = Exception("Send Error")
    response = await client.post('/api/send', json={"target": "User", "content": "Hello"})
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is False
    assert "Send Error" in data["message"]

@pytest.mark.asyncio
async def test_api_usage_error(client, mock_manager):
    mock_manager.get_usage.side_effect = Exception("Usage Error")
    response = await client.get('/api/usage')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is False
    assert "Usage Error" in data["message"]


@pytest.mark.asyncio
async def test_api_model_catalog(client):
    response = await client.get('/api/model_catalog')
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    qwen = next((provider for provider in data["providers"] if provider["id"] == "qwen"), None)
    assert qwen is not None
    assert "qwen3.5-plus" in qwen["models"]


@pytest.mark.asyncio
async def test_api_config_masks_key_and_infers_provider(client):
    test_config = {
        "api": {
            "presets": [
                {
                    "name": "Qwen",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "sk-1234567890abcdef",
                    "model": "qwen3.5-plus",
                    "alias": "小千",
                    "timeout_sec": 10,
                    "max_retries": 2,
                    "temperature": 0.6,
                    "max_tokens": 512,
                    "allow_empty_key": False,
                }
            ]
        },
        "bot": {},
        "logging": {},
    }

    with patch("backend.config.CONFIG", test_config):
        response = await client.get('/api/config')

    assert response.status_code == 200
    data = await response.get_json()
    preset = data["api"]["presets"][0]
    assert preset["provider_id"] == "qwen"
    assert preset["api_key_configured"] is True
    assert "api_key" not in preset


@pytest.mark.asyncio
async def test_api_config_marks_ollama_as_no_key_required(client):
    test_config = {
        "api": {
            "presets": [
                {
                    "name": "Ollama",
                    "provider_id": "ollama",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "api_key": "",
                    "model": "qwen3",
                    "alias": "本地",
                    "timeout_sec": 20,
                    "max_retries": 1,
                    "temperature": 0.6,
                    "max_tokens": 512,
                    "allow_empty_key": True,
                }
            ]
        },
        "bot": {},
        "logging": {},
    }

    with patch("backend.config.CONFIG", test_config):
        response = await client.get('/api/config')

    data = await response.get_json()
    preset = data["api"]["presets"][0]
    assert preset["provider_id"] == "ollama"
    assert preset["api_key_required"] is False
    assert preset["api_key_configured"] is False


@pytest.mark.asyncio
async def test_api_ollama_models(client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "models": [
            {"name": "qwen3:8b"},
            {"model": "llama3.1:8b"},
        ]
    }
    mock_response.raise_for_status.return_value = None

    with patch("backend.api.httpx.get", return_value=mock_response) as mock_get:
        response = await client.get('/api/ollama/models?base_url=http://127.0.0.1:11434/v1')

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["models"] == ["qwen3:8b", "llama3.1:8b"]
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_api_save_config_triggers_runtime_reload(client, mock_manager):
    test_config = {
        "api": {
            "active_preset": "OpenAI",
            "presets": [
                {
                    "name": "OpenAI",
                    "provider_id": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-test-openai",
                    "model": "gpt-5-mini",
                    "alias": "小欧",
                    "allow_empty_key": False,
                },
                {
                    "name": "DeepSeek",
                    "provider_id": "deepseek",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-test-deepseek",
                    "model": "deepseek-chat",
                    "alias": "小深",
                    "allow_empty_key": False,
                },
            ],
        },
        "bot": {},
        "logging": {},
    }

    async_to_thread = AsyncMock(return_value={})
    with (
        patch("backend.api.asyncio.to_thread", async_to_thread),
        patch("backend.api._build_config_payload", return_value=test_config),
        patch("backend.config.CONFIG", test_config),
        patch("backend.config._apply_config_overrides"),
        patch("backend.config._apply_api_keys"),
        patch("backend.config._apply_prompt_overrides"),
    ):
        response = await client.post("/api/config", json={"api": {"active_preset": "DeepSeek"}})

    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"] is True
    assert data["config"]["api"]["active_preset"] == "OpenAI"
    assert data["runtime_apply"]["success"] is True
    mock_manager.reload_runtime_config.assert_awaited_once()
