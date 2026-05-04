"""Tests for the memory module."""
import os
from igris.core.memory import append_memory_event, recent_memory_events, read_memory
from igris.models.config import CONFIG


def test_append_and_read(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    append_memory_event("test_ns", {"action": "hello", "value": 1})
    events = recent_memory_events("test_ns", limit=10)
    assert len(events) == 1
    assert events[0]["action"] == "hello"


def test_recent_with_limit(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    for i in range(5):
        append_memory_event("limit_ns", {"i": i})
    events = recent_memory_events("limit_ns", limit=3)
    assert len(events) == 3
    assert events[0]["i"] == 2


def test_missing_namespace_returns_empty(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    os.environ["PROJECT_ROOT"] = str(root)
    CONFIG.project_root = root

    events = recent_memory_events("nonexistent_ns")
    assert events == []
