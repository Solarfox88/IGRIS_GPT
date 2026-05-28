from __future__ import annotations

from typing import Dict, List, Set, Tuple

from igris.agent.mission.mission_schema import Mission


def _classify_action_evidence(mission: Mission) -> Dict[str, str]:
    by_action: Dict[str, str] = {}
    for result in mission.execution_results:
        by_action[result.action_id] = result.evidence_depth
    return by_action


def _collect_checklist_coverage(
    mission: Mission,
    action_evidence: Dict[str, str],
) -> Tuple[List[str], List[str]]:
    incomplete: List[str] = []
    sufficient: List[str] = []
    for item in mission.checklist:
        linked_actions = [a for a in mission.actions if item.id in a.linked_checklist_ids]
        if not linked_actions:
            incomplete.append(item.id)
            continue
        has_sufficient = any(
            action_evidence.get(action.id) == "sufficient_evidence" for action in linked_actions
        )
        if has_sufficient:
            sufficient.append(item.id)
        else:
            incomplete.append(item.id)
    return sufficient, incomplete


def evaluate_quality_gate(mission: Mission) -> Dict[str, object]:
    gaps: List[str] = []
    reasons: List[str] = []
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

    action_evidence = _classify_action_evidence(mission)
    shallow_or_missing = [
        res.action_id
        for res in mission.execution_results
        if res.success and res.evidence_depth in {"shallow_evidence", "missing_evidence"}
    ]
    missing = [
        res.action_id
        for res in mission.execution_results
        if res.evidence_depth == "missing_evidence"
    ]
    sufficient_steps, incomplete_checklist = _collect_checklist_coverage(mission, action_evidence)

    is_single_step = len(mission.checklist) == 1
    is_multi_step = len(mission.checklist) > 1
    if missing:
        gaps.append("Action(s) with missing evidence depth: " + ", ".join(missing))
        reasons.append("missing_evidence")

    if is_single_step and shallow_or_missing:
        gaps.append("Single-step mission has shallow evidence depth: " + ", ".join(shallow_or_missing))
        reasons.append("shallow_evidence")

    if is_multi_step:
        if shallow_or_missing:
            gaps.append("Multi-step mission has insufficient action evidence depth: " + ", ".join(shallow_or_missing))
            reasons.append("insufficient_multistep_evidence")
        if incomplete_checklist:
            gaps.append(
                "Multi-step mission has incomplete checklist evidence coverage: "
                + ", ".join(incomplete_checklist)
            )
            reasons.append("incomplete_checklist_evidence")

    score = max(0, 100 - (len(gaps) * 15))
    passed = len(gaps) == 0
    mission.quality_gate_passed = passed
    return {
        "passed": passed,
        "score": score,
        "gaps": gaps,
        "reasons": sorted(set(reasons)),
        "evidence_summary": {
            "sufficient_checklist_items": sufficient_steps,
            "incomplete_checklist_items": incomplete_checklist,
            "action_evidence_depth": action_evidence,
        },
    }
