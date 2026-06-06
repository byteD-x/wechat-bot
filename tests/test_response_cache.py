import json

from backend.core.response_cache import ResponseCache


def _build_key(cache, *, chat_id="friend:alice", citation_ids=None, policy_context=None):
    citations = [
        {"citation_id": citation_id}
        for citation_id in (citation_ids if citation_ids is not None else ["c-1"])
    ]
    return cache.build_key(
        provider_id="OpenAI",
        model="test-model",
        chat_id=chat_id,
        user_text="secret user question",
        system_prompt="secret system prompt",
        prompt_messages=[
            {
                "role": "user",
                "content": "secret prompt message",
                "additional_kwargs": {"trace": "secret-extra"},
            }
        ],
        retrieval={"citations": citations},
        policy_context=policy_context or {"safety_require_citations_for_rag": True},
    )


def test_response_cache_is_disabled_by_default():
    cache = ResponseCache()
    key = _build_key(cache)

    assert cache.get_status()["enabled"] is False
    assert cache.get(key) is None
    assert cache.set(key, answer_text="answer") is False
    assert cache.get_status()["skipped"] == 2


def test_response_cache_key_is_context_bound_and_does_not_expose_raw_text():
    cache = ResponseCache({"enabled": True})

    key = _build_key(cache)
    different_chat = _build_key(cache, chat_id="friend:bob")
    different_citation = _build_key(cache, citation_ids=["c-2"])
    different_policy = _build_key(
        cache,
        policy_context={"safety_require_citations_for_rag": False},
    )

    assert key.key != different_chat.key
    assert key.key != different_citation.key
    assert key.key != different_policy.key
    assert key.citation_ids == ["c-1"]

    serialized = json.dumps(key.to_dict(), ensure_ascii=False)
    assert "friend:alice" not in serialized
    assert "secret user question" not in serialized
    assert "secret system prompt" not in serialized
    assert "secret prompt message" not in serialized
    assert "secret-extra" not in serialized


def test_response_cache_ttl_expiry(monkeypatch):
    import backend.core.response_cache as response_cache_module

    now = 100.0
    monkeypatch.setattr(response_cache_module.time, "time", lambda: now)

    cache = ResponseCache({"enabled": True, "ttl_sec": 1})
    key = _build_key(cache)
    assert cache.set(key, answer_text="answer") is True

    now = 100.5
    assert cache.get(key) is not None

    now = 101.0
    assert cache.get(key) is None
    status = cache.get_status()
    assert status["expired"] == 1
    assert status["misses"] == 1
    assert status["size"] == 0


def test_response_cache_evicts_oldest_entry(monkeypatch):
    import backend.core.response_cache as response_cache_module

    now = 200.0
    monkeypatch.setattr(response_cache_module.time, "time", lambda: now)

    cache = ResponseCache({"enabled": True, "ttl_sec": 60, "max_entries": 1})
    first = _build_key(cache, chat_id="friend:first")
    second = _build_key(cache, chat_id="friend:second")

    assert cache.set(first, answer_text="first answer") is True
    now = 201.0
    assert cache.set(second, answer_text="second answer") is True

    status = cache.get_status()
    assert status["evictions"] == 1
    assert status["size"] == 1
    assert cache.get(first) is None
    assert cache.get(second).answer_text == "second answer"
