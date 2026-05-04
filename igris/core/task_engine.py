"""
Persistent task engine for IGRIS_GPT.

Tasks are stored as individual JSON files under ``.igris/tasks/``.
Timeline events go under ``.igris/timeline/``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from igris.core import anti_loop, semantic_dedup
from igris.models.config import CONFIG
from igris.models.task import Task, TaskStatus


def _runtime_root() -> Path:
    return CONFIG.project_root / ".igris"


class TaskEngine:
    """Persistent task engine backed by JSON files on disk."""

    def __init__(self, runtime_root: Optional[Path] = None) -> None:
        self._root = runtime_root or _runtime_root()
        self._tasks_dir = self._root / "tasks"
        self._timeline_dir = self._root / "timeline"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._timeline_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: List[Task] = []
        self._next_id: int = 1
        self._load_tasks()

    def _load_tasks(self) -> None:
        """Load all tasks from disk into memory."""
        self._tasks = []
        max_id = 0
        for fp in sorted(self._tasks_dir.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                task = Task.from_dict(data)
                self._tasks.append(task)
                if task.id >= max_id:
                    max_id = task.id
            except Exception:
                continue
        self._next_id = max_id + 1

    def _save_task(self, task: Task) -> None:
        fp = self._tasks_dir / f"{task.id}.json"
        fp.write_text(json.dumps(task.to_dict(), indent=2), encoding="utf-8")

    @property
    def tasks(self) -> List[Task]:
        return self._tasks

    def create_task(
        self,
        description: str,
        title: Optional[str] = None,
        family: Optional[str] = None,
        priority: int = 0,
        source: str = "user",
        risk: str = "low",
        success_criteria: Optional[List[str]] = None,
    ) -> Task:
        fam = family or anti_loop.classify_task_family(description)
        fp = semantic_dedup.semantic_fingerprint(description, fam)
        task = Task(
            id=self._next_id,
            description=description,
            title=title,
            family=fam,
            priority=priority,
            source=source,
            risk=risk,
            success_criteria=success_criteria or [],
            semantic_fingerprint=fp,
        )
        self._next_id += 1
        self._tasks.append(task)
        self._save_task(task)
        self.append_timeline_event({
            "event": "task_created",
            "task_id": task.id,
            "description": description,
            "source": source,
        })
        return task

    # Keep old add_task as an alias
    def add_task(self, description: str, source: str = "user") -> Task:
        return self.create_task(description, source=source)

    def load_task(self, task_id: int) -> Optional[Task]:
        return self.get_task(task_id)

    def get_task(self, task_id: int) -> Optional[Task]:
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    def list_tasks(self, status: Optional[str] = None) -> List[Task]:
        if status is None:
            return list(self._tasks)
        return [t for t in self._tasks if t.status.value == status]

    def update_task_status(
        self, task_id: int, status: TaskStatus,
        result: Optional[str] = None, reason: Optional[str] = None,
    ) -> Optional[Task]:
        task = self.get_task(task_id)
        if not task:
            return None
        task.status = status
        task.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if result is not None:
            task.result = result
        if reason is not None:
            task.blocked_reason = reason
        self._save_task(task)
        self.append_timeline_event({
            "event": f"task_{status.value}",
            "task_id": task_id,
            "result": result,
            "reason": reason,
        })
        return task

    def complete_task(self, task_id: int, result: Optional[str] = None) -> Optional[Task]:
        return self.update_task_status(task_id, TaskStatus.completed, result)

    def block_task(self, task_id: int, reason: Optional[str] = None) -> Optional[Task]:
        return self.update_task_status(task_id, TaskStatus.blocked, reason=reason)

    def next_task(self) -> Optional[Task]:
        pending = [t for t in self._tasks if t.status == TaskStatus.pending]
        if not pending:
            return None
        descriptions = [t.description for t in self._tasks]
        counts = anti_loop.compute_family_counts(descriptions)
        saturated = set(anti_loop.saturated_families(counts))
        for task in pending:
            family = anti_loop.classify_task_family(task.description)
            if family in saturated:
                continue
            if semantic_dedup.is_semantic_duplicate(task.description, descriptions[:-1]):
                continue
            return task
        return pending[0] if pending else None

    # ---- Timeline persistence ----

    def append_timeline_event(self, event: Dict) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        event.setdefault("timestamp", ts)
        idx = len(list(self._timeline_dir.glob("*.json")))
        fp = self._timeline_dir / f"{idx:06d}.json"
        fp.write_text(json.dumps(event, indent=2, default=str), encoding="utf-8")

    def recent_timeline_events(self, limit: int = 50) -> List[Dict]:
        files = sorted(self._timeline_dir.glob("*.json"))
        events: List[Dict] = []
        for fp in files[-limit:]:
            try:
                events.append(json.loads(fp.read_text(encoding="utf-8")))
            except Exception:
                continue
        return events
