"""Decision reports per loop cycle.

Creates a structured JSON decision report for every loop step,
capturing project snapshot, selected task, rejected candidates,
safety decisions, outcome, memory constraints, teacher recommendation,
and next action. Stored under `.igris/reports/decisions/`.

Provides query endpoints for retrieving reports.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from igris.core import decision_memory
from igris.core import project_state as project_state_mod
from igris.core.safety import redact_secrets
from igris.core.task_selection_explain import explain_task_selection
from igris.models.config import CONFIG
from igris.models.task import Task, TaskStatus


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class DecisionReport:
    """Structured decision report for a single loop step."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    step_number: int = 0

    # Project snapshot
    project_snapshot: Dict[str, Any] = field(default_factory=dict)

    # Task selection
    selected_task: Optional[Dict[str, Any]] = None
    rejected_candidates: List[Dict[str, Any]] = field(default_factory=list)
    selection_source: str = ""
    selection_summary: str = ""

    # Safety decisions
    safety_decisions: List[Dict[str, Any]] = field(default_factory=list)

    # Outcome
    action_type: str = ""
    action_detail: str = ""
    outcome: str = ""
    outcome_reason: str = ""

    # Memory constraints
    memory_constraints: Dict[str, Any] = field(default_factory=dict)

    # Teacher recommendation
    teacher_recommendation: Optional[Dict[str, Any]] = None

    # Next action
    next_action: str = ""
    next_action_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["action_detail"] = redact_secrets(d.get("action_detail", ""))
        d["outcome_reason"] = redact_secrets(d.get("outcome_reason", ""))
        d["selection_summary"] = redact_secrets(d.get("selection_summary", ""))
        d["next_action_reason"] = redact_secrets(d.get("next_action_reason", ""))
        if d.get("selected_task"):
            for k in ("description", "title", "result"):
                if k in d["selected_task"]:
                    d["selected_task"][k] = redact_secrets(str(d["selected_task"].get(k, "") or ""))
        for rc in d.get("rejected_candidates", []):
            if "title" in rc:
                rc["title"] = redact_secrets(str(rc.get("title", "")))
        return d


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _reports_dir(project_root: Optional[str] = None) -> Path:
    root = Path(project_root) if project_root else CONFIG.project_root
    d = root / ".igris" / "reports" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_decision_report(
    report: DecisionReport,
    project_root: Optional[str] = None,
) -> str:
    """Save a decision report and return its ID."""
    d = _reports_dir(project_root)
    path = d / f"{report.id}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    # Also maintain an index file for quick listing
    index_path = d / "_index.json"
    index: List[Dict[str, str]] = []
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            index = []

    index.append({
        "id": report.id,
        "timestamp": report.timestamp,
        "step_number": report.step_number,
        "outcome": report.outcome,
        "action_type": report.action_type,
    })
    # Keep last 200 entries
    index = index[-200:]
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    return report.id


def get_decision_report(
    report_id: str,
    project_root: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a specific decision report by ID."""
    d = _reports_dir(project_root)
    path = d / f"{report_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, TypeError):
        return None


def list_decision_reports(
    limit: int = 20,
    project_root: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List recent decision reports (from index)."""
    d = _reports_dir(project_root)
    index_path = d / "_index.json"
    if not index_path.exists():
        return []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        return index[-limit:]
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Report creation helpers
# ---------------------------------------------------------------------------

def create_decision_report(
    step_number: int,
    tasks: List[Task],
    action_type: str = "",
    action_detail: str = "",
    outcome: str = "",
    outcome_reason: str = "",
    teacher_recommendation: Optional[Dict[str, Any]] = None,
    next_action: str = "",
    next_action_reason: str = "",
    safety_decisions: Optional[List[Dict[str, Any]]] = None,
    project_root: Optional[str] = None,
) -> DecisionReport:
    """Create a comprehensive decision report for a loop step."""

    # Project snapshot
    snapshot = _build_project_snapshot(tasks, project_root)

    # Task selection explanation
    pending = [t for t in tasks if t.status == TaskStatus.pending]
    history = [t.description for t in tasks if t.status == TaskStatus.completed]
    selection = explain_task_selection(
        candidate_tasks=tasks,
        history=history,
        project_root=project_root,
    )

    selected = selection.selected
    rejected = [c.to_dict() for c in selection.candidates if not c.selected]

    # Memory constraints
    constraints = decision_memory.explain_memory_constraints(project_root=project_root)

    report = DecisionReport(
        step_number=step_number,
        project_snapshot=snapshot,
        selected_task=selected,
        rejected_candidates=rejected,
        selection_source=selection.selection_source,
        selection_summary=selection.summary,
        safety_decisions=safety_decisions or [],
        action_type=action_type,
        action_detail=action_detail,
        outcome=outcome,
        outcome_reason=outcome_reason,
        memory_constraints=constraints,
        teacher_recommendation=teacher_recommendation,
        next_action=next_action,
        next_action_reason=next_action_reason,
    )

    save_decision_report(report, project_root=project_root)
    return report


def _build_project_snapshot(
    tasks: List[Task],
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a lightweight project snapshot for the report."""
    pending = [t for t in tasks if t.status == TaskStatus.pending]
    running = [t for t in tasks if t.status == TaskStatus.running]
    completed = [t for t in tasks if t.status == TaskStatus.completed]
    blocked = [t for t in tasks if t.status == TaskStatus.blocked]

    # Get project state (cooldowns, recovery)
    state = project_state_mod.get_project_state(project_root=project_root)

    return {
        "task_counts": {
            "total": len(tasks),
            "pending": len(pending),
            "running": len(running),
            "completed": len(completed),
            "blocked": len(blocked),
        },
        "cooling_down_families": state.get("cooling_down", []),
        "critical_families": state.get("critical_families", []),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
