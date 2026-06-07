import json

from backend.core.response_cache import ResponseCache


def _build_key(
    cache,
    *,
    chat_id="friend:alice",
    provider_id="OpenAI",
    model="test-model",
    user_text="secret user question",
    prompt_context=None,
    citation_ids=None,
    policy_context=None,
):
    citations = [
        {"citation_id": citation_id}
        for citation_id in (citation_ids if citation_ids is not None else ["c-1"])
    ]
    messages = list(prompt_context or [])
    messages.append(
        {
            "role": "user",
            "content": "secret prompt message",
            "additional_kwargs": {"trace": "secret-extra"},
        }
    )
    return cache.build_key(
        provider_id=provider_id,
        model=model,
        chat_id=chat_id,
        user_text=user_text,
        system_prompt="secret system prompt",
        prompt_messages=messages,
        retrieval={"citations": citations},
        policy_context=policy_context or {"safety_require_citations_for_rag": True},
    )


def test_response_cache_is_disabled_by_default():
    cache = ResponseCache()
    key = _build_key(cache)

    assert cache.get_status()["enabled"] is False
    assert cache.get_status()["semantic_enabled"] is False
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


def test_response_cache_semantic_disabled_by_default():
    cache = ResponseCache({"enabled": True})
    key = _build_key(cache)
    similar = _build_key(cache, user_text="secret similar question")

    assert cache.set(key, answer_text="answer", query_embedding=[1.0, 0.0]) is True
    assert cache.get_semantic(similar, [1.0, 0.0]) is None

    status = cache.get_status()
    assert status["semantic_enabled"] is False
    assert status["semantic_skipped"] == 1


def test_response_cache_semantic_hit_is_context_bound_and_redacted():
    cache = ResponseCache(
        {
            "enabled": True,
            "semantic_enabled": True,
            "semantic_similarity_threshold": 0.9,
        }
    )
    prompt_context = [{"role": "system", "content": "stable context"}]
    key = _build_key(cache, prompt_context=prompt_context)
    similar = _build_key(
        cache,
        user_text="secret user question paraphrase",
        prompt_context=prompt_context,
    )

    assert key.key != similar.key
    assert key.semantic_context_key == similar.semantic_context_key
    assert cache.set(key, answer_text="answer", query_embedding=[1.0, 0.0]) is True

    hit = cache.get_semantic(similar, [0.96, 0.04])

    assert hit is not None
    assert hit.answer_text == "answer"
    assert hit.semantic_similarity >= 0.9
    status = cache.get_status()
    assert status["semantic_hits"] == 1
    serialized = json.dumps(similar.to_dict(), ensure_ascii=False)
    assert "secret user question paraphrase" not in serialized
    assert "stable context" not in serialized


def test_response_cache_semantic_rejects_different_boundaries():
    cache = ResponseCache(
        {
            "enabled": True,
            "semantic_enabled": True,
            "semantic_similarity_threshold": 0.9,
        }
    )
    key = _build_key(
        cache,
        prompt_context=[{"role": "assistant", "content": "stable context"}],
    )
    assert cache.set(key, answer_text="answer", query_embedding=[1.0, 0.0]) is True

    variants = [
        _build_key(cache, chat_id="friend:bob"),
        _build_key(cache, provider_id="qwen"),
        _build_key(cache, model="other-model"),
        _build_key(
            cache,
            policy_context={"safety_require_citations_for_rag": False},
        ),
        _build_key(cache, citation_ids=["c-2"]),
        _build_key(
            cache,
            prompt_context=[{"role": "assistant", "content": "different context"}],
        ),
    ]

    for variant in variants:
        assert variant.semantic_context_key != key.semantic_context_key
        assert cache.get_semantic(variant, [1.0, 0.0]) is None

    assert cache.get_status()["semantic_misses"] == len(variants)


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
