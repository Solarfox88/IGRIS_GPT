from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Tuple


@dataclass
class ContractViolation:
    role: str
    action_type: str
    goal_type: str
    reason: str
    timestamp: float


def validate_agent_action(role: str, action_type: str) -> Tuple[bool, str]:
    from igris.core.agent_registry import TOOL_PERMISSIONS
    allowed = TOOL_PERMISSIONS.get(role)
    if allowed is None:
        return True, ""
    if action_type in allowed:
        return True, ""
    return False, f"Role '{role}' is not permitted to execute '{action_type}'"


class AgentCoordinator:
    def __init__(self, project_root: str) -> None:
        self.project_root = project_root

    def check_and_record(self, role: str, action_type: str, goal: str, goal_type: str = "") -> Tuple[bool, str]:
        allowed, reason = validate_agent_action(role, action_type)
        if not allowed:
            _ = ContractViolation(role=role, action_type=action_type, goal_type=goal_type, reason=reason, timestamp=time.time())
            try:
                from igris.core.memory_graph import MemoryGraph
                mg = MemoryGraph(self.project_root)
                mg.add_node("lesson", {"failure_class": "contract_violation", "role": role, "action_type": action_type, "goal_type": goal_type, "reason": reason, "goal_snippet": goal[:120]}, confidence=0.9)
                past = mg.query_lessons_for_failure_class("contract_violation")
                repeat_count = sum(1 for p in past if p.get("content", {}).get("role") == role and p.get("content", {}).get("action_type") == action_type)
                if repeat_count >= 2:
                    from igris.core.agent_registry import ESCALATION_PATH
                    escalation_role = ESCALATION_PATH.get(role, "")
                    if escalation_role:
                        mg.add_node("run_event", {"event_type": "escalation_triggered", "reason": f"Role '{role}' violated contract on '{action_type}' {repeat_count}x", "escalation_to": escalation_role})
            except Exception:
                pass
        return allowed, reason
