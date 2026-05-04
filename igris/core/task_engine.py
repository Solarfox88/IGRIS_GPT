"""
Simple task engine used by IGRIS_GPT.

The task engine maintains a list of tasks and selects the next one to execute
while avoiding repetitive task families using the anti‑loop heuristics.
"""

from __future__ import annotations

from typing import List, Optional

from igris.core import anti_loop
from igris.core import semantic_dedup
from igris.models.task import Task, TaskStatus


class TaskEngine:
    """In‑memory task engine for selecting and managing tasks."""

    def __init__(self) -> None:
        self._tasks: List[Task] = []
        self._next_id: int = 1

    @property
    def tasks(self) -> List[Task]:
        return self._tasks

    def add_task(self, description: str) -> Task:
        task = Task(id=self._next_id, description=description)
        self._next_id += 1
        self._tasks.append(task)
        return task

    def get_task(self, task_id: int) -> Optional[Task]:
        """Return the task with the given ID, or None if not found."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    def update_task_status(self, task_id: int, status: TaskStatus, result: Optional[str] = None) -> Optional[Task]:
        """Update the status (and optional result) of a task.

        :returns: The updated task or None if the task was not found.
        """
        task = self.get_task(task_id)
        if not task:
            return None
        task.status = status
        if result is not None:
            task.result = result
        return task

    def complete_task(self, task_id: int, result: Optional[str] = None) -> Optional[Task]:
        """Mark a task as completed and optionally set its result."""
        return self.update_task_status(task_id, TaskStatus.completed, result)

    def block_task(self, task_id: int, reason: Optional[str] = None) -> Optional[Task]:
        """Mark a task as blocked and set the result to the reason."""
        return self.update_task_status(task_id, TaskStatus.blocked, reason)

    def next_task(self) -> Optional[Task]:
        """Return the next task to execute or None if all are completed/blocked.

        This method uses the anti‑loop heuristics to avoid choosing a task from
        a saturated family.  If all pending tasks are from saturated families
        then None is returned.
        """
        pending = [t for t in self._tasks if t.status == TaskStatus.pending]
        if not pending:
            return None
        # Compute family counts from recent task descriptions
        descriptions = [t.description for t in self._tasks]
        counts = anti_loop.compute_family_counts(descriptions)
        saturated = set(anti_loop.saturated_families(counts))
        # Iterate over pending tasks in order and pick the first that is not saturated
        # and not a semantic duplicate of a recent task
        for task in pending:
            family = anti_loop.classify_task_family(task.description)
            if family in saturated:
                continue
            # Skip if the task is a semantic duplicate of a recent one
            if semantic_dedup.is_semantic_duplicate(task.description, descriptions[:-1]):
                continue
            return task
        # If none found, fallback to first pending task
        return pending[0] if pending else None