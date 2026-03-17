from backend.core.provider_compat import (
    build_openai_chat_payload,
    normalize_chat_result,
    normalize_provider_error,
)


class _FakeResponse:
    def __init__(self, status_code=502, payload=None, text="bad gateway"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_normalize_chat_result_extracts_text_reasoning_and_tool_calls():
    normalized = normalize_chat_result(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": [{"type": "text", "text": "最终答案"}],
                        "reasoning_content": "这是推理",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "search_web",
                                    "arguments": {"query": "天气"},
                                },
                            }
                        ],
                    },
                }
            ]
        }
    )

    assert normalized.text == "最终答案"
    assert normalized.reasoning == "这是推理"
    assert normalized.finish_reason == "tool_calls"
    assert len(normalized.tool_calls) == 1
    assert normalized.tool_calls[0].name == "search_web"
    assert '"query": "天气"' in normalized.tool_calls[0].arguments


def test_build_openai_chat_payload_uses_completion_token_precedence():
    payload = build_openai_chat_payload(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
        temperature=0.3,
        max_tokens=256,
        max_completion_tokens=128,
        reasoning_effort="medium",
    )

    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["max_completion_tokens"] == 128
    assert "max_tokens" not in payload
    assert payload["reasoning_effort"] == "medium"


def test_normalize_provider_error_prefers_provider_payload():
    response = _FakeResponse(
        status_code=429,
        payload={"error": {"message": "rate limit", "code": "too_many_requests", "type": "limit"}},
        text='{"error":{"message":"rate limit"}}',
    )

    normalized = normalize_provider_error(response=response)

    assert normalized.message == "rate limit"
    assert normalized.code == "too_many_requests"
    assert normalized.type == "limit"
    assert normalized.retryable is True
