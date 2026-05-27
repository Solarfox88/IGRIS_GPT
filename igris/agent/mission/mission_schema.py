from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class MissionRequirement:
    id: str
    description: str
    verification_method: str
    explicit: bool = True
    status: str = "pending"


@dataclass
class MissionChecklistItem:
    id: str
    description: str
    linked_requirement: str
    status: str = "pending"
    evidence: str = ""


@dataclass
class MissionAction:
    id: str
    description: str
    linked_checklist_ids: List[str] = field(default_factory=list)
    expected_outcome: str = ""
    unsafe: bool = False


@dataclass
class MissionExecutionResult:
    action_id: str
    command: str = ""
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    success: bool = False
    evidence: str = ""


@dataclass
class MissionFinalJudgment:
    technical_status: str = "unknown"
    strategic_status: str = "unknown"
    reason: str = ""


@dataclass
class Mission:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=_now_iso)
    project: str = "igrisgpt"
    user_input: str = ""
    intent_summary: str = "unknown"
    requirements: List[MissionRequirement] = field(default_factory=list)
    plan: List[Dict[str, Any]] = field(default_factory=list)
    checklist: List[MissionChecklistItem] = field(default_factory=list)
    actions: List[MissionAction] = field(default_factory=list)
    execution_results: List[MissionExecutionResult] = field(default_factory=list)
    status: str = "created"
    quality_gate_passed: bool = False
    satisfaction_gate_passed: bool = False
    final_response: str = ""
    final_judgment: MissionFinalJudgment = field(default_factory=MissionFinalJudgment)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    recovery_attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Mission":
        return cls(
            id=str(data.get("id") or str(uuid.uuid4())),
            created_at=str(data.get("created_at") or _now_iso()),
            project=str(data.get("project") or "igrisgpt"),
            user_input=str(data.get("user_input") or ""),
            intent_summary=str(data.get("intent_summary") or "unknown"),
            requirements=[
                MissionRequirement(**item) for item in (data.get("requirements") or [])
            ],
            plan=list(data.get("plan") or []),
            checklist=[
                MissionChecklistItem(**item) for item in (data.get("checklist") or [])
            ],
            actions=[MissionAction(**item) for item in (data.get("actions") or [])],
            execution_results=[
                MissionExecutionResult(**item)
                for item in (data.get("execution_results") or [])
            ],
            status=str(data.get("status") or "created"),
            quality_gate_passed=bool(data.get("quality_gate_passed", False)),
            satisfaction_gate_passed=bool(data.get("satisfaction_gate_passed", False)),
            final_response=str(data.get("final_response") or ""),
            final_judgment=MissionFinalJudgment(**(data.get("final_judgment") or {})),
            context_snapshot=dict(data.get("context_snapshot") or {}),
            recovery_attempts=int(data.get("recovery_attempts") or 0),
        )
