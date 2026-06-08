from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.knowledge_base import (
    KNOWLEDGE_SOURCE,
    KnowledgeBaseService,
    KnowledgeDocument,
    build_knowledge_index_payload,
)


class DummyVectorMemory:
    def __init__(self):
        self.deleted = []
        self.upserts = []

    def delete(self, where):
        self.deleted.append(where)

    def upsert_text(self, text, metadata, item_id, embedding):
        self.upserts.append(
            {
                "text": text,
                "metadata": metadata,
                "id": item_id,
                "embedding": embedding,
            }
        )


@pytest.mark.asyncio
async def test_knowledge_base_ingests_chunks_with_citation_metadata():
    vector_memory = DummyVectorMemory()
    ai_client = SimpleNamespace(get_embedding=AsyncMock(return_value=[0.1, 0.2, 0.3]))
    service = KnowledgeBaseService(vector_memory, chunk_size=140, chunk_overlap=20)
    content = (
        "Release plan section. QA signs off after smoke tests and rollback drills. "
        "The launch owner records the final checkpoint in the release tracker.\n\n"
        "Operations section. On-call watches latency, tool failures, and retrieval hit rate "
        "during the first hour after deployment."
    )

    summary = await service.ingest_document(
        KnowledgeDocument(
            content=content,
            doc_id="release-playbook",
            version="2026-06",
            source_file="docs/release-playbook.md",
            url="https://example.test/release-playbook",
            metadata={"page": 3, "owner": "platform"},
        ),
        ai_client,
    )

    assert summary["success"] is True
    assert summary["doc_id"] == "release-playbook"
    assert summary["version"] == "2026-06"
    assert summary["indexed_chunks"] == len(vector_memory.upserts)
    assert summary["indexed_chunks"] >= 2
    assert summary["skipped_chunks"] == 0
    assert len(summary["chunk_ids"]) == summary["indexed_chunks"]

    first = vector_memory.upserts[0]
    metadata = first["metadata"]
    assert first["id"].startswith("kb::")
    assert metadata["source"] == KNOWLEDGE_SOURCE
    assert metadata["scope"] == "knowledge"
    assert metadata["doc_id"] == "release-playbook"
    assert metadata["doc_version"] == "2026-06"
    assert metadata["chunk_id"] == first["id"]
    assert metadata["source_file"] == "docs/release-playbook.md"
    assert metadata["url"] == "https://example.test/release-playbook"
    assert metadata["page"] == 3
    assert metadata["owner"] == "platform"


@pytest.mark.asyncio
async def test_knowledge_base_rebuild_deletes_previous_document_chunks():
    vector_memory = DummyVectorMemory()
    ai_client = SimpleNamespace(get_embedding=AsyncMock(return_value=[0.1, 0.2]))
    service = KnowledgeBaseService(vector_memory)

    summary = await service.ingest_document(
        KnowledgeDocument(
            content="A short but useful runbook entry.",
            doc_id="runbook",
            version="v2",
        ),
        ai_client,
        rebuild=True,
    )

    assert summary["success"] is True
    assert summary["deleted_previous"] is True
    assert vector_memory.deleted == [{"source": KNOWLEDGE_SOURCE, "doc_id": "runbook"}]
    assert vector_memory.upserts[0]["metadata"]["doc_version"] == "v2"


@pytest.mark.asyncio
async def test_knowledge_base_rebuild_keeps_previous_chunks_when_embedding_is_incomplete():
    vector_memory = DummyVectorMemory()
    vector_memory.upsert_text(
        "old runbook chunk",
        {"source": KNOWLEDGE_SOURCE, "doc_id": "runbook"},
        "old-runbook",
        [0.9],
    )
    ai_client = SimpleNamespace(get_embedding=AsyncMock(side_effect=[[0.1], []]))
    service = KnowledgeBaseService(vector_memory, chunk_size=140, chunk_overlap=0)

    summary = await service.ingest_document(
        KnowledgeDocument(
            content=(
                "First runbook section has enough detail to become one chunk. "
                "It covers startup checks and owner confirmation.\n\n"
                "Second runbook section has enough detail to become another chunk. "
                "It covers rollback checks and incident notes."
            ),
            doc_id="runbook",
            version="v3",
        ),
        ai_client,
        rebuild=True,
    )

    assert summary["success"] is False
    assert summary["reason"] == "incomplete_embeddings"
    assert summary["deleted_previous"] is False
    assert summary["indexed_chunks"] == 0
    assert summary["skipped_chunks"] == 1
    assert vector_memory.deleted == []
    assert vector_memory.upserts == [
        {
            "text": "old runbook chunk",
            "metadata": {"source": KNOWLEDGE_SOURCE, "doc_id": "runbook"},
            "id": "old-runbook",
            "embedding": [0.9],
        }
    ]


