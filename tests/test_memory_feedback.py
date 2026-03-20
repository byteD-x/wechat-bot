import pytest

from backend.core.memory import MemoryManager


@pytest.mark.asyncio
async def test_memory_manager_update_message_feedback_persists_metadata(tmp_path):
    manager = MemoryManager(str(tmp_path / "chat_memory.db"))
    await manager.add_message(
        "friend:alice",
        "assistant",
        "hello",
        metadata={"reply_quality": {"user_feedback": "helpful"}},
    )

    page = await manager.get_message_page(chat_id="friend:alice")
    message_id = page["messages"][0]["id"]

    updated = await manager.update_message_feedback(message_id, "unhelpful")

    assert updated is not None
    assert updated["feedback"] == "unhelpful"
    assert updated["metadata"]["reply_quality"]["user_feedback"] == "unhelpful"

    latest = await manager.get_message_page(chat_id="friend:alice")
    assert latest["messages"][0]["metadata"]["reply_quality"]["user_feedback"] == "unhelpful"

    cleared = await manager.update_message_feedback(message_id, "")
    assert cleared["feedback"] == ""
    assert "user_feedback" not in cleared["metadata"].get("reply_quality", {})

    await manager.close()


@pytest.mark.asyncio
async def test_memory_manager_message_page_prefers_display_name_for_ui(tmp_path):
    manager = MemoryManager(str(tmp_path / "chat_memory.db"))
    await manager.add_message("friend:alice", "user", "hello")
    await manager.add_message("friend:alice", "assistant", "hi")
    await manager.update_user_profile("friend:alice", nickname="Alice")

    page = await manager.get_message_page(chat_id="friend:alice")

    assert len(page["messages"]) == 2
    latest_assistant = page["messages"][0]
    latest_user = page["messages"][1]

    assert latest_assistant["sender"] == "AI"
    assert latest_assistant["display_name"] == "Alice"
    assert latest_assistant["chat_display_name"] == "Alice"
    assert latest_user["sender"] == "Alice"
    assert latest_user["sender_display_name"] == "Alice"

    await manager.close()
