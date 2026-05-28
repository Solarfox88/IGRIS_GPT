"""Recovery Recommendation Taxonomy — EPIC #886 (#887).

Defines the advisory recovery templates for each combined_status produced by the
Goal/Run Status Bridge. All templates are advisory-only; auto_executable is ALWAYS False.
"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Recovery actions
# ---------------------------------------------------------------------------

RECOVERY_CONTINUE_FROM_PARTIAL    = "continue_from_partial_progress"
RECOVERY_DIAGNOSE_FAILURE         = "diagnose_failure"
RECOVERY_REQUEST_CONTEXT          = "request_context"
RECOVERY_MARK_COMPLETE            = "mark_complete"
RECOVERY_INVESTIGATE_ANOMALY      = "investigate_anomaly"
RECOVERY_RETRY_WITH_CONTEXT       = "retry_with_context"
RECOVERY_ESCALATE_BLOCKED         = "escalate_blocked"
RECOVERY_REVIEW_PARTIAL_COMPLETE  = "review_partial_complete"
RECOVERY_AWAIT_CLARIFICATION      = "await_clarification"

RECOVERY_ACTIONS: frozenset = frozenset({
    RECOVERY_CONTINUE_FROM_PARTIAL,
    RECOVERY_DIAGNOSE_FAILURE,
    RECOVERY_REQUEST_CONTEXT,
    RECOVERY_MARK_COMPLETE,
    RECOVERY_INVESTIGATE_ANOMALY,
    RECOVERY_RETRY_WITH_CONTEXT,
    RECOVERY_ESCALATE_BLOCKED,
    RECOVERY_REVIEW_PARTIAL_COMPLETE,
    RECOVERY_AWAIT_CLARIFICATION,
})

# ---------------------------------------------------------------------------
# Confidence levels
# ---------------------------------------------------------------------------

CONFIDENCE_HIGH   = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW    = "low"

CONFIDENCE_LEVELS: frozenset = frozenset({
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
})


class RecoveryTemplate(TypedDict):
    action: str
    confidence: str
    evidence_required: List[str]
    safe_next_action: str
    rationale: str
    auto_executable: bool
    advisory_only: bool


RECOVERY_TEMPLATES: Dict[str, RecoveryTemplate] = {
    "technical_failure_with_goal_progress": {
        "action": RECOVERY_CONTINUE_FROM_PARTIAL,
        "confidence": CONFIDENCE_HIGH,
        "evidence_required": ["mission_brain_decision", "goal_class", "current_loop_decision"],
        "safe_next_action": (
            "Identify which goal sub-tasks completed. "
            "Resume from last successful sub-task. Do NOT restart from scratch."
        ),
        "rationale": (
            "Run failed technically but goal made measurable progress. "
            "Continuing from the partial state avoids redundant work."
        ),
        "auto_executable": False,
        "advisory_only": True,
    },
    "hard_failure": {
        "action": RECOVERY_DIAGNOSE_FAILURE,
        "confidence": CONFIDENCE_HIGH,
        "evidence_required": ["current_loop_decision", "mission_brain_decision"],
        "safe_next_action": (
            "Review error logs to identify root cause. "
            "Determine whether failure is transient (retry) or structural (redesign)."
        ),
        "rationale": (
            "Both run and goal failed. Diagnosis required before any recovery attempt."
        ),
        "auto_executable": False,
        "advisory_only": True,
    },
    "blocked_with_goal_progress": {
        "action": RECOVERY_ESCALATE_BLOCKED,
        "confidence": CONFIDENCE_HIGH,
        "evidence_required": ["current_loop_decision", "mission_brain_decision"],
        "safe_next_action": (
            "Identify and resolve the blocking dependency. "
            "Preserve completed progress before retrying."
        ),
        "rationale": (
            "Run blocked externally but partial progress was made. "
            "Escalating the blocker while preserving progress is safer than a full restart."
        ),
        "auto_executable": False,
        "advisory_only": True,
    },
    "completed": {
        "action": RECOVERY_MARK_COMPLETE,
        "confidence": CONFIDENCE_HIGH,
        "evidence_required": ["current_loop_decision", "mission_brain_decision"],
        "safe_next_action": "Confirm completion criteria are satisfied. Mark goal as complete.",
        "rationale": "Both run and goal report success. No recovery needed; confirm and close.",
        "auto_executable": False,
        "advisory_only": True,
    },
    "insufficient_context": {
        "action": RECOVERY_REQUEST_CONTEXT,
        "confidence": CONFIDENCE_LOW,
        "evidence_required": ["current_loop_decision", "mission_brain_decision", "goal_class"],
        "safe_next_action": (
            "Gather missing context (run logs, goal definition, intermediate outputs) "
            "before attempting any recovery action."
        ),
        "rationale": (
            "Status is undetermined due to missing or conflicting signals. "
            "Acting without context risks incorrect recovery."
        ),
        "auto_executable": False,
        "advisory_only": True,
    },
    "anomaly_run_passed_goal_not_completed": {
        "action": RECOVERY_INVESTIGATE_ANOMALY,
        "confidence": CONFIDENCE_MEDIUM,
        "evidence_required": ["current_loop_decision", "mission_brain_decision", "goal_class"],
        "safe_next_action": (
            "Investigate why the run passed but goal assessment shows incomplete. "
            "Check for evaluation misalignment or scope discrepancy."
        ),
        "rationale": (
            "Run succeeded but goal is not marked complete — anomaly requiring human review."
        ),
        "auto_executable": False,
        "advisory_only": True,
    },
    "run_passed_goal_partial": {
        "action": RECOVERY_REVIEW_PARTIAL_COMPLETE,
        "confidence": CONFIDENCE_MEDIUM,
        "evidence_required": ["current_loop_decision", "mission_brain_decision"],
        "safe_next_action": (
            "Review what sub-tasks are still incomplete. "
            "Determine whether a follow-up run is needed to complete remaining goal steps."
        ),
        "rationale": (
            "Run passed but goal is only partially achieved. "
            "A follow-up run or scope adjustment may be needed."
        ),
        "auto_executable": False,
        "advisory_only": True,
    },
    "blocked_no_goal_progress": {
        "action": RECOVERY_ESCALATE_BLOCKED,
        "confidence": CONFIDENCE_MEDIUM,
        "evidence_required": ["current_loop_decision", "mission_brain_decision"],
        "safe_next_action": (
            "Identify the blocking dependency. Escalate or resolve before retrying. "
            "Consider whether goal should be deprioritized while blocked."
        ),
        "rationale": (
            "Run blocked and goal made no progress. Escalation is required; "
            "retrying without resolving the blocker is wasteful."
        ),
        "auto_executable": False,
        "advisory_only": True,
    },
    "unknown_status": {
        "action": RECOVERY_AWAIT_CLARIFICATION,
        "confidence": CONFIDENCE_LOW,
        "evidence_required": ["current_loop_decision", "mission_brain_decision"],
        "safe_next_action": (
            "Do not act. Await clarification of run and goal status before any recovery step."
        ),
        "rationale": (
            "Status is entirely unknown. Any recovery attempt without clear status risks "
            "incorrect action. Wait for clarification."
        ),
        "auto_executable": False,
        "advisory_only": True,
    },
}


def _validate_taxonomy() -> None:
    """Validate all taxonomy invariants. Raises AssertionError on violation."""
    for status, tmpl in RECOVERY_TEMPLATES.items():
        assert tmpl["auto_executable"] is False, (
            f"INVARIANT VIOLATION: {status}.auto_executable must be False"
        )
        assert tmpl["advisory_only"] is True, (
            f"INVARIANT VIOLATION: {status}.advisory_only must be True"
        )
        assert tmpl["action"] in RECOVERY_ACTIONS, (
            f"INVARIANT VIOLATION: {status}.action={tmpl['action']!r} not in RECOVERY_ACTIONS"
        )
        assert tmpl["confidence"] in CONFIDENCE_LEVELS, (
            f"INVARIANT VIOLATION: {status}.confidence={tmpl['confidence']!r} not valid"
        )
        assert tmpl["safe_next_action"].strip(), (
            f"INVARIANT VIOLATION: {status}.safe_next_action is empty"
        )
        assert isinstance(tmpl["evidence_required"], list), (
            f"INVARIANT VIOLATION: {status}.evidence_required must be a list"
        )


# Enforce at import time
_validate_taxonomy()


def get_template(combined_status: str) -> Optional[RecoveryTemplate]:
    """Return the recovery template for a combined_status, or None if not found."""
    return RECOVERY_TEMPLATES.get(combined_status)


def list_statuses_with_templates() -> List[str]:
    """Return all combined_status values that have a recovery template."""
    return list(RECOVERY_TEMPLATES.keys())
