"""
A2A task store with artifact and event management.

Provides persistent storage for A2A tasks, their artifacts, and events.
Supports long-running task patterns with status transitions and cancellation.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from igris.core.safety import redact_secrets

# Maximum artifact content size (text only, 100 KB)
MAX_ARTIFACT_SIZE = 100_000


def _a2a_dir(project_root: Optional[str] = None) -> Path:
    if project_root:
        d = Path(project_root) / ".igris" / "a2a"
    else:
        from igris.models.config import CONFIG
        d = CONFIG.project_root / ".igris" / "a2a"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tasks_dir(project_root: Optional[str] = None) -> Path:
    d = _a2a_dir(project_root) / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_task(task_id: str, project_root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    fp = _tasks_dir(project_root) / f"{task_id}.json"
    if not fp.exists():
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def _save_task(task: Dict[str, Any], project_root: Optional[str] = None) -> None:
    fp = _tasks_dir(project_root) / f"{task['id']}.json"
    fp.write_text(json.dumps(task, indent=2, default=str), encoding="utf-8")


def _redact_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Redact secrets from task data."""
    for key in ("title", "description"):
        if key in task and isinstance(task[key], str):
            task[key] = redact_secrets(task[key])
    for art in task.get("artifacts", []):
        if "content" in art and isinstance(art["content"], str):
            art["content"] = redact_secrets(art["content"])
        if "name" in art and isinstance(art["name"], str):
            art["name"] = redact_secrets(art["name"])
    for ev in task.get("events", []):
        if "detail" in ev and isinstance(ev["detail"], str):
            ev["detail"] = redact_secrets(ev["detail"])
    return task


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------

VALID_STATUSES = {"submitted", "working", "input_required", "completed", "failed", "canceled"}
TERMINAL_STATUSES = {"completed", "failed", "canceled"}


def create_a2a_task(
    title: str = "",
    description: str = "",
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    task = {
        "id": uuid.uuid4().hex[:12],
        "title": redact_secrets(title),
        "description": redact_secrets(description),
        "status": "submitted",
        "created_at": time.time(),
        "updated_at": time.time(),
        "artifacts": [],
        "events": [
            {"type": "status_change", "status": "submitted",
             "timestamp": time.time(), "detail": "Task created"},
        ],
    }
    _save_task(task, project_root)
    return _redact_task(dict(task))


def get_a2a_task(task_id: str, project_root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    task = _load_task(task_id, project_root)
    if task is None:
        return None
    return _redact_task(dict(task))


def list_a2a_tasks(project_root: Optional[str] = None) -> List[Dict[str, Any]]:
    tasks = []
    d = _tasks_dir(project_root)
    for fp in sorted(d.glob("*.json")):
        try:
            t = json.loads(fp.read_text(encoding="utf-8"))
            tasks.append(_redact_task(t))
        except Exception:
            continue
    return tasks


def update_a2a_task_status(
    task_id: str,
    status: str,
    detail: str = "",
    project_root: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    task = _load_task(task_id, project_root)
    if task is None:
        return None
    if status not in VALID_STATUSES:
        return None
    old_status = task.get("status", "")
    if old_status in TERMINAL_STATUSES:
        return None  # Cannot transition from terminal status
    task["status"] = status
    task["updated_at"] = time.time()
    task.setdefault("events", []).append({
        "type": "status_change",
        "status": status,
        "timestamp": time.time(),
        "detail": redact_secrets(detail),
    })
    _save_task(task, project_root)
    return _redact_task(dict(task))


def cancel_a2a_task(
    task_id: str,
    reason: str = "",
    project_root: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return update_a2a_task_status(task_id, "canceled", detail=reason or "Canceled by user", project_root=project_root)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

def _is_secret_like(content: str) -> bool:
    """Check if content looks like it contains secrets."""
    from igris.core.safety import redact_secrets
    redacted = redact_secrets(content)
    return redacted != content


def add_artifact(
    task_id: str,
    name: str,
    content: str,
    mime_type: str = "text/plain",
    project_root: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    task = _load_task(task_id, project_root)
    if task is None:
        return None

    # Safety: text only, size limit
    if len(content) > MAX_ARTIFACT_SIZE:
        return {"error": f"Artifact too large: {len(content)} bytes (max {MAX_ARTIFACT_SIZE})"}

    # Safety: redact secrets in content
    safe_content = redact_secrets(content)
    safe_name = redact_secrets(name)

    artifact = {
        "id": uuid.uuid4().hex[:8],
        "name": safe_name,
        "content": safe_content,
        "mime_type": mime_type,
        "created_at": time.time(),
    }
    task.setdefault("artifacts", []).append(artifact)
    task["updated_at"] = time.time()
    task.setdefault("events", []).append({
        "type": "artifact_added",
        "artifact_id": artifact["id"],
        "timestamp": time.time(),
        "detail": f"Artifact added: {safe_name}",
    })
    _save_task(task, project_root)
    return artifact


def get_artifacts(
    task_id: str,
    project_root: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    task = _load_task(task_id, project_root)
    if task is None:
        return None
    artifacts = task.get("artifacts", [])
    # Redact all content
    for a in artifacts:
        if "content" in a and isinstance(a["content"], str):
            a["content"] = redact_secrets(a["content"])
    return artifacts


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def get_events(
    task_id: str,
    project_root: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    task = _load_task(task_id, project_root)
    if task is None:
        return None
    events = task.get("events", [])
    for e in events:
        if "detail" in e and isinstance(e["detail"], str):
            e["detail"] = redact_secrets(e["detail"])
    return events
