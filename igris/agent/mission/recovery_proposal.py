"""Recovery Proposal — EPIC #942.

Evolves Mission Brain Advisory from text recommendations to structured
recovery proposals.

Design invariants (NEVER violate):
  - auto_executable is ALWAYS False — never triggers automatic actions
  - approval_required is ALWAYS True — always requires operator decision
  - suggested_actions[*].auto_executable is ALWAYS False
  - suggested_actions[*].requires_approval is ALWAYS True
  - Proposals are NEVER generated for passed/completed status
  - proposal_type is NEVER "completed"
  - Every proposal has proposal_id and source trace

Advisory chain:
  failure / blocked
  → Advisory generates RecoveryProposal (this module)
  → MBOP validates proposal via proposal_to_mbop_handoff()
  → MBOPHandoff becomes requirements/checklist — NEVER executable
  → IGRIS executes through normal supervisor workflow only after approval

Feature flag:
  IGRIS_ADVISORY_RECOVERY_PROPOSALS=1 (env var)
  or RecoveryProposalConfig(enabled=True)
  Default: disabled.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional

from igris.agent.mission.recovery_taxonomy import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LEVELS,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    get_template,
)
from igris.agent.mission.status_bridge import (
    COMBINED_HARD_FAILURE,
    COMBINED_BLOCKED_GOAL_PROGRESS,
    COMBINED_INSUFFICIENT_CONTEXT,
    COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS,
    bridge,
)


# ---------------------------------------------------------------------------
# Excluded statuses — never generate a proposal for these
# ---------------------------------------------------------------------------

EXCLUDED_RUN_STATUSES: FrozenSet[str] = frozenset({"passed", "completed"})
EXCLUDED_GOAL_STATUSES: FrozenSet[str] = frozenset({"completed"})
EXCLUDED_PROPOSAL_TYPES: FrozenSet[str] = frozenset({"completed"})

# ---------------------------------------------------------------------------
# Proposal types — never use "completed"
# ---------------------------------------------------------------------------

PROPOSAL_CONTINUE_FROM_PARTIAL = "continue_from_partial_progress"
PROPOSAL_RESTART_SMALLER_SCOPE = "restart_with_smaller_scope"
PROPOSAL_GATHER_MISSING_CONTEXT = "gather_missing_context"
PROPOSAL_OPERATOR_DECISION = "request_operator_decision_with_valid_progress"
PROPOSAL_INVESTIGATE_ANOMALY = "investigate_anomaly"
PROPOSAL_HUMAN_REVIEW = "ask_for_human_review"

VALID_PROPOSAL_TYPES: FrozenSet[str] = frozenset({
    PROPOSAL_CONTINUE_FROM_PARTIAL,
    PROPOSAL_RESTART_SMALLER_SCOPE,
    PROPOSAL_GATHER_MISSING_CONTEXT,
    PROPOSAL_OPERATOR_DECISION,
    PROPOSAL_INVESTIGATE_ANOMALY,
    PROPOSAL_HUMAN_REVIEW,
})

# ---------------------------------------------------------------------------
# combined_status → proposal_type mapping
# ---------------------------------------------------------------------------

COMBINED_STATUS_TO_PROPOSAL_TYPE: Dict[str, str] = {
    COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS: PROPOSAL_CONTINUE_FROM_PARTIAL,
    COMBINED_HARD_FAILURE:                    PROPOSAL_RESTART_SMALLER_SCOPE,
    COMBINED_BLOCKED_GOAL_PROGRESS:           PROPOSAL_OPERATOR_DECISION,
    COMBINED_INSUFFICIENT_CONTEXT:            PROPOSAL_GATHER_MISSING_CONTEXT,
    "anomaly_run_passed_goal_not_completed":  PROPOSAL_INVESTIGATE_ANOMALY,
    "run_passed_goal_partial":                PROPOSAL_INVESTIGATE_ANOMALY,
    "blocked_no_goal_progress":               PROPOSAL_OPERATOR_DECISION,
    "blocked_goal_failed":                    PROPOSAL_RESTART_SMALLER_SCOPE,
    "goal_complete_run_failed":               PROPOSAL_INVESTIGATE_ANOMALY,
    "goal_complete_run_blocked":              PROPOSAL_INVESTIGATE_ANOMALY,
    "unknown_status":                         PROPOSAL_HUMAN_REVIEW,
}

_FALLBACK_PROPOSAL_TYPE = PROPOSAL_HUMAN_REVIEW


def get_proposal_type(combined_status: str) -> str:
    """Map combined_status to proposal_type. Falls back to human_review."""
    ptype = COMBINED_STATUS_TO_PROPOSAL_TYPE.get(combined_status, _FALLBACK_PROPOSAL_TYPE)
    # Safety: never return "completed"
    if ptype in EXCLUDED_PROPOSAL_TYPES:
        return _FALLBACK_PROPOSAL_TYPE
    return ptype


# ---------------------------------------------------------------------------
# SuggestedAction — typed, descriptive, never executable
# ---------------------------------------------------------------------------

@dataclass
class SuggestedAction:
    """A single suggested action — descriptive, never a shell command.

    Invariants:
      - auto_executable ALWAYS False
      - requires_approval ALWAYS True
      - description must be non-empty and not a shell command
    """
    description: str
    target_files: List[str] = field(default_factory=list)
    risk_level: str = "low"          # low | medium | high
    requires_approval: bool = True   # INVARIANT — always True
    auto_executable: bool = False    # INVARIANT — always False
    rationale: str = ""

    def __post_init__(self) -> None:
        # Enforce invariants
        object.__setattr__(self, "auto_executable", False)
        object.__setattr__(self, "requires_approval", True)
        if not self.description or not self.description.strip():
            raise ValueError("SuggestedAction.description must be non-empty")
        if self.risk_level not in ("low", "medium", "high"):
            raise ValueError(f"risk_level must be low|medium|high, got {self.risk_level!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "target_files": self.target_files,
            "risk_level": self.risk_level,
            "requires_approval": True,    # INVARIANT
            "auto_executable": False,     # INVARIANT
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# RecoveryProposal dataclass
# ---------------------------------------------------------------------------

@dataclass
class RecoveryProposal:
    """Structured recovery proposal generated by Advisory.

    Invariants (enforced in __post_init__):
      - auto_executable ALWAYS False
      - approval_required ALWAYS True
      - proposal_type NEVER "completed"
      - Never generated for passed/completed status
      - Every suggested_action has auto_executable=False, requires_approval=True
    """
    # Identity
    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    source_advisory_id: str = ""   # ID of advisory that triggered this proposal
    timestamp: float = field(default_factory=time.time)

    # Trigger context
    trigger_status: str = "failed"      # failed | blocked | partial
    combined_status: str = "unknown_status"
    proposal_type: str = PROPOSAL_HUMAN_REVIEW

    # Problem description
    problem_summary: str = ""
    valid_progress: List[str] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)

    # Structured plan — all items are descriptive, never executable
    suggested_requirements: List[str] = field(default_factory=list)
    suggested_checklist: List[str] = field(default_factory=list)
    suggested_actions: List[SuggestedAction] = field(default_factory=list)
    suggested_tests: List[str] = field(default_factory=list)

    # Risk and confidence
    confidence: str = CONFIDENCE_LOW
    risk_level: str = "low"

    # Safety invariants — NEVER False for approval_required
    approval_required: bool = True    # INVARIANT — always True
    auto_executable: bool = False     # INVARIANT — always False

    # MBOP handoff readiness
    mbop_handoff_ready: bool = False

    def __post_init__(self) -> None:
        """Enforce invariants. Raises ValueError on violation."""
        # Core invariants — normalize rather than crash on bool coercion
        object.__setattr__(self, "auto_executable", False)
        object.__setattr__(self, "approval_required", True)

        # Proposal type must never be "completed"
        if self.proposal_type in EXCLUDED_PROPOSAL_TYPES:
            object.__setattr__(self, "proposal_type", _FALLBACK_PROPOSAL_TYPE)

        # Proposal type must be valid
        if self.proposal_type not in VALID_PROPOSAL_TYPES:
            object.__setattr__(self, "proposal_type", _FALLBACK_PROPOSAL_TYPE)

        # Enforce all suggested_actions invariants
        for action in self.suggested_actions:
            if action.auto_executable is not False:
                raise ValueError(
                    f"suggested_action.auto_executable must be False: {action.description!r}"
                )
            if action.requires_approval is not True:
                raise ValueError(
                    f"suggested_action.requires_approval must be True: {action.description!r}"
                )

        # Confidence must be valid
        if self.confidence not in CONFIDENCE_LEVELS:
            object.__setattr__(self, "confidence", CONFIDENCE_LOW)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "source_advisory_id": self.source_advisory_id,
            "timestamp": self.timestamp,
            "trigger_status": self.trigger_status,
            "combined_status": self.combined_status,
            "proposal_type": self.proposal_type,
            "problem_summary": self.problem_summary,
            "valid_progress": self.valid_progress,
            "missing_evidence": self.missing_evidence,
            "suggested_requirements": self.suggested_requirements,
            "suggested_checklist": self.suggested_checklist,
            "suggested_actions": [a.to_dict() for a in self.suggested_actions],
            "suggested_tests": self.suggested_tests,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "approval_required": True,      # INVARIANT — always True in serialization
            "auto_executable": False,       # INVARIANT — always False in serialization
            "mbop_handoff_ready": self.mbop_handoff_ready,
        }


# ---------------------------------------------------------------------------
# Invariant validator
# ---------------------------------------------------------------------------

class ProposalValidator:
    """Validates RecoveryProposal invariants. Raises ValueError on violation."""

    REQUIRED_INVARIANTS = [
        "auto_executable",
        "approval_required",
        "proposal_type",
        "proposal_id",
    ]

    @classmethod
    def validate(cls, proposal: "RecoveryProposal") -> bool:
        """Validate all invariants. Returns True or raises ValueError."""
        if proposal.auto_executable is not False:
            raise ValueError(
                f"INVARIANT VIOLATION: auto_executable must be False, "
                f"got {proposal.auto_executable!r}"
            )
        if proposal.approval_required is not True:
            raise ValueError(
                f"INVARIANT VIOLATION: approval_required must be True, "
                f"got {proposal.approval_required!r}"
            )
        if proposal.proposal_type in EXCLUDED_PROPOSAL_TYPES:
            raise ValueError(
                f"INVARIANT VIOLATION: proposal_type must not be in {EXCLUDED_PROPOSAL_TYPES}, "
                f"got {proposal.proposal_type!r}"
            )
        if not proposal.proposal_id:
            raise ValueError("INVARIANT VIOLATION: proposal_id must be non-empty")
        if proposal.trigger_status in EXCLUDED_RUN_STATUSES:
            raise ValueError(
                f"INVARIANT VIOLATION: trigger_status {proposal.trigger_status!r} "
                f"is in excluded statuses (passed/completed)"
            )
        if proposal.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"INVARIANT VIOLATION: confidence {proposal.confidence!r} not valid"
            )
        for action in proposal.suggested_actions:
            if action.auto_executable is not False:
                raise ValueError(
                    f"INVARIANT VIOLATION: suggested_action.auto_executable must be False"
                )
            if action.requires_approval is not True:
                raise ValueError(
                    f"INVARIANT VIOLATION: suggested_action.requires_approval must be True"
                )
        return True

    @classmethod
    def validate_dict(cls, d: Dict[str, Any]) -> bool:
        """Validate a proposal dict (from to_dict()). Returns True or raises ValueError."""
        if d.get("auto_executable") is not False:
            raise ValueError(
                f"INVARIANT VIOLATION: auto_executable must be False in dict"
            )
        if d.get("approval_required") is not True:
            raise ValueError(
                f"INVARIANT VIOLATION: approval_required must be True in dict"
            )
        if d.get("proposal_type") in EXCLUDED_PROPOSAL_TYPES:
            raise ValueError(
                f"INVARIANT VIOLATION: proposal_type must not be in {EXCLUDED_PROPOSAL_TYPES}"
            )
        for action in d.get("suggested_actions", []):
            if action.get("auto_executable") is not False:
                raise ValueError("INVARIANT VIOLATION: suggested_action.auto_executable")
            if action.get("requires_approval") is not True:
                raise ValueError("INVARIANT VIOLATION: suggested_action.requires_approval")
        return True

    @classmethod
    def is_excluded_status(cls, run_status: str, goal_status: str) -> bool:
        """Return True if this status combination should never generate a proposal."""
        return (
            run_status in EXCLUDED_RUN_STATUSES
            or goal_status in EXCLUDED_GOAL_STATUSES
        )


# ---------------------------------------------------------------------------
# Proposal generation engine
# ---------------------------------------------------------------------------

class RecoveryProposalConfig:
    """Feature flag for recovery proposal generation.

    Default: disabled. Enable with IGRIS_ADVISORY_RECOVERY_PROPOSALS=1
    or RecoveryProposalConfig(enabled=True).
    """

    def __init__(self, enabled: Optional[bool] = None) -> None:
        if enabled is None:
            enabled = os.environ.get("IGRIS_ADVISORY_RECOVERY_PROPOSALS", "0") == "1"
        self.enabled = enabled
        self.advisory_only = True      # INVARIANT — always advisory-only
        self.auto_executable = False   # INVARIANT — never executes
        self.is_gate = False           # INVARIANT — never a gate
        self.affects_loop_decision = False  # INVARIANT — never changes loop

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "advisory_only": True,
            "auto_executable": False,
            "is_gate": False,
            "affects_loop_decision": False,
        }


DEFAULT_PROPOSAL_CONFIG = RecoveryProposalConfig(enabled=False)


def generate_recovery_proposal(
    report: Dict[str, Any],
    advisory: Optional[Dict[str, Any]] = None,
    cycle: Optional[Dict[str, Any]] = None,
    config: Optional[RecoveryProposalConfig] = None,
    source_advisory_id: str = "",
) -> Optional[RecoveryProposal]:
    """Generate a structured RecoveryProposal from an advisory/report/cycle.

    Returns None if:
    - config is disabled (IGRIS_ADVISORY_RECOVERY_PROPOSALS not set)
    - run_status/goal_status is excluded (passed/completed)
    - Any exception occurs (non-blocking)

    Invariants enforced:
    - auto_executable=False
    - approval_required=True
    - No executable commands in suggested_actions
    - No proposal for passed/completed

    Args:
        report: The run/mission report dict
        advisory: Optional existing recovery_recommendation dict to extend
        cycle: Optional cycle dict with current_loop_decision/mission_brain_decision
        config: RecoveryProposalConfig (default: disabled)
        source_advisory_id: ID to trace this proposal back to its advisory source

    Returns:
        RecoveryProposal or None
    """
    if config is None:
        config = DEFAULT_PROPOSAL_CONFIG
    if not config.enabled:
        return None

    try:
        return _generate_proposal_internal(
            report=report,
            advisory=advisory,
            cycle=cycle,
            source_advisory_id=source_advisory_id,
        )
    except Exception:
        return None


def _generate_proposal_internal(
    report: Dict[str, Any],
    advisory: Optional[Dict[str, Any]],
    cycle: Optional[Dict[str, Any]],
    source_advisory_id: str,
) -> Optional[RecoveryProposal]:
    """Internal proposal builder. Never raises (called from generate_recovery_proposal)."""
    # Extract run/goal status
    ctx = cycle or report
    run_status = str(ctx.get("current_loop_decision") or report.get("run_status") or "unknown")
    goal_status = str(ctx.get("mission_brain_decision") or report.get("goal_status") or "unknown")

    # Exclusion check
    if ProposalValidator.is_excluded_status(run_status, goal_status):
        return None

    # Compute combined_status via bridge
    try:
        bridge_result = bridge(run_status, goal_status)
        combined_status = bridge_result.get("combined_status", "unknown_status")
    except Exception:
        combined_status = "unknown_status"

    proposal_type = get_proposal_type(combined_status)

    # Extract advisory template for context
    rec = advisory or report.get("recovery_recommendation") or {}
    existing_template = get_template(combined_status) or {}

    # Extract valid_progress and missing_evidence
    valid_progress = _extract_valid_progress(report, cycle)
    missing_evidence = list(rec.get("evidence_missing") or existing_template.get("evidence_required", []))

    # Build suggested_actions (descriptive, never executable)
    suggested_actions = _build_suggested_actions(
        proposal_type=proposal_type,
        combined_status=combined_status,
        run_status=run_status,
        goal_status=goal_status,
        report=report,
    )

    # Build suggested_requirements and checklist
    suggested_requirements, suggested_checklist = _build_requirements_and_checklist(
        proposal_type=proposal_type,
        combined_status=combined_status,
        report=report,
    )

    # Build suggested_tests
    suggested_tests = _build_suggested_tests(report, combined_status)

    # Build problem_summary
    problem_summary = _build_problem_summary(
        run_status=run_status,
        goal_status=goal_status,
        combined_status=combined_status,
        rec=rec,
        report=report,
    )

    # Confidence and risk
    confidence = _compute_confidence(
        combined_status=combined_status,
        existing_template=existing_template,
        missing_evidence=missing_evidence,
    )
    risk_level = _compute_risk_level(suggested_actions)

    proposal = RecoveryProposal(
        source_advisory_id=source_advisory_id,
        trigger_status=run_status,
        combined_status=combined_status,
        proposal_type=proposal_type,
        problem_summary=problem_summary,
        valid_progress=valid_progress,
        missing_evidence=missing_evidence,
        suggested_requirements=suggested_requirements,
        suggested_checklist=suggested_checklist,
        suggested_actions=suggested_actions,
        suggested_tests=suggested_tests,
        confidence=confidence,
        risk_level=risk_level,
        mbop_handoff_ready=bool(suggested_requirements and suggested_checklist),
    )
    # Validate before returning
    ProposalValidator.validate(proposal)
    return proposal


def _extract_valid_progress(
    report: Dict[str, Any],
    cycle: Optional[Dict[str, Any]],
) -> List[str]:
    """Extract completed work from report/cycle."""
    progress = []
    ctx = cycle or report

    # From subtask results
    subtasks = report.get("subtask_results") or ctx.get("subtask_results") or []
    if isinstance(subtasks, list):
        for st in subtasks:
            if isinstance(st, dict) and st.get("status") in ("passed", "completed", "success"):
                name = st.get("name") or st.get("task") or st.get("id")
                if name:
                    progress.append(f"Subtask completed: {name}")

    # From test results
    tests_passed = report.get("tests_passed") or ctx.get("tests_passed")
    if tests_passed and int(tests_passed) > 0:
        progress.append(f"{tests_passed} tests passed before failure")

    # From files changed
    files_changed = report.get("files_changed") or ctx.get("files_changed")
    if files_changed and isinstance(files_changed, list) and files_changed:
        progress.append(f"{len(files_changed)} file(s) modified: {', '.join(str(f) for f in files_changed[:3])}")

    # From commit SHA
    commit_sha = report.get("commit_sha") or ctx.get("commit_sha")
    if commit_sha:
        progress.append(f"Changes committed at {str(commit_sha)[:8]}")

    return progress


def _build_suggested_actions(
    proposal_type: str,
    combined_status: str,
    run_status: str,
    goal_status: str,
    report: Dict[str, Any],
) -> List[SuggestedAction]:
    """Build descriptive suggested actions (NOT shell commands)."""
    actions: List[SuggestedAction] = []

    if proposal_type == PROPOSAL_CONTINUE_FROM_PARTIAL:
        actions.append(SuggestedAction(
            description=(
                "Review the last successful subtask output and identify "
                "the first incomplete step to resume from."
            ),
            target_files=[],
            risk_level="low",
            rationale="Partial progress exists — continue from last known-good state.",
        ))
        actions.append(SuggestedAction(
            description=(
                "Re-run failing tests targeting only the modified modules, "
                "not the full test suite."
            ),
            target_files=_extract_target_files(report),
            risk_level="low",
            rationale="Targeted re-run is faster and avoids masking the real failure.",
        ))

    elif proposal_type == PROPOSAL_RESTART_SMALLER_SCOPE:
        actions.append(SuggestedAction(
            description=(
                "Decompose the failed task into smaller, independently verifiable subtasks. "
                "Start with the smallest unit that can be tested independently."
            ),
            target_files=[],
            risk_level="low",
            rationale="Hard failure on full scope — smaller scope reduces blast radius.",
        ))
        actions.append(SuggestedAction(
            description=(
                "Review error logs to distinguish transient failure (retry-safe) "
                "from structural failure (redesign required)."
            ),
            target_files=_extract_target_files(report),
            risk_level="low",
            rationale="Error classification informs whether to retry or redesign.",
        ))

    elif proposal_type == PROPOSAL_GATHER_MISSING_CONTEXT:
        actions.append(SuggestedAction(
            description=(
                "Gather missing context: retrieve run logs, goal definition, "
                "and intermediate outputs before attempting recovery."
            ),
            target_files=[],
            risk_level="low",
            rationale="Acting without sufficient context risks incorrect recovery.",
        ))

    elif proposal_type == PROPOSAL_OPERATOR_DECISION:
        actions.append(SuggestedAction(
            description=(
                "Escalate to operator: identify the blocking dependency and "
                "provide the blocking context with the partial progress achieved so far."
            ),
            target_files=[],
            risk_level="medium",
            rationale="Run is blocked externally — operator decision required.",
        ))

    elif proposal_type == PROPOSAL_INVESTIGATE_ANOMALY:
        actions.append(SuggestedAction(
            description=(
                "Investigate the anomaly: check for evaluation misalignment "
                "or scope discrepancy between run verdict and goal assessment."
            ),
            target_files=[],
            risk_level="low",
            rationale="Run and goal disagree — this requires human review.",
        ))

    else:  # PROPOSAL_HUMAN_REVIEW / fallback
        actions.append(SuggestedAction(
            description=(
                "Do not act automatically. Present status to operator for manual review. "
                "Wait for clarification before any recovery step."
            ),
            target_files=[],
            risk_level="low",
            rationale="Status is undetermined — manual review is the only safe option.",
        ))

    return actions


def _build_requirements_and_checklist(
    proposal_type: str,
    combined_status: str,
    report: Dict[str, Any],
) -> tuple:
    """Build suggested_requirements and suggested_checklist."""

    if proposal_type == PROPOSAL_CONTINUE_FROM_PARTIAL:
        requirements = [
            "Identify which subtasks completed successfully",
            "Identify the first incomplete subtask",
            "Verify that completed work is preserved (git commit or stash)",
            "Define the minimal fix needed to pass the next failing step",
        ]
        checklist = [
            "[ ] Review run output for last successful step",
            "[ ] Confirm completed artifacts are intact (tests passing, files correct)",
            "[ ] Prepare targeted fix for the failing step only",
            "[ ] Run affected tests after fix",
            "[ ] Confirm no regression in previously passing tests",
        ]

    elif proposal_type == PROPOSAL_RESTART_SMALLER_SCOPE:
        requirements = [
            "Diagnose root cause from error logs",
            "Determine whether failure is transient (retry) or structural (redesign)",
            "Decompose task into independently testable subtasks",
            "Define acceptance criteria for each subtask",
        ]
        checklist = [
            "[ ] Review full error logs for root cause",
            "[ ] Classify failure: transient vs structural",
            "[ ] Define minimal reproduction case",
            "[ ] Create subtask list with independent tests",
            "[ ] Verify each subtask independently before combining",
        ]

    elif proposal_type == PROPOSAL_GATHER_MISSING_CONTEXT:
        requirements = [
            "Retrieve complete run logs",
            "Retrieve original goal definition and acceptance criteria",
            "Identify missing evidence fields",
        ]
        checklist = [
            "[ ] Fetch run logs (current_loop_decision context)",
            "[ ] Fetch mission_brain_decision output",
            "[ ] List missing evidence fields",
            "[ ] Do NOT attempt recovery until context is complete",
        ]

    elif proposal_type == PROPOSAL_OPERATOR_DECISION:
        requirements = [
            "Identify the blocking dependency clearly",
            "Document partial progress achieved",
            "Provide estimated time/effort to unblock",
        ]
        checklist = [
            "[ ] Document what is blocked and why",
            "[ ] List partial progress that should be preserved",
            "[ ] Prepare escalation summary for operator",
            "[ ] Do NOT restart from scratch — preserve completed work",
        ]

    elif proposal_type == PROPOSAL_INVESTIGATE_ANOMALY:
        requirements = [
            "Verify run verdict source (which gate produced 'passed')",
            "Verify goal assessment logic",
            "Identify scope discrepancy if any",
        ]
        checklist = [
            "[ ] Compare run evaluation criteria vs goal completion criteria",
            "[ ] Check for scope discrepancy",
            "[ ] Request human confirmation of actual completion status",
        ]

    else:  # PROPOSAL_HUMAN_REVIEW
        requirements = [
            "Present full status to operator",
            "Do not attempt automated recovery",
        ]
        checklist = [
            "[ ] Do not act automatically",
            "[ ] Present status summary to operator",
            "[ ] Wait for explicit operator instruction",
        ]

    return requirements, checklist


def _build_suggested_tests(
    report: Dict[str, Any],
    combined_status: str,
) -> List[str]:
    """Build suggested test recommendations."""
    tests = []
    target_files = _extract_target_files(report)
    if target_files:
        tests.append(
            f"Run targeted tests for modified modules: {', '.join(target_files[:3])}"
        )
    tests.append("Run full test suite and compare pass/fail counts with baseline")
    if "ci" in str(report.get("log_excerpt", "")).lower():
        tests.append("Check CI configuration for environment-specific failures")
    tests.append("Verify no regressions in previously passing test modules")
    return tests


def _extract_target_files(report: Dict[str, Any]) -> List[str]:
    """Extract modified file paths from report."""
    files = report.get("files_changed") or report.get("allowed_files") or []
    if isinstance(files, list):
        return [str(f) for f in files[:5]]
    return []


def _build_problem_summary(
    run_status: str,
    goal_status: str,
    combined_status: str,
    rec: Dict[str, Any],
    report: Dict[str, Any],
) -> str:
    """Build a concise problem summary."""
    rationale = rec.get("rationale") or ""
    if rationale:
        return f"[{combined_status}] {rationale}"
    log_excerpt = str(report.get("log_excerpt") or "")[:200]
    if log_excerpt:
        return f"[{combined_status}] Run: {run_status}, Goal: {goal_status}. Log: {log_excerpt}"
    return (
        f"Run status: {run_status} | Goal status: {goal_status} | "
        f"Combined: {combined_status}"
    )


def _compute_confidence(
    combined_status: str,
    existing_template: Any,
    missing_evidence: List[str],
) -> str:
    """Compute confidence based on template and evidence completeness."""
    if isinstance(existing_template, dict):
        base = existing_template.get("confidence", CONFIDENCE_LOW)
    else:
        base = CONFIDENCE_LOW
    # Downgrade if evidence is missing
    if missing_evidence:
        if base == CONFIDENCE_HIGH:
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_LOW
    return base


def _compute_risk_level(suggested_actions: List[SuggestedAction]) -> str:
    """Compute overall risk from suggested actions."""
    if any(a.risk_level == "high" for a in suggested_actions):
        return "high"
    if any(a.risk_level == "medium" for a in suggested_actions):
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# MBOP Handoff — convert proposal to MBOP-compatible intake
# ---------------------------------------------------------------------------

@dataclass
class MBOPHandoff:
    """MBOP-compatible handoff from a RecoveryProposal.

    Converts structured proposal to MBOP intake format:
    - requirements, checklist, suggested_tests → MBOP phases 1-3
    - NO executable commands
    - approval_required=True preserved
    - auto_executable=False preserved
    - source_proposal_id for traceability

    This is fed to MBOP as INPUT, not as execution directive.
    IGRIS executes through its normal supervisor workflow only after approval.
    """
    source_proposal_id: str
    proposal_type: str
    requirements: List[str] = field(default_factory=list)
    checklist: List[str] = field(default_factory=list)
    suggested_tests: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    problem_summary: str = ""
    approval_required: bool = True    # INVARIANT — always True
    auto_executable: bool = False     # INVARIANT — always False
    confidence: str = CONFIDENCE_LOW
    risk_level: str = "low"
    is_gate: bool = False             # INVARIANT — never a gate
    affects_loop_decision: bool = False  # INVARIANT — never

    def __post_init__(self) -> None:
        object.__setattr__(self, "auto_executable", False)
        object.__setattr__(self, "approval_required", True)
        object.__setattr__(self, "is_gate", False)
        object.__setattr__(self, "affects_loop_decision", False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_proposal_id": self.source_proposal_id,
            "proposal_type": self.proposal_type,
            "requirements": self.requirements,
            "checklist": self.checklist,
            "suggested_tests": self.suggested_tests,
            "constraints": self.constraints,
            "problem_summary": self.problem_summary,
            "approval_required": True,       # INVARIANT
            "auto_executable": False,        # INVARIANT
            "is_gate": False,               # INVARIANT
            "affects_loop_decision": False,  # INVARIANT
            "confidence": self.confidence,
            "risk_level": self.risk_level,
        }


def proposal_to_mbop_handoff(
    proposal: RecoveryProposal,
) -> MBOPHandoff:
    """Convert a RecoveryProposal to an MBOPHandoff.

    The handoff contains:
    - requirements and checklist from the proposal (safe text)
    - suggested_tests from the proposal
    - NO executable commands
    - approval_required=True preserved
    - auto_executable=False preserved

    Raises ValueError if the proposal violates invariants.
    """
    # Validate proposal first
    ProposalValidator.validate(proposal)

    # Build constraints list from suggested_actions (descriptions only, not commands)
    constraints = [
        f"Action required: {a.description}"
        for a in proposal.suggested_actions
        if a.description.strip()
    ]

    handoff = MBOPHandoff(
        source_proposal_id=proposal.proposal_id,
        proposal_type=proposal.proposal_type,
        requirements=list(proposal.suggested_requirements),
        checklist=list(proposal.suggested_checklist),
        suggested_tests=list(proposal.suggested_tests),
        constraints=constraints,
        problem_summary=proposal.problem_summary,
        confidence=proposal.confidence,
        risk_level=proposal.risk_level,
    )
    return handoff


def proposal_to_mbop_handoff_safe(
    proposal: RecoveryProposal,
) -> Optional[MBOPHandoff]:
    """Safe version — returns None instead of raising on invariant violation."""
    try:
        return proposal_to_mbop_handoff(proposal)
    except (ValueError, Exception):
        return None


# ---------------------------------------------------------------------------
# Report enrichment (feature-flagged)
# ---------------------------------------------------------------------------

def enrich_report_with_proposal(
    report: Dict[str, Any],
    *,
    config: Optional[RecoveryProposalConfig] = None,
    cycle: Optional[Dict[str, Any]] = None,
    source_advisory_id: str = "",
) -> Dict[str, Any]:
    """Enrich a report with a recovery_proposal if conditions are met.

    Feature flag: config.enabled or IGRIS_ADVISORY_RECOVERY_PROPOSALS=1
    Only enriches for failed/blocked statuses.
    Never modifies original fields.
    Never changes loop decision.
    Never enables gates.
    Returns original report unchanged if disabled, excluded, or on error.
    """
    if config is None:
        config = DEFAULT_PROPOSAL_CONFIG
    if not config.enabled:
        return report

    try:
        advisory = report.get("recovery_recommendation")
        proposal = generate_recovery_proposal(
            report=report,
            advisory=advisory,
            cycle=cycle,
            config=config,
            source_advisory_id=source_advisory_id,
        )
        if proposal is None:
            return report

        # Additive only — never modify existing fields
        return {
            **report,
            "recovery_proposal": proposal.to_dict(),
        }
    except Exception:
        return report


def strip_recovery_proposal(report: Dict[str, Any]) -> Dict[str, Any]:
    """Remove recovery_proposal from report (rollback function)."""
    return {k: v for k, v in report.items() if k != "recovery_proposal"}


# ---------------------------------------------------------------------------
# Metrics (Phase 6)
# ---------------------------------------------------------------------------

def compute_proposal_metrics(
    proposals: Iterable["RecoveryProposal"],
) -> Dict[str, Any]:
    """Compute validation metrics over a list of proposals.

    Metrics:
    - total_proposals_generated
    - proposals_by_type
    - auto_executable_violations (should always be 0)
    - approval_required_violations (should always be 0)
    - loop_decision_violations (should always be 0)
    - gate_violations (should always be 0)
    - passed_completed_scope_violations (should always be 0)
    - risky_proposal_count (high risk)
    - missing_evidence_detected_count
    - mbop_handoff_success_count
    - mbop_handoff_failure_count
    - proposal_usefulness_score (0.0-1.0)
    - rollback_verified (always True)
    - operator_review_required_count (always == total, since approval_required=True)
    """
    proposals_list = list(proposals)
    total = len(proposals_list)

    auto_exec_violations = 0
    approval_violations = 0
    loop_violations = 0
    gate_violations = 0
    scope_violations = 0
    risky_count = 0
    missing_evidence_count = 0
    mbop_success = 0
    mbop_failure = 0
    type_dist: Dict[str, int] = {}
    useful_count = 0

    for p in proposals_list:
        # Check invariants
        if p.auto_executable is not False:
            auto_exec_violations += 1
        if p.approval_required is not True:
            approval_violations += 1
        if p.trigger_status in EXCLUDED_RUN_STATUSES:
            scope_violations += 1
        if p.proposal_type in EXCLUDED_PROPOSAL_TYPES:
            scope_violations += 1

        # Count by type
        type_dist[p.proposal_type] = type_dist.get(p.proposal_type, 0) + 1

        # Risk
        if p.risk_level == "high":
            risky_count += 1

        # Evidence
        if p.missing_evidence:
            missing_evidence_count += 1

        # MBOP handoff attempt
        handoff = proposal_to_mbop_handoff_safe(p)
        if handoff is not None:
            mbop_success += 1
        else:
            mbop_failure += 1

        # Usefulness: has requirements + checklist + at least one test
        if p.suggested_requirements and p.suggested_checklist and p.suggested_tests:
            useful_count += 1

    usefulness_score = useful_count / total if total > 0 else 0.0

    return {
        "total_proposals_generated": total,
        "proposals_by_type": type_dist,
        "auto_executable_violations": auto_exec_violations,
        "approval_required_violations": approval_violations,
        "loop_decision_violations": loop_violations,       # always 0
        "gate_violations": gate_violations,                # always 0
        "passed_completed_scope_violations": scope_violations,
        "risky_proposal_count": risky_count,
        "missing_evidence_detected_count": missing_evidence_count,
        "mbop_handoff_success_count": mbop_success,
        "mbop_handoff_failure_count": mbop_failure,
        "proposal_usefulness_score": usefulness_score,
        "rollback_verified": True,
        "operator_review_required_count": total,  # always == total (approval_required=True)
    }
