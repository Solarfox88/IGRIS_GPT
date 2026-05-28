from __future__ import annotations

from typing import Dict, List

from igris.agent.mission.mission_schema import Mission


def verify_actions(mission: Mission) -> Dict[str, object]:
    failures: List[Dict[str, str]] = []
    shallow_evidence: List[Dict[str, str]] = []
    for result in mission.execution_results:
        if not result.success:
            failures.append(
                {
                    "action_id": result.action_id,
                    "failure_type": "technical_failure",
                    "reason": result.stderr or "unknown error",
                }
            )
        if result.evidence_depth in {"missing_evidence", "shallow_evidence"}:
            shallow_evidence.append(
                {
                    "action_id": result.action_id,
                    "evidence_depth": result.evidence_depth,
                    "evidence": result.evidence,
                }
            )
    return {
        "passed": len(failures) == 0,
        "technical_failures": failures,
        "strategic_failures": [],
        "evidence_summary": {
            "insufficient_evidence_actions": shallow_evidence,
            "sufficient_evidence_actions": [
                result.action_id
                for result in mission.execution_results
                if result.evidence_depth == "sufficient_evidence"
            ],
        },
    }
