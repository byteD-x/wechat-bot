
import pytest
import sys
import os

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

@pytest.fixture
def mock_config():
    return {
        "bot": {
            "listen_list": ["User1"],
            "reply_interval": 1.0,
            "retry_count": 3,
        },
        "api": {
            "base_url": "http://localhost",
            "api_key": "sk-test",
            "model": "gpt-3.5-turbo",
        },
        "logging": {
            "level": "INFO",
            "log_file": "test.log",
        }
    }
