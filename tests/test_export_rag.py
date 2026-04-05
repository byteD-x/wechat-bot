import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.export_rag import ExportChatRAG


class DummyVectorMemory:
    def __init__(self):
        self.deleted = []
        self.upserts = []
        self.search_results = []

    def delete(self, where):
        self.deleted.append(where)

    def upsert_text(self, text, metadata, item_id, embedding):
        self.upserts.append({
            "text": text,
            "metadata": metadata,
            "id": item_id,
            "embedding": embedding,
        })

    def search(self, **kwargs):
        return list(self.search_results)


def _write_csv(csv_path: Path, rows):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["时间", "发送人", "类型", "内容"])
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.asyncio
async def test_export_rag_sync_builds_assistant_chunks_and_uses_manifest(tmp_path):
    base_dir = tmp_path / "chat_exports" / "聊天记录" / "张三(wxid_1)"
    csv_path = base_dir / "张三.csv"
    _write_csv(csv_path, [
        {"时间": "2025-01-01 10:00:00", "发送人": "知有", "类型": "文本", "内容": "早"},
        {"时间": "2025-01-01 10:00:05", "发送人": "知有", "类型": "文本", "内容": "吃了吗"},
        {"时间": "2025-01-01 10:01:00", "发送人": "张三", "类型": "文本", "内容": "刚起"},
        {"时间": "2025-01-01 10:02:00", "发送人": "知有", "类型": "文本", "内容": "那你先去洗漱"},
    ])

    vector_memory = DummyVectorMemory()
    ai_client = SimpleNamespace(
        embedding_model="text-embedding-3-small",
        get_embedding=AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )
    rag = ExportChatRAG(vector_memory)
    rag.manifest_path = str(tmp_path / "data" / "export_rag_manifest.json")
    rag.update_config({
        "export_rag_enabled": True,
        "export_rag_dir": str(tmp_path / "chat_exports" / "聊天记录"),
        "export_rag_chunk_messages": 2,
        "export_rag_max_chunks_per_chat": 10,
        "self_name": "知有",
    })

    result = await rag.sync(ai_client)

    assert result["success"] is True
    assert result["indexed_contacts"] == 1
    assert result["indexed_chunks"] == 2
    assert len(vector_memory.deleted) == 1
    assert vector_memory.deleted[0] == {"chat_id": "friend:张三", "source": "export_chat"}
    assert [item["text"] for item in vector_memory.upserts] == ["早\n吃了吗", "那你先去洗漱"]

    first_upserts = len(vector_memory.upserts)
    second = await rag.sync(ai_client)
    assert second["skipped_files"] == 1
    assert len(vector_memory.upserts) == first_upserts


@pytest.mark.asyncio
async def test_export_rag_search_filters_duplicates_and_distance():
    vector_memory = DummyVectorMemory()
    vector_memory.search_results = [
        {
            "text": "这周有空一起吃饭",
            "metadata": {"timestamp": 200},
            "distance": 0.3,
        },
        {
            "text": "这周有空一起吃饭",
            "metadata": {"timestamp": 100},
            "distance": 0.31,
        },
        {
            "text": "我先去忙啦",
            "metadata": {"timestamp": 300},
            "distance": 0.45,
        },
        {
            "text": "这个太远了",
            "metadata": {"timestamp": 500},
            "distance": 1.4,
        },
    ]
    ai_client = SimpleNamespace(
        embedding_model="text-embedding-3-small",
        get_embedding=AsyncMock(return_value=[0.2, 0.1]),
    )
    rag = ExportChatRAG(vector_memory)
    rag.update_config({
        "export_rag_enabled": True,
        "export_rag_top_k": 2,
        "export_rag_min_score": 0.8,
        "export_rag_max_context_chars": 200,
    })

    results = await rag.search(ai_client, "friend:张三", "晚上吃什么")
    assert [item["text"] for item in results] == ["这周有空一起吃饭", "我先去忙啦"]

    message = rag.build_memory_message(results)
    assert message is not None
    assert message["role"] == "system"
    assert "真实历史聊天" in message["content"]
    assert "这周有空一起吃饭" in message["content"]
    assert "我先去忙啦" in message["content"]


@pytest.mark.asyncio
async def test_export_rag_search_skips_group_chat():
    vector_memory = DummyVectorMemory()
    ai_client = SimpleNamespace(
        embedding_model="text-embedding-3-small",
        get_embedding=AsyncMock(return_value=[0.2, 0.1]),
    )
    rag = ExportChatRAG(vector_memory)
    rag.update_config({"export_rag_enabled": True})

    results = await rag.search(ai_client, "group:测试群", "你好")
    assert results == []


@pytest.mark.asyncio
async def test_export_rag_search_supports_legacy_display_name_alias():
    vector_memory = DummyVectorMemory()
    vector_memory.search_results = [
        {
            "text": "legacy style snippet",
            "metadata": {"timestamp": 200},
            "distance": 0.2,
        }
    ]
    ai_client = SimpleNamespace(
        embedding_model="text-embedding-3-small",
        get_embedding=AsyncMock(return_value=[0.2, 0.1]),
    )
    rag = ExportChatRAG(vector_memory)
    rag.update_config({
        "export_rag_enabled": True,
        "export_rag_top_k": 2,
        "export_rag_min_score": 0.8,
    })

    results = await rag.search(
        ai_client,
        "friend:wxid_zhangsan",
        "legacy question",
        chat_id_aliases=["friend:张三"],
    )

    assert [item["text"] for item in results] == ["legacy style snippet"]
