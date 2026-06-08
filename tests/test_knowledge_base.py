import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.knowledge_base import (
    KNOWLEDGE_SOURCE,
    KnowledgeBaseJobQueue,
    KnowledgeBaseService,
    KnowledgeDocument,
    build_knowledge_auto_index_preview_payload,
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


def test_knowledge_base_auto_index_preview_uses_fixed_inbox_without_raw_content(tmp_path):
    inbox = tmp_path / "data" / "knowledge_base" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "runbook.md").write_text("Secret inbox runbook text must stay out of previews.", encoding="utf-8")
    (inbox / "faq.txt").write_text("Short FAQ entry for chunk preview.", encoding="utf-8")
    (inbox / "unsupported.pdf").write_text("PDF body should not be read.", encoding="utf-8")
    (inbox / "nested").mkdir()
    (inbox / "bad.md").write_bytes(b"\xff\xfe\x00")
    (inbox / "large.txt").write_text("x" * 41, encoding="utf-8")

    payload = build_knowledge_auto_index_preview_payload(inbox, max_file_chars=40)

    assert payload["success"] is True
    assert payload["dry_run"] is True
    assert payload["auto_index"] is True
    assert payload["fixed_inbox"] is True
    assert payload["source"] == KNOWLEDGE_SOURCE
    assert payload["exists"] is True
    assert payload["inbox"] == ".../inbox"
    assert payload["document_count"] == 1
    assert payload["skipped_count"] == 5
    assert payload["chunk_count"] == payload["documents"][0]["chunk_count"]
    assert payload["char_count"] == len("Short FAQ entry for chunk preview.")

    document = payload["documents"][0]
    assert document["name"] == "faq.txt"
    assert document["source_file"] == ".../faq.txt"
    assert document["doc_id"] == ".../faq.txt"
    assert document["content_type"] == "text"
    assert document["chunk_ids"]
    assert document["chunks"][0]["source_file"] == ".../faq.txt"

    skipped = {item["name"]: item["reason"] for item in payload["skipped"]}
    assert skipped == {
        "bad.md": "unsupported_encoding",
        "large.txt": "file_too_large",
        "nested": "directory_ignored",
        "runbook.md": "file_too_large",
        "unsupported.pdf": "unsupported_extension",
    }
    payload_text = str(payload)
    assert "Secret inbox runbook" not in payload_text
    assert "Short FAQ entry" not in payload_text
    assert "PDF body" not in payload_text
    assert str(tmp_path) not in payload_text


def test_knowledge_base_auto_index_preview_reports_missing_inbox_without_creating_it(tmp_path):
    inbox = tmp_path / "data" / "knowledge_base" / "inbox"

    payload = build_knowledge_auto_index_preview_payload(inbox)

    assert payload["success"] is True
    assert payload["exists"] is False
    assert payload["document_count"] == 0
    assert payload["skipped_count"] == 0
    assert not inbox.exists()


@pytest.mark.asyncio
async def test_knowledge_base_job_queue_runs_documents_without_raw_content():
    vector_memory = DummyVectorMemory()
    ai_client = SimpleNamespace(get_embedding=AsyncMock(return_value=[0.1, 0.2]))
    queue = KnowledgeBaseJobQueue(max_jobs=4)
    raw_content = "Secret queued runbook text must not appear in job status."

    queued = await queue.enqueue(
        mode="ingest",
        documents=[
            KnowledgeDocument(
                content=raw_content,
                doc_id="queued-runbook",
                version="2026-06",
                source_file="Z:/fixture/private/queued-runbook.md",
                url="file:///Z:/fixture/private/source-url.md",
                metadata={"page": 7},
            )
        ],
        vector_memory=vector_memory,
        ai_client=ai_client,
    )

    assert queued["status"] == "queued"
    assert queued["documents"][0]["doc_id"] == "queued-runbook"
    assert queued["documents"][0]["source_file"] == ".../queued-runbook.md"
    assert queued["documents"][0]["url"] == ".../source-url.md"

    completed = await _wait_for_knowledge_job(queue, queued["job_id"])
    assert completed["status"] == "succeeded"
    assert completed["result"]["success"] is True
    assert completed["result"]["indexed_chunks"] == len(vector_memory.upserts)
    assert completed["result"]["documents"][0]["doc_id"] == "queued-runbook"
    assert vector_memory.upserts[0]["metadata"]["source_file"] == ".../queued-runbook.md"

    status_text = str(completed)
    assert "Secret queued runbook" not in status_text
    assert "Z:/fixture/private" not in status_text
    assert "file://" not in status_text


@pytest.mark.asyncio
async def test_knowledge_base_job_queue_marks_document_failures():
    vector_memory = DummyVectorMemory()
    ai_client = SimpleNamespace(get_embedding=AsyncMock(return_value=[]))
    queue = KnowledgeBaseJobQueue(max_jobs=4)

    queued = await queue.enqueue(
        mode="rebuild",
        documents=[KnowledgeDocument(content="A document with no embedding.", doc_id="no-embedding")],
        vector_memory=vector_memory,
        ai_client=ai_client,
    )

    completed = await _wait_for_knowledge_job(queue, queued["job_id"])
    assert completed["status"] == "failed"
    assert completed["success"] is False
    assert completed["error"] == "no_chunks_indexed"
    assert completed["result"]["success"] is False
    assert completed["result"]["documents"][0]["reason"] == "no_chunks_indexed"
    assert vector_memory.upserts == []


async def _wait_for_knowledge_job(queue, job_id):
    for _ in range(50):
        payload = await queue.get_job(job_id)
        if payload.get("status") not in {"queued", "running"}:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError(f"knowledge job did not finish: {job_id}")
