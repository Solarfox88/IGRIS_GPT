"""
Simple memory management for IGRIS_GPT.

This module provides helper functions to persist simple JSON data
structures on disk under the `.igris/memory` directory of the
project.  Namespaces are used to isolate different kinds of
memory (e.g. chat sessions, task history, teacher messages).  The
interface is intentionally minimal: read, write, append and list
recent events.  More complex memory features (embedding storage,
semantic search) can be layered on top of this basic mechanism in
future iterations.

"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from igris.models.config import CONFIG


def _memory_base() -> Path:
    """Return the base directory for memory storage.

    The memory directory is located under `.igris/memory` relative to
    the project root.  If it does not exist, it is created.
    """
    base = CONFIG.project_root / ".igris" / "memory"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _namespace_path(namespace: str) -> Path:
    """Return the path to the JSON file for a given namespace."""
    return _memory_base() / f"{namespace}.json"


def read_memory(namespace: str) -> Any:
    """Read a memory namespace from disk.

    If the file does not exist, returns None.  Errors in reading or
    parsing the file are propagated to the caller.
    """
    path = _namespace_path(namespace)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_memory(namespace: str, data: Any) -> None:
    """Write an arbitrary JSON-serializable object to a namespace."""
    path = _namespace_path(namespace)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def append_memory_event(namespace: str, event: Dict[str, Any]) -> None:
    """Append a single event (dict) to a namespace list.

    If the namespace does not exist, it is created with a list containing
    the event.  If the existing data is not a list, it is replaced.
    """
    existing = read_memory(namespace)
    if not isinstance(existing, list):
        existing = []
    existing.append(event)
    write_memory(namespace, existing)


def recent_memory_events(namespace: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Return the most recent events from a namespace list.

    :param namespace: The namespace to read.
    :param limit: Maximum number of events to return (defaults to 20).
    :returns: A list of events ordered from oldest to newest.
    """
    data = read_memory(namespace)
    if not isinstance(data, list):
        return []
    return data[-limit:]