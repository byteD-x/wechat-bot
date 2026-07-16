"""SQLite 向量记忆的直接单元测试。

旧实现基于 ChromaDB 且被所有上层测试用 Dummy 替身覆盖,真实类无回归保护;
本文件针对 SQLite 实现直接验证写入/向量检索/关键词回退/过滤/删除/计数。
"""

import math

from backend.core.vector_memory import VectorMemory, _cosine_distance


def _make(tmp_path):
    return VectorMemory(db_path=str(tmp_path / "vector_db"))


def test_cosine_distance_basic():
    assert _cosine_distance([1.0, 0.0], [1.0, 0.0]) == 0.0
    assert math.isclose(_cosine_distance([1.0, 0.0], [0.0, 1.0]), 1.0, abs_tol=1e-9)
    assert math.isclose(_cosine_distance([1.0, 0.0], [-1.0, 0.0]), 2.0, abs_tol=1e-9)
    assert _cosine_distance([], [1.0]) == 1.0


def test_add_and_vector_search_orders_by_similarity(tmp_path):
    vm = _make(tmp_path)
    assert bool(vm) is True
    vm.add_text("今晚发布计划", {"chat_id": "c1", "source": "runtime_chat"}, "c1_a", [1.0, 0.0, 0.0])
    vm.add_text("无关的闲聊", {"chat_id": "c1", "source": "runtime_chat"}, "c1_b", [0.0, 1.0, 0.0])

    results = vm.search(n_results=2, filter_meta={"chat_id": "c1", "source": "runtime_chat"}, query_embedding=[0.9, 0.1, 0.0])
    assert [r["id"] for r in results] == ["c1_a", "c1_b"]
    assert results[0]["distance"] < results[1]["distance"]
    assert results[0]["metadata"]["chat_id"] == "c1"


def test_filter_isolates_chat_and_source(tmp_path):
    vm = _make(tmp_path)
    vm.add_text("A", {"chat_id": "c1", "source": "runtime_chat"}, "a", [1.0, 0.0])
    vm.add_text("B", {"chat_id": "c2", "source": "runtime_chat"}, "b", [1.0, 0.0])
    vm.add_text("C", {"chat_id": "c1", "source": "export_chat"}, "c", [1.0, 0.0])

    results = vm.search(n_results=10, filter_meta={"chat_id": "c1", "source": "runtime_chat"}, query_embedding=[1.0, 0.0])
    assert [r["id"] for r in results] == ["a"]


def test_upsert_replaces_same_id(tmp_path):
    vm = _make(tmp_path)
    vm.upsert_text("old", {"source": "knowledge_base", "doc_id": "d1"}, "d1_0", [1.0, 0.0])
    vm.upsert_text("new", {"source": "knowledge_base", "doc_id": "d1"}, "d1_0", [1.0, 0.0])
    assert vm.count({"source": "knowledge_base", "doc_id": "d1"}) == 1
    rows = vm.list_metadata({"source": "knowledge_base"})
    assert len(rows) == 1


def test_keyword_search_fallback_when_no_embedding(tmp_path):
    # BM25 为 token 级匹配(与原实现一致):CJK 连续串按整段成词,故用空格分词的可比 token。
    vm = _make(tmp_path)
    vm.add_text("发布 回滚 计划", {"source": "kb", "doc_id": "d"}, "k1", None)
    vm.add_text("完全 无关 内容", {"source": "kb", "doc_id": "d"}, "k2", None)
    results = vm.search(query="回滚", n_results=1, filter_meta={"source": "kb"})
    assert results and results[0]["id"] == "k1"


def test_delete_and_count(tmp_path):
    vm = _make(tmp_path)
    vm.add_text("A", {"source": "kb", "doc_id": "d1"}, "a", [1.0])
    vm.add_text("B", {"source": "kb", "doc_id": "d1"}, "b", [1.0])
    vm.add_text("C", {"source": "kb", "doc_id": "d2"}, "c", [1.0])
    assert vm.count({"source": "kb"}) == 3
    vm.delete({"source": "kb", "doc_id": "d1"})
    assert vm.count({"source": "kb"}) == 1
    assert vm.count({"source": "kb", "doc_id": "d2"}) == 1


def test_persists_across_instances(tmp_path):
    vm = _make(tmp_path)
    vm.add_text("persist", {"source": "kb", "doc_id": "d"}, "p1", [1.0, 0.0])
    reopened = _make(tmp_path)
    assert reopened.count({"source": "kb"}) == 1
