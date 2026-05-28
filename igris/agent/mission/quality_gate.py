from __future__ import annotations

from typing import Dict, List, Set

from igris.agent.mission.mission_schema import Mission


def evaluate_quality_gate(mission: Mission) -> Dict[str, object]:
    gaps: List[str] = []
    req_ids = {req.id for req in mission.requirements}
    checklist_req_ids = {item.linked_requirement for item in mission.checklist}
    if not req_ids:
        gaps.append("No requirements defined")
    missing_req_links = sorted(req_ids - checklist_req_ids)
    if missing_req_links:
        gaps.append(f"Missing checklist links for requirements: {', '.join(missing_req_links)}")

    action_links: Set[str] = set()
    for action in mission.actions:
        action_links.update(action.linked_checklist_ids)
    for item in mission.checklist:
        if item.id not in action_links:
            gaps.append(f"Checklist item without action link: {item.id}")

    successful_actions = {res.action_id for res in mission.execution_results if res.success}
    for action in mission.actions:
        if action.id not in successful_actions:
            gaps.append(f"Action not successfully executed: {action.id}")

    # #824: consume evidence_depth for multi-step missions without introducing
    # full policy hardening (reserved for #825). Multi-step cannot be completed
    # with only shallow/missing evidence.
    is_multi_step = len(mission.checklist) > 1
    if is_multi_step:
        insufficient = [
            res.action_id
            for res in mission.execution_results
            if res.success and res.evidence_depth != "sufficient_evidence"
        ]
        if insufficient:
            gaps.append(
                "Multi-step mission has insufficient action evidence depth: "
                + ", ".join(insufficient)
            )

    score = max(0, 100 - (len(gaps) * 15))
    passed = len(gaps) == 0
    mission.quality_gate_passed = passed
    return {"passed": passed, "score": score, "gaps": gaps}
