from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkPhase(str, Enum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    ACT = "act"
    OBSERVE = "observe"
    FIX = "fix"
    VERIFY = "verify"
    DELIVER = "deliver"
    REMEMBER = "remember"


@dataclass
class PhaseRecord:
    phase: WorkPhase
    started_at: float
    completed_at: Optional[float] = None
    outcome: str = ""
    notes: str = ""


@dataclass
class DeliveryReport:
    work_session_id: str
    goal: str
    files_modified: List[str]
    diff_summary: str
    test_output: str
    ci_status: str
    pr_url: str
    pr_number: int
    healthcheck_url: str
    residual_risks: List[str]
    rollback_available: bool
    run_id: str
    last_failure_class: str
    repair_cycles_used: int
    capability_signals: Dict[str, Any]


@dataclass
class WorkSession:
    session_id: str
    goal: str
    mission_id: Optional[str]
    phases: List[PhaseRecord]
    delivery_report: Optional[DeliveryReport]
    created_at: float
    updated_at: float
    status: str

    @classmethod
    def create(cls, goal: str, mission_id: Optional[str] = None) -> "WorkSession":
        now = time.time()
        return cls(uuid.uuid4().hex[:16], goal, mission_id, [], None, now, now, "active")

    def advance_phase(self, phase: WorkPhase, outcome: str = "success", notes: str = "") -> "WorkSession":
        now = time.time()
        for p in reversed(self.phases):
            if p.completed_at is None:
                p.completed_at = now
                p.outcome = outcome
                p.notes = notes
                break
        self.phases.append(PhaseRecord(phase=phase, started_at=now))
        self.updated_at = now
        return self

    def complete_deliver(self, report: DeliveryReport) -> "WorkSession":
        self.delivery_report = report
        self.status = "delivered"
        self.updated_at = time.time()
        return self

    def remember(self, project_root: str) -> None:
        try:
            from igris.core.memory_graph import MemoryGraph
            mg = MemoryGraph(project_root)
            report = self.delivery_report
            mg.add_node("lesson", {"session_id": self.session_id, "goal": self.goal[:200], "files_modified": (report.files_modified if report else []), "outcome": self.status, "ci_status": (report.ci_status if report else "unknown"), "pr_url": (report.pr_url if report else ""), "failure_class": (report.last_failure_class if report else "")}, confidence=0.85)
            mg.add_node("world_state_snapshot", {"session_id": self.session_id, "tests_pass": (report.ci_status == "green" if report else False), "pr_created": bool(report.pr_url if report else False), "ci_status": (report.ci_status if report else "unknown")})
        except Exception:
            pass

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phases"] = [{**p, "phase": p["phase"]} for p in data["phases"]]
        return data

    def to_pr_review_request(self) -> Dict[str, Any]:
        r = self.delivery_report
        if not r:
            raise ValueError("No delivery report — call complete_deliver first")
        return {"pr_number": r.pr_number, "pr_diff": r.diff_summary, "changed_files": r.files_modified, "ci_passed": r.ci_status == "green", "run_id": r.run_id, "last_failure_class": r.last_failure_class, "repair_cycles_used": r.repair_cycles_used, "capability_signals": r.capability_signals}
