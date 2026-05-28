"""Goal/Run Status Bridge — EPIC #874 (#876).

Observational/diagnostic shadow module that maps the combination of:
  - run_status  : operational verdict from the supervisor loop (run-level, binary)
  - goal_status : strategic verdict from Mission Brain (goal-level, graded)

to a composed ``combined_status`` and a ``next_action_recommendation``.

DESIGN CONSTRAINTS:
  - Shadow mode only: this module does NOT modify loop behavior.
  - Observational/diagnostic — NOT decisional by default.
  - combined=completed ONLY when run=passed AND goal=completed.
  - goal=completed with run!=passed → anomaly review, never automatic completed.
  - Fully deterministic: same inputs always produce same outputs.
  - No side effects: pure functions only.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# RunStatus constants
# ---------------------------------------------------------------------------
RUN_PASSED  = "passed"
RUN_FAILED  = "failed"
RUN_BLOCKED = "blocked"
RUN_UNKNOWN = "unknown"

RUN_STATUSES: frozenset = frozenset({RUN_PASSED, RUN_FAILED, RUN_BLOCKED, RUN_UNKNOWN})

# ---------------------------------------------------------------------------
# GoalStatus constants
# ---------------------------------------------------------------------------
GOAL_COMPLETED = "completed"
GOAL_PARTIAL   = "partial"
GOAL_FAILED    = "failed"
GOAL_UNKNOWN   = "unknown"

GOAL_STATUSES: frozenset = frozenset({GOAL_COMPLETED, GOAL_PARTIAL, GOAL_FAILED, GOAL_UNKNOWN})

# ---------------------------------------------------------------------------
# CombinedStatus constants
# ---------------------------------------------------------------------------
COMBINED_COMPLETED                         = "completed"
COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS   = "technical_failure_with_goal_progress"
COMBINED_HARD_FAILURE                      = "hard_failure"
COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE = "technical_success_but_goal_incomplete"
COMBINED_BLOCKED_GOAL_PROGRESS             = "blocked_with_goal_progress"
COMBINED_BLOCKED_GOAL_FAILED               = "blocked_goal_failed"
COMBINED_INSUFFICIENT_CONTEXT             = "insufficient_context"
COMBINED_GOAL_COMPLETE_RUN_FAILED          = "goal_complete_run_failed"
COMBINED_GOAL_COMPLETE_RUN_BLOCKED         = "goal_complete_run_blocked"

COMBINED_STATUSES: frozenset = frozenset({
    COMBINED_COMPLETED,
    COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS,
    COMBINED_HARD_FAILURE,
    COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE,
    COMBINED_BLOCKED_GOAL_PROGRESS,
    COMBINED_BLOCKED_GOAL_FAILED,
    COMBINED_INSUFFICIENT_CONTEXT,
    COMBINED_GOAL_COMPLETE_RUN_FAILED,
    COMBINED_GOAL_COMPLETE_RUN_BLOCKED,
})

# ---------------------------------------------------------------------------
# NextActionRecommendation constants
# ---------------------------------------------------------------------------
NEXT_RECOVER_FROM_PARTIAL  = "recover_or_continue_from_partial_progress"
NEXT_DIAGNOSE_FAILURE      = "diagnose_failure"
NEXT_CONTINUE_OR_CLARIFY   = "continue_mission_or_request_clarification"
NEXT_MARK_COMPLETE         = "mark_mission_complete"
NEXT_REQUEST_CONTEXT       = "request_context_or_planning"
NEXT_REVIEW_ANOMALY        = "review_anomaly"
NEXT_UNBLOCK_THEN_CONTINUE = "unblock_then_continue_from_partial"
NEXT_UNBLOCK_THEN_DIAGNOSE = "unblock_then_diagnose"

NEXT_ACTIONS: frozenset = frozenset({
    NEXT_RECOVER_FROM_PARTIAL,
    NEXT_DIAGNOSE_FAILURE,
    NEXT_CONTINUE_OR_CLARIFY,
    NEXT_MARK_COMPLETE,
    NEXT_REQUEST_CONTEXT,
    NEXT_REVIEW_ANOMALY,
    NEXT_UNBLOCK_THEN_CONTINUE,
    NEXT_UNBLOCK_THEN_DIAGNOSE,
})

# ---------------------------------------------------------------------------
# Mapping table — fully enumerated 4×4 = 16 pairs
# ---------------------------------------------------------------------------
# (run_status, goal_status) → (combined_status, next_action, rationale)
_BRIDGE_MAP: Dict[Tuple[str, str], Dict[str, str]] = {
    # run=passed
    (RUN_PASSED, GOAL_COMPLETED): {
        "combined": COMBINED_COMPLETED,
        "next": NEXT_MARK_COMPLETE,
        "rationale": "Run succeeded and goal fully achieved. Mission complete.",
    },
    (RUN_PASSED, GOAL_PARTIAL): {
        "combined": COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE,
        "next": NEXT_CONTINUE_OR_CLARIFY,
        "rationale": (
            "Run succeeded but goal only partially met. "
            "Either more iterations needed or goal scope is ambiguous."
        ),
    },
    (RUN_PASSED, GOAL_FAILED): {
        "combined": COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE,
        "next": NEXT_REVIEW_ANOMALY,
        "rationale": (
            "Anomalous: run passed but MB says goal failed. "
            "Possible goal-scope mismatch or MB evaluation error. Requires human review."
        ),
    },
    (RUN_PASSED, GOAL_UNKNOWN): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run passed but goal evaluation unavailable. Request context before continuing.",
    },

    # run=failed
    (RUN_FAILED, GOAL_COMPLETED): {
        "combined": COMBINED_GOAL_COMPLETE_RUN_FAILED,
        "next": NEXT_REVIEW_ANOMALY,
        "rationale": (
            "Anomalous: run failed but MB says goal completed. "
            "Do not treat as completed without operator confirmation."
        ),
    },
    (RUN_FAILED, GOAL_PARTIAL): {
        "combined": COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS,
        "next": NEXT_RECOVER_FROM_PARTIAL,
        "rationale": (
            "Run failed but partial goal progress was made. "
            "Recover from partial state and continue toward goal."
        ),
    },
    (RUN_FAILED, GOAL_FAILED): {
        "combined": COMBINED_HARD_FAILURE,
        "next": NEXT_DIAGNOSE_FAILURE,
        "rationale": "Both run and goal failed. Hard failure — diagnose root cause.",
    },
    (RUN_FAILED, GOAL_UNKNOWN): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run failed and goal evaluation unavailable. Context needed before recovery.",
    },

    # run=blocked
    (RUN_BLOCKED, GOAL_COMPLETED): {
        "combined": COMBINED_GOAL_COMPLETE_RUN_BLOCKED,
        "next": NEXT_REVIEW_ANOMALY,
        "rationale": (
            "Run blocked but MB says goal completed. Possible stale MB eval. "
            "Review before treating as completed."
        ),
    },
    (RUN_BLOCKED, GOAL_PARTIAL): {
        "combined": COMBINED_BLOCKED_GOAL_PROGRESS,
        "next": NEXT_UNBLOCK_THEN_CONTINUE,
        "rationale": (
            "Run blocked but partial goal progress made. "
            "Unblock (e.g. clean workspace) then continue from partial state. "
            "Most common case in #868 calibration dataset (17/20 new cycles)."
        ),
    },
    (RUN_BLOCKED, GOAL_FAILED): {
        "combined": COMBINED_BLOCKED_GOAL_FAILED,
        "next": NEXT_UNBLOCK_THEN_DIAGNOSE,
        "rationale": "Run blocked and goal failed. Unblock then diagnose root cause.",
    },
    (RUN_BLOCKED, GOAL_UNKNOWN): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run blocked and goal state unknown. Need context to proceed.",
    },

    # run=unknown
    (RUN_UNKNOWN, GOAL_COMPLETED): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run status unknown. Cannot confirm completed — request run status.",
    },
    (RUN_UNKNOWN, GOAL_PARTIAL): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run status unknown. Cannot act on partial — request run status.",
    },
    (RUN_UNKNOWN, GOAL_FAILED): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run status unknown. Cannot diagnose — request run status.",
    },
    (RUN_UNKNOWN, GOAL_UNKNOWN): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Both statuses unknown. Request full context.",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def bridge(run_status: str, goal_status: str) -> Dict[str, str]:
    """Map (run_status, goal_status) → bridge result dict.

    Returns a dict with keys:
      - run_status
      - goal_status
      - combined_status
      - next_action_recommendation
      - rationale

    For unknown inputs, falls back to COMBINED_INSUFFICIENT_CONTEXT /
    NEXT_REQUEST_CONTEXT rather than raising — ensures the bridge never
    crashes the loop.
    """
    # Normalize
    run = str(run_status or "").strip().lower()
    goal = str(goal_status or "").strip().lower()

    if run not in RUN_STATUSES:
        run = RUN_UNKNOWN
    if goal not in GOAL_STATUSES:
        goal = GOAL_UNKNOWN

    entry = _BRIDGE_MAP[(run, goal)]
    return {
        "run_status": run,
        "goal_status": goal,
        "combined_status": entry["combined"],
        "next_action_recommendation": entry["next"],
        "rationale": entry["rationale"],
    }


def bridge_cycle(cycle: Dict[str, Any]) -> Dict[str, Any]:
    """Apply bridge to a single shadow cycle record.

    Reads run_status from ``current_loop_decision`` and goal_status from
    ``mission_brain_decision``. Returns an augmented copy of the cycle
    record with bridge fields added.

    This function is ADDITIVE — it does not modify the original cycle dict
    and does not alter any loop decision.
    """
    run_status = _normalize_run_status(cycle.get("current_loop_decision", ""))
    goal_status = _normalize_goal_status(cycle.get("mission_brain_decision", ""))
    result = bridge(run_status, goal_status)
    return {
        **cycle,
        "bridge_run_status": result["run_status"],
        "bridge_goal_status": result["goal_status"],
        "combined_status": result["combined_status"],
        "next_action_recommendation": result["next_action_recommendation"],
        "bridge_rationale": result["rationale"],
    }


def _normalize_run_status(raw: Optional[str]) -> str:
    """Map loop decision values to RunStatus."""
    if not raw:
        return RUN_UNKNOWN
    r = str(raw).strip().lower()
    if r in RUN_STATUSES:
        return r
    # Common aliases from supervisor loop
    if r in ("success", "completed", "ok"):
        return RUN_PASSED
    if r in ("fail", "error", "exception"):
        return RUN_FAILED
    if r in ("block", "dirty", "workspace_dirty", "infrastructure_error"):
        return RUN_BLOCKED
    return RUN_UNKNOWN


def _normalize_goal_status(raw: Optional[str]) -> str:
    """Map MB decision values to GoalStatus."""
    if not raw:
        return GOAL_UNKNOWN
    r = str(raw).strip().lower()
    if r in GOAL_STATUSES:
        return r
    # Common aliases
    if r in ("complete", "done", "success"):
        return GOAL_COMPLETED
    if r in ("fail", "error"):
        return GOAL_FAILED
    if r in ("in_progress", "progress", "partial_success"):
        return GOAL_PARTIAL
    return GOAL_UNKNOWN


def aggregate_bridge_cycles(cycles: list) -> Dict[str, Any]:
    """Aggregate per-cycle bridge results into summary metrics.

    Returns distribution of combined_status and next_action_recommendation,
    plus individual counts for the key cases from the epic spec.
    """
    bridged = [bridge_cycle(c) for c in cycles]
    total = len(bridged)

    combined_dist: Dict[str, int] = {}
    next_dist: Dict[str, int] = {}
    for b in bridged:
        cs = b["combined_status"]
        na = b["next_action_recommendation"]
        combined_dist[cs] = combined_dist.get(cs, 0) + 1
        next_dist[na] = next_dist.get(na, 0) + 1

    # Sort distributions by count desc
    combined_dist = dict(sorted(combined_dist.items(), key=lambda x: -x[1]))
    next_dist = dict(sorted(next_dist.items(), key=lambda x: -x[1]))

    return {
        "total_cycles": total,
        "combined_status_distribution": combined_dist,
        "next_action_recommendation_distribution": next_dist,
        # Named counts from epic spec
        "technical_failure_with_goal_progress_count": combined_dist.get(
            COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS, 0
        ),
        "technical_success_but_goal_incomplete_count": combined_dist.get(
            COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE, 0
        ),
        "hard_failure_count": combined_dist.get(COMBINED_HARD_FAILURE, 0),
        "completed_count": combined_dist.get(COMBINED_COMPLETED, 0),
        "insufficient_context_count": combined_dist.get(COMBINED_INSUFFICIENT_CONTEXT, 0),
        "blocked_with_goal_progress_count": combined_dist.get(COMBINED_BLOCKED_GOAL_PROGRESS, 0),
        "anomaly_count": sum(
            combined_dist.get(c, 0)
            for c in (COMBINED_GOAL_COMPLETE_RUN_FAILED, COMBINED_GOAL_COMPLETE_RUN_BLOCKED)
        ),
    }
