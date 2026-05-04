"""
Mission Planner for IGRIS_GPT.

Transforms a user mission into a multi-step plan with task graph,
dependencies, and success criteria. Plans are deterministic (no LLM
required). Tasks are materialized into the persistent TaskEngine.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from igris.core.task_engine import TaskEngine
from igris.models.task import Task


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class PlanStep:
    """A single step in a mission plan."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    mission_id: str = ""
    title: str = ""
    description: str = ""
    family: str = "other"
    dependencies: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    status: str = "pending"
    safe_capabilities: List[str] = field(default_factory=list)
    risk: str = "low"
    order: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "mission_id": self.mission_id,
            "title": self.title,
            "description": self.description,
            "family": self.family,
            "dependencies": self.dependencies,
            "success_criteria": self.success_criteria,
            "status": self.status,
            "safe_capabilities": self.safe_capabilities,
            "risk": self.risk,
            "order": self.order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanStep":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            mission_id=data.get("mission_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            family=data.get("family", "other"),
            dependencies=data.get("dependencies", []),
            success_criteria=data.get("success_criteria", []),
            status=data.get("status", "pending"),
            safe_capabilities=data.get("safe_capabilities", []),
            risk=data.get("risk", "low"),
            order=data.get("order", 0),
        )


@dataclass
class Mission:
    """A user mission with plan and status."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    status: str = "created"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    current_task_id: Optional[int] = None
    plan_summary: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    task_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_task_id": self.current_task_id,
            "plan_summary": self.plan_summary,
            "steps": [s.to_dict() for s in self.steps],
            "step_count": len(self.steps),
            "task_ids": self.task_ids,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Mission":
        steps = [PlanStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=data.get("status", "created"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            current_task_id=data.get("current_task_id"),
            plan_summary=data.get("plan_summary", ""),
            steps=steps,
            task_ids=data.get("task_ids", []),
        )


# ---------------------------------------------------------------------------
# Mission persistence
# ---------------------------------------------------------------------------

def _missions_dir(project_root: str = ".") -> Path:
    d = Path(project_root) / ".igris" / "missions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_mission(mission: Mission, project_root: str = ".") -> None:
    fp = _missions_dir(project_root) / f"{mission.id}.json"
    fp.write_text(json.dumps(mission.to_dict(), indent=2), encoding="utf-8")


def load_mission(mission_id: str, project_root: str = ".") -> Optional[Mission]:
    fp = _missions_dir(project_root) / f"{mission_id}.json"
    if not fp.exists():
        return None
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        return Mission.from_dict(data)
    except Exception:
        return None


def list_missions(project_root: str = ".") -> List[Mission]:
    missions: List[Mission] = []
    for fp in sorted(_missions_dir(project_root).glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            missions.append(Mission.from_dict(data))
        except Exception:
            continue
    return missions


# ---------------------------------------------------------------------------
# Deterministic planner
# ---------------------------------------------------------------------------

_FAMILY_MAP = {
    "analyze": ["analyze", "read", "understand", "check", "review", "examine", "inspect", "study", "explore"],
    "test": ["test", "verify", "validate", "assert", "check test", "run test"],
    "code": ["implement", "create", "write code", "add feature", "build", "develop", "coding"],
    "fix": ["fix", "repair", "resolve", "patch", "debug", "correct"],
    "refactor": ["refactor", "restructure", "reorganize", "simplify", "clean"],
    "docs": ["document", "write docs", "update readme", "add docs"],
    "config": ["configure", "setup", "install", "deploy"],
    "git": ["commit", "branch", "merge", "push", "pull request", "pr"],
}


def _classify_family(text: str) -> str:
    lowered = text.lower()
    for family, keywords in _FAMILY_MAP.items():
        for kw in keywords:
            if kw in lowered:
                return family
    return "other"


def _generate_success_criteria(step_title: str, family: str) -> List[str]:
    """Generate reasonable success criteria based on step type."""
    criteria: List[str] = []
    if family == "analyze":
        criteria.append(f"Analysis of '{step_title}' complete with findings documented")
    elif family == "test":
        criteria.append("All tests pass (python -m pytest -q)")
        criteria.append("No regressions introduced")
    elif family == "code":
        criteria.append(f"Implementation of '{step_title}' complete")
        criteria.append("Code compiles/runs without errors")
    elif family == "fix":
        criteria.append(f"Bug fix for '{step_title}' verified")
        criteria.append("Original issue no longer reproducible")
    elif family == "docs":
        criteria.append(f"Documentation for '{step_title}' updated")
    elif family == "git":
        criteria.append("Git operation completed successfully")
    elif family == "config":
        criteria.append("Configuration applied and verified")
    else:
        criteria.append(f"Step '{step_title}' completed successfully")
    return criteria


def generate_plan(mission: Mission) -> List[PlanStep]:
    """Generate a deterministic plan from the mission description.

    The planner breaks the mission into logical steps based on keywords
    and common patterns. This is deterministic (no LLM).
    """
    desc = mission.description.strip()
    steps: List[PlanStep] = []

    lines = [line.strip() for line in desc.split("\n") if line.strip()]
    numbered = [line for line in lines if line and (line[0].isdigit() or line.startswith("- "))]

    if numbered:
        for i, line in enumerate(numbered):
            clean = line.lstrip("0123456789.-) ").strip()
            if not clean:
                continue
            family = _classify_family(clean)
            step = PlanStep(
                mission_id=mission.id,
                title=clean[:120],
                description=clean,
                family=family,
                dependencies=[steps[-1].id] if steps else [],
                success_criteria=_generate_success_criteria(clean[:80], family),
                risk="low",
                order=i,
            )
            steps.append(step)
    else:
        family = _classify_family(desc)
        step_analyze = PlanStep(
            mission_id=mission.id,
            title=f"Analyze: {mission.title}"[:120],
            description=f"Understand requirements for: {desc[:200]}",
            family="analyze",
            success_criteria=["Requirements understood", "Approach documented"],
            risk="low",
            order=0,
        )
        steps.append(step_analyze)

        step_impl = PlanStep(
            mission_id=mission.id,
            title=f"Implement: {mission.title}"[:120],
            description=f"Implement the changes for: {desc[:200]}",
            family=family if family != "analyze" else "code",
            dependencies=[step_analyze.id],
            success_criteria=_generate_success_criteria(mission.title, family),
            safe_capabilities=["read", "write", "patch_propose"],
            risk="low",
            order=1,
        )
        steps.append(step_impl)

        step_test = PlanStep(
            mission_id=mission.id,
            title=f"Test: {mission.title}"[:120],
            description=f"Verify implementation with tests",
            family="test",
            dependencies=[step_impl.id],
            success_criteria=["All tests pass", "No regressions"],
            risk="low",
            order=2,
        )
        steps.append(step_test)

    return steps


def plan_mission(mission_id: str, project_root: str = ".") -> Optional[Mission]:
    """Load a mission, generate its plan, and save."""
    mission = load_mission(mission_id, project_root)
    if not mission:
        return None
    steps = generate_plan(mission)
    mission.steps = steps
    mission.status = "planned"
    mission.plan_summary = f"{len(steps)} steps planned"
    mission.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_mission(mission, project_root)
    return mission


# ---------------------------------------------------------------------------
# Materialize tasks
# ---------------------------------------------------------------------------

def materialize_tasks(
    mission_id: str,
    task_engine: TaskEngine,
    project_root: str = ".",
) -> Optional[Mission]:
    """Convert plan steps into persistent tasks in the TaskEngine."""
    mission = load_mission(mission_id, project_root)
    if not mission:
        return None
    if not mission.steps:
        return None

    existing_titles = {t.title or t.description for t in task_engine.tasks}

    task_ids: List[int] = []
    for step in mission.steps:
        if step.title in existing_titles:
            continue
        task = task_engine.create_task(
            description=step.description,
            title=step.title,
            family=step.family,
            priority=len(mission.steps) - step.order,
            source="mission",
            risk=step.risk,
            success_criteria=step.success_criteria,
        )
        task_ids.append(task.id)

    mission.task_ids.extend(task_ids)
    mission.status = "active"
    mission.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if task_ids:
        mission.current_task_id = task_ids[0]
    save_mission(mission, project_root)
    return mission


# ---------------------------------------------------------------------------
# Graph serialization
# ---------------------------------------------------------------------------

def get_mission_graph(mission_id: str, project_root: str = ".") -> Optional[Dict]:
    """Return a serializable graph representation of the mission plan."""
    mission = load_mission(mission_id, project_root)
    if not mission:
        return None
    nodes = []
    edges = []
    for step in mission.steps:
        nodes.append({
            "id": step.id,
            "title": step.title,
            "family": step.family,
            "status": step.status,
            "order": step.order,
            "risk": step.risk,
        })
        for dep in step.dependencies:
            edges.append({"from": dep, "to": step.id})
    return {
        "mission_id": mission.id,
        "title": mission.title,
        "status": mission.status,
        "nodes": nodes,
        "edges": edges,
    }
