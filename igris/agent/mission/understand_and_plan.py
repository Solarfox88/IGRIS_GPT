from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from igris.agent.mission.mission_schema import (
    Mission,
    MissionChecklistItem,
    MissionRequirement,
)


def _classify_intent(user_input: str) -> str:
    text = user_input.lower()
    if any(k in text for k in ("diagnos", "errore", "bug", "fix")):
        return "diagnosis"
    if any(k in text for k in ("architett", "architecture", "design")):
        return "architecture"
    if any(k in text for k in ("plan", "piano", "roadmap")):
        return "planning"
    if any(k in text for k in ("verify", "verifica", "test", "check")):
        return "verification"
    if any(k in text for k in ("implement", "modifica", "change", "aggiungi")):
        return "code_change"
    return "mixed"


def _extract_unknown_safe_summary(user_input: str) -> str:
    text = " ".join(user_input.strip().split())
    if not text:
        return "unknown"
    return text[:240]


def _verification_method_for_intent(intent_type: str) -> str:
    mapping = {
        "diagnosis": "reproduce_and_confirm_resolution",
        "verification": "run_targeted_tests",
        "architecture": "review_artifacts_and_constraints",
        "planning": "review_plan_consistency",
        "code_change": "file_diff_and_tests",
        "mixed": "combined_artifact_review",
    }
    return mapping.get(intent_type, "combined_artifact_review")


def _build_requirements(intent_type: str, summary: str, repo_view: Optional[Dict[str, object]]) -> List[MissionRequirement]:
    requirements: List[MissionRequirement] = []
    base_desc = summary if summary != "unknown" else "User intent is partially unknown"
    requirements.append(
        MissionRequirement(
            id="REQ-001",
            description=f"Interpret the request and preserve constraints: {base_desc}",
            verification_method="intent_consistency_check",
            explicit=True,
        )
    )
    requirements.append(
        MissionRequirement(
            id="REQ-002",
            description=f"Produce an executable plan for intent type '{intent_type}'",
            verification_method=_verification_method_for_intent(intent_type),
            explicit=False,
        )
    )
    if repo_view:
        requirements.append(
            MissionRequirement(
                id="REQ-003",
                description="Use available repository view without inventing missing details",
                verification_method="evidence_traceability_check",
                explicit=False,
            )
        )
    return requirements


def _build_plan(intent_type: str, requirements: Iterable[MissionRequirement], simple_request: bool) -> List[Dict[str, str]]:
    req_ids = [req.id for req in requirements]
    if simple_request:
        return [
            {
                "id": "PLAN-001",
                "step": "Apply minimal action set to satisfy the request safely.",
                "why": f"Simple request classified as {intent_type}; avoid bureaucratic overhead.",
                "linked_requirements": ",".join(req_ids),
            }
        ]
    return [
        {
            "id": "PLAN-001",
            "step": "Confirm intent and constraints before execution.",
            "why": "Prevents false-positive completion.",
            "linked_requirements": req_ids[0],
        },
        {
            "id": "PLAN-002",
            "step": "Execute changes or analysis in a verifiable sequence.",
            "why": "Ensures deterministic progress and measurable outcomes.",
            "linked_requirements": req_ids[1] if len(req_ids) > 1 else req_ids[0],
        },
        {
            "id": "PLAN-003",
            "step": "Validate results against requirements and constraints.",
            "why": "Avoids technical success without mission satisfaction.",
            "linked_requirements": ",".join(req_ids),
        },
    ]


def _build_checklist(requirements: Iterable[MissionRequirement], simple_request: bool) -> List[MissionChecklistItem]:
    reqs = list(requirements)
    if simple_request:
        return [
            MissionChecklistItem(
                id="CHK-001",
                description="Primary request outcome is demonstrably completed.",
                linked_requirement=reqs[0].id,
            )
        ]
    items: List[MissionChecklistItem] = []
    for idx, req in enumerate(reqs, start=1):
        items.append(
            MissionChecklistItem(
                id=f"CHK-{idx:03d}",
                description=f"Evidence collected for {req.id}: {req.verification_method}",
                linked_requirement=req.id,
            )
        )
    return items


def understand_and_plan(
    user_input: str,
    project: str,
    repo_view: Optional[Dict[str, object]] = None,
    mission: Optional[Mission] = None,
) -> Mission:
    """Build/augment a mission with deterministic Understand&Plan output."""
    target = mission or Mission(project=project, user_input=user_input)
    target.project = project
    target.user_input = user_input

    intent_type = _classify_intent(user_input)
    summary = _extract_unknown_safe_summary(user_input)
    target.intent_summary = f"[{intent_type}] {summary}"

    simple_request = len(user_input.split()) <= 12 and intent_type in {
        "verification",
        "planning",
        "mixed",
    }
    target.requirements = _build_requirements(intent_type, summary, repo_view)
    target.plan = _build_plan(intent_type, target.requirements, simple_request)
    target.checklist = _build_checklist(target.requirements, simple_request)
    target.status = "understand_planned"
    if repo_view:
        target.context_snapshot["repo_view_keys"] = sorted(repo_view.keys())
    return target
