import json

import pytest

from deeptutor.api.utils.task_log_stream import KnowledgeTaskStreamManager


@pytest.mark.asyncio
async def test_knowledge_task_stream_emits_process_log_sse_event():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-1")
    manager.emit_log("task-1", "Indexing started")

    stream = manager.stream("task-1")
    try:
        chunk = await anext(stream)
    finally:
        await stream.aclose()

    lines = chunk.splitlines()
    header, data_line = lines[:2]
    assert header == "event: process_log"
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["type"] == "process_log"
    assert payload["message"] == "Indexing started"
    assert payload["context"]["task_id"] == "task-1"


def test_completed_task_buffers_are_bounded_and_restore_terminal_event():
    manager = KnowledgeTaskStreamManager()
    manager._MAX_RETAINED_TASKS = 3

    for index in range(8):
        task_id = f"task-{index}"
        manager.ensure_task(task_id)
        manager.emit_log(task_id, "x" * 100)
        manager.emit_complete(task_id)

    assert manager.retained_task_count() == 3
    assert len(manager._terminal_tombstones) == 5

    manager.ensure_task("task-0")
    restored = list(manager._buffers["task-0"])
    assert restored[-1]["event"] == "complete"


def test_task_buffer_has_approximate_byte_ceiling():
    manager = KnowledgeTaskStreamManager()
    manager._MAX_BYTES_PER_TASK = 2_000
    manager.ensure_task("large-task")

    for _ in range(20):
        manager.emit_log("large-task", "x" * 500)

    assert manager._buffer_bytes["large-task"] <= manager._MAX_BYTES_PER_TASK
    assert len(manager._buffers["large-task"]) < 20