@pytest.mark.asyncio
async def test_knowledge_base_skips_when_embedding_is_unavailable():
    vector_memory = DummyVectorMemory()
    ai_client = SimpleNamespace(get_embedding=AsyncMock(return_value=[]))
    service = KnowledgeBaseService(vector_memory)

    summary = await service.ingest_document(
        KnowledgeDocument(content="This document cannot be embedded.", doc_id="no-embedding"),
        ai_client,
    )

    assert summary["success"] is False
    assert summary["reason"] == "no_chunks_indexed"
    assert summary["indexed_chunks"] == 0
    assert summary["skipped_chunks"] == 1
    assert vector_memory.upserts == []


@pytest.mark.asyncio
async def test_knowledge_base_rejects_empty_document_without_embedding_call():
    vector_memory = DummyVectorMemory()
    ai_client = SimpleNamespace(get_embedding=AsyncMock(return_value=[0.1]))
    service = KnowledgeBaseService(vector_memory)

    summary = await service.ingest_document(KnowledgeDocument(content="   \n\n"), ai_client)

    assert summary["success"] is False
    assert summary["reason"] == "empty_document"
    assert summary["chunk_count"] == 0
    assert vector_memory.upserts == []
    ai_client.get_embedding.assert_not_awaited()


def test_knowledge_base_index_payload_groups_metadata_without_raw_content():
    payload = build_knowledge_index_payload(
        [
            {
                "id": "kb-1",
                "metadata": {
                    "source": KNOWLEDGE_SOURCE,
                    "doc_id": "release-playbook",
                    "doc_version": "2026-06",
                    "source_file": "Z:/fixture/private/release-playbook.md",
                    "url": "file:///Z:/fixture/private/source-url.md",
                    "page": 2,
                },
            },
            {
                "id": "kb-2",
                "metadata": {
                    "source": KNOWLEDGE_SOURCE,
                    "doc_id": "release-playbook",
                    "doc_version": "2026-06",
                    "source_file": "Z:/fixture/private/release-playbook.md",
                    "url": "file:///Z:/fixture/private/source-url.md",
                    "page": 3,
                },
            },
            {
                "id": "chat-1",
                "metadata": {
                    "source": "chat_memory",
                    "doc_id": "release-playbook",
                    "source_file": "Z:/fixture/private/chat.md",
                },
            },
        ],
        chunk_count=2,
        limit=1000,
    )

    assert payload["source"] == KNOWLEDGE_SOURCE
    assert payload["chunk_count"] == 2
    assert payload["indexed_chunk_count"] == 2
    assert payload["document_count"] == 1
    assert payload["truncated"] is False
    document = payload["documents"][0]
    assert document["doc_id"] == "release-playbook"
    assert document["version"] == "2026-06"
    assert document["versions"] == ["2026-06"]
    assert document["source_file"] == ".../release-playbook.md"
    assert document["source_files"] == [".../release-playbook.md"]
    assert document["url"] == ".../source-url.md"
    assert document["urls"] == [".../source-url.md"]
    assert document["pages"] == [2, 3]
    assert document["chunk_count"] == 2
    assert "text" not in str(payload)
    assert "Z:/fixture/private" not in str(payload)


def test_knowledge_base_index_payload_marks_truncated_metadata_listing():
    payload = build_knowledge_index_payload(
        [
            {
                "id": "kb-1",
                "metadata": {
                    "source": KNOWLEDGE_SOURCE,
                    "doc_id": "runbook",
                    "doc_version": "v1",
                },
            },
        ],
        chunk_count=3,
        limit=1,
    )

    assert payload["indexed_chunk_count"] == 1
    assert payload["chunk_count"] == 3
    assert payload["document_count"] == 1
    assert payload["truncated"] is True
