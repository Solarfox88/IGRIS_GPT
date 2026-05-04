"""
Best-task selection logic for IGRIS_GPT.

Implements advisory-aware task selection that honours external hints
while respecting safety, saturation and deduplication constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from igris.core import anti_loop, semantic_dedup
from igris.core.decision_memory import get_blocked_families_from_memory
from igris.models.task import Task, TaskStatus


@dataclass
class SelectionResult:
    """Result of the task selection process."""

    selected_task: Optional[Task] = None
    selected_source: str = "fallback"
    advisory_honored: bool = False
    rejected_advisory_reason: Optional[str] = None
    saturation_reason: Optional[str] = None
    duplicate_reason: Optional[str] = None
    safety_reason: Optional[str] = None
    fallback_reason: Optional[str] = None


def select_next_task(
    candidate_tasks: List[Task],
    advisory_next_task_id: Optional[int] = None,
    advisory_next_task_file: Optional[str] = None,
    history: Optional[List[str]] = None,
    blocked_families: Optional[List[str]] = None,
    project_root: Optional[str] = None,
) -> SelectionResult:
    """Select the next task to execute.

    If *advisory_next_task_id* is provided and the task passes all
    safety/saturation/duplication checks, it is honoured.  Otherwise
    the function falls back to picking the best candidate.
    """
    history = history or []
    blocked_families = list(blocked_families or [])
    memory_blocked = get_blocked_families_from_memory(project_root)
    for fam in memory_blocked:
        if fam not in blocked_families:
            blocked_families.append(fam)
    result = SelectionResult()

    pending = [t for t in candidate_tasks if t.status == TaskStatus.pending]
    if not pending:
        result.fallback_reason = "No pending tasks"
        return result

    counts = anti_loop.compute_family_counts(history)
    saturated = set(anti_loop.saturated_families(counts))

    # Try advisory task first
    advisory_task: Optional[Task] = None
    if advisory_next_task_id is not None:
        for t in pending:
            if t.id == advisory_next_task_id:
                advisory_task = t
                break

    if advisory_task is not None:
        family = advisory_task.family or anti_loop.classify_task_family(advisory_task.description)

        # Safety check
        if advisory_task.risk == "high":
            result.rejected_advisory_reason = "Task risk is high"
            result.safety_reason = "high risk task rejected"
        # Blocked check
        elif advisory_task.status == TaskStatus.blocked:
            result.rejected_advisory_reason = "Task is blocked"
        elif advisory_task.status == TaskStatus.completed:
            result.rejected_advisory_reason = "Task is already completed"
        elif family in blocked_families:
            result.rejected_advisory_reason = f"Family '{family}' is blocked"
        # Saturation check
        elif family in saturated:
            result.rejected_advisory_reason = f"Family '{family}' is saturated without differentiator"
            result.saturation_reason = f"Family '{family}' count exceeds threshold"
        # Duplicate check
        elif semantic_dedup.is_semantic_duplicate(advisory_task.description, history):
            is_dup, explanation = semantic_dedup.explain_duplicate(advisory_task.description, history)
            result.rejected_advisory_reason = "Task is a semantic duplicate"
            result.duplicate_reason = explanation
        else:
            # Advisory is valid
            result.selected_task = advisory_task
            result.selected_source = "advisory"
            result.advisory_honored = True
            return result

    # Fallback: pick best pending task
    for task in sorted(pending, key=lambda t: -t.priority):
        family = task.family or anti_loop.classify_task_family(task.description)
        if family in blocked_families:
            continue
        if family in saturated:
            continue
        if semantic_dedup.is_semantic_duplicate(task.description, history):
            continue
        result.selected_task = task
        result.selected_source = "fallback"
        if advisory_task is not None:
            result.advisory_honored = False
        return result

    # Last resort: first pending
    result.selected_task = pending[0]
    result.selected_source = "last_resort"
    result.fallback_reason = "All candidates saturated or duplicated; using first pending"
    return result
