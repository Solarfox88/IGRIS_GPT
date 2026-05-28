#!/usr/bin/env python3
"""Mission Brain EPIC #874 — #875: Define Goal/Run status model and mapping table.

Defines:
  - RunStatus: operational verdict from the loop (run-level, binary)
  - GoalStatus: strategic verdict from Mission Brain (goal-level, graded)
  - CombinedStatus: composed interpretation
  - NextActionRecommendation: what Igris should do next

Mapping table covers all (run, goal) pairs from the spec + edge cases.
Outputs the model as a JSON schema artifact + MD reference.

Usage:
    python scripts/run_goal_run_bridge_model_875.py
"""
from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Status enumerations (as plain string constants — no enum dep needed)
# ---------------------------------------------------------------------------

# Run-level statuses (current supervisor loop)
RUN_STATUS_PASSED  = "passed"
RUN_STATUS_FAILED  = "failed"
RUN_STATUS_BLOCKED = "blocked"
RUN_STATUS_UNKNOWN = "unknown"

RUN_STATUSES = frozenset({
    RUN_STATUS_PASSED,
    RUN_STATUS_FAILED,
    RUN_STATUS_BLOCKED,
    RUN_STATUS_UNKNOWN,
})

# Goal-level statuses (Mission Brain shadow evaluation)
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_PARTIAL   = "partial"
GOAL_STATUS_FAILED    = "failed"
GOAL_STATUS_UNKNOWN   = "unknown"

GOAL_STATUSES = frozenset({
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_PARTIAL,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_UNKNOWN,
})

# Combined statuses
COMBINED_COMPLETED                          = "completed"
COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS    = "technical_failure_with_goal_progress"
COMBINED_HARD_FAILURE                       = "hard_failure"
COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE  = "technical_success_but_goal_incomplete"
COMBINED_BLOCKED_GOAL_PROGRESS              = "blocked_with_goal_progress"
COMBINED_BLOCKED_GOAL_FAILED                = "blocked_goal_failed"
COMBINED_INSUFFICIENT_CONTEXT               = "insufficient_context"
COMBINED_GOAL_COMPLETE_RUN_FAILED           = "goal_complete_run_failed"
COMBINED_GOAL_COMPLETE_RUN_BLOCKED          = "goal_complete_run_blocked"

COMBINED_STATUSES = frozenset({
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

# Next-action recommendations
NEXT_RECOVER_FROM_PARTIAL      = "recover_or_continue_from_partial_progress"
NEXT_DIAGNOSE_FAILURE          = "diagnose_failure"
NEXT_CONTINUE_OR_CLARIFY       = "continue_mission_or_request_clarification"
NEXT_MARK_COMPLETE             = "mark_mission_complete"
NEXT_REQUEST_CONTEXT           = "request_context_or_planning"
NEXT_REVIEW_ANOMALY            = "review_anomaly"
NEXT_UNBLOCK_THEN_CONTINUE     = "unblock_then_continue_from_partial"
NEXT_UNBLOCK_THEN_DIAGNOSE     = "unblock_then_diagnose"

NEXT_ACTIONS = frozenset({
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
# Mapping table: (run_status, goal_status) → (combined_status, next_action)
# ---------------------------------------------------------------------------
# Format: (run, goal): {"combined": ..., "next": ..., "rationale": ...}

MAPPING_TABLE: dict = {
    # --- Run passed ---
    (RUN_STATUS_PASSED, GOAL_STATUS_COMPLETED): {
        "combined": COMBINED_COMPLETED,
        "next": NEXT_MARK_COMPLETE,
        "rationale": "Run succeeded and goal fully achieved. Mission complete.",
    },
    (RUN_STATUS_PASSED, GOAL_STATUS_PARTIAL): {
        "combined": COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE,
        "next": NEXT_CONTINUE_OR_CLARIFY,
        "rationale": (
            "Run succeeded but goal is only partially met. Either the goal needs more "
            "iterations or its scope is ambiguous. Request clarification or plan next step."
        ),
    },
    (RUN_STATUS_PASSED, GOAL_STATUS_FAILED): {
        "combined": COMBINED_TECHNICAL_SUCCESS_GOAL_INCOMPLETE,
        "next": NEXT_REVIEW_ANOMALY,
        "rationale": (
            "Anomalous: run passed but MB says goal failed. Possible goal-scope mismatch "
            "or MB evaluation error. Requires human review."
        ),
    },
    (RUN_STATUS_PASSED, GOAL_STATUS_UNKNOWN): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run passed but goal evaluation unavailable. Request context before continuing.",
    },

    # --- Run failed ---
    (RUN_STATUS_FAILED, GOAL_STATUS_COMPLETED): {
        "combined": COMBINED_GOAL_COMPLETE_RUN_FAILED,
        "next": NEXT_REVIEW_ANOMALY,
        "rationale": (
            "Anomalous: run failed but MB says goal completed. Likely MB evaluated "
            "a prior successful attempt. Requires review — do not treat as completed "
            "without operator confirmation."
        ),
    },
    (RUN_STATUS_FAILED, GOAL_STATUS_PARTIAL): {
        "combined": COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS,
        "next": NEXT_RECOVER_FROM_PARTIAL,
        "rationale": (
            "Run failed but partial goal progress was made. Some sub-tasks completed "
            "before block. Recover from partial state and continue."
        ),
    },
    (RUN_STATUS_FAILED, GOAL_STATUS_FAILED): {
        "combined": COMBINED_HARD_FAILURE,
        "next": NEXT_DIAGNOSE_FAILURE,
        "rationale": "Both run and goal failed. Hard failure — diagnose root cause.",
    },
    (RUN_STATUS_FAILED, GOAL_STATUS_UNKNOWN): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run failed and goal evaluation unavailable. Context needed before recovery.",
    },

    # --- Run blocked ---
    (RUN_STATUS_BLOCKED, GOAL_STATUS_COMPLETED): {
        "combined": COMBINED_GOAL_COMPLETE_RUN_BLOCKED,
        "next": NEXT_REVIEW_ANOMALY,
        "rationale": (
            "Run blocked but MB says goal completed. Possible stale MB eval. "
            "Review before treating as completed."
        ),
    },
    (RUN_STATUS_BLOCKED, GOAL_STATUS_PARTIAL): {
        "combined": COMBINED_BLOCKED_GOAL_PROGRESS,
        "next": NEXT_UNBLOCK_THEN_CONTINUE,
        "rationale": (
            "Run blocked but partial goal progress made. Unblock (e.g. clean workspace) "
            "then continue from partial state. This is the most common case in #868 dataset."
        ),
    },
    (RUN_STATUS_BLOCKED, GOAL_STATUS_FAILED): {
        "combined": COMBINED_BLOCKED_GOAL_FAILED,
        "next": NEXT_UNBLOCK_THEN_DIAGNOSE,
        "rationale": "Run blocked and goal failed. Unblock then diagnose root cause.",
    },
    (RUN_STATUS_BLOCKED, GOAL_STATUS_UNKNOWN): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run blocked and goal state unknown. Need context to proceed.",
    },

    # --- Run unknown ---
    (RUN_STATUS_UNKNOWN, GOAL_STATUS_COMPLETED): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run status unknown. Cannot confirm completed — request run status.",
    },
    (RUN_STATUS_UNKNOWN, GOAL_STATUS_PARTIAL): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run status unknown. Cannot act on partial — request run status.",
    },
    (RUN_STATUS_UNKNOWN, GOAL_STATUS_FAILED): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Run status unknown. Cannot diagnose — request run status.",
    },
    (RUN_STATUS_UNKNOWN, GOAL_STATUS_UNKNOWN): {
        "combined": COMBINED_INSUFFICIENT_CONTEXT,
        "next": NEXT_REQUEST_CONTEXT,
        "rationale": "Both statuses unknown. Request full context.",
    },
}

# Validate: all (run, goal) pairs covered
def _validate_mapping_table() -> None:
    for run in RUN_STATUSES:
        for goal in GOAL_STATUSES:
            key = (run, goal)
            assert key in MAPPING_TABLE, f"Missing mapping for {key}"
            entry = MAPPING_TABLE[key]
            assert "combined" in entry, f"Missing combined for {key}"
            assert "next" in entry, f"Missing next for {key}"
            assert "rationale" in entry, f"Missing rationale for {key}"
            assert entry["combined"] in COMBINED_STATUSES, (
                f"Unknown combined status {entry['combined']!r} for {key}"
            )
            assert entry["next"] in NEXT_ACTIONS, (
                f"Unknown next action {entry['next']!r} for {key}"
            )


def main() -> int:
    _validate_mapping_table()

    # Serialize mapping table as list of records
    mapping_records = [
        {
            "run_status": run,
            "goal_status": goal,
            "combined_status": MAPPING_TABLE[(run, goal)]["combined"],
            "next_action_recommendation": MAPPING_TABLE[(run, goal)]["next"],
            "rationale": MAPPING_TABLE[(run, goal)]["rationale"],
        }
        for run in sorted(RUN_STATUSES)
        for goal in sorted(GOAL_STATUSES)
    ]

    model = {
        "epic": 874,
        "subissue": 875,
        "title": "Goal/Run Status Model and Mapping Table",

        "run_statuses": sorted(RUN_STATUSES),
        "goal_statuses": sorted(GOAL_STATUSES),
        "combined_statuses": sorted(COMBINED_STATUSES),
        "next_action_recommendations": sorted(NEXT_ACTIONS),

        "mapping_table": mapping_records,
        "mapping_table_size": len(mapping_records),

        # Key design constraints (from epic spec)
        "design_constraints": [
            "Bridge is observational/diagnostic only — not decisional by default",
            "Shadow mode only — does not modify loop behavior",
            "combined=completed only when run=passed AND goal=completed",
            "goal=completed with run=failed/blocked → anomaly review, not completed",
            "Mapping is deterministic and fully enumerated",
        ],

        "guardrails": {
            "shadow_mode_only": True,
            "default_behavior_unchanged": True,
            "no_enable_by_default": True,
            "no_mandatory_gate": True,
            "completed_not_more_permissive": True,
        },

        "evaluation": "passed",
        "stop_reason": None,
        "next_subissue": 876,
    }

    out_dir = Path("reports/mission_brain/bridge/875")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "bridge_model_875.json"
    md_path = out_dir / "bridge_model_875.md"

    json_path.write_text(json.dumps(model, indent=2), encoding="utf-8")

    md = [
        "# Goal/Run Status Bridge Model — #875",
        "## EPIC #874 Mission Brain Goal/Run Status Bridge",
        "",
        "## Status Enumerations",
        "",
        "### RunStatus (loop, run-level, binary)",
        f"  `{', '.join(sorted(RUN_STATUSES))}`",
        "",
        "### GoalStatus (Mission Brain, goal-level, graded)",
        f"  `{', '.join(sorted(GOAL_STATUSES))}`",
        "",
        "### CombinedStatus (bridge output)",
        f"  `{', '.join(sorted(COMBINED_STATUSES))}`",
        "",
        "## Mapping Table",
        "",
        "| run_status | goal_status | combined_status | next_action_recommendation |",
        "|------------|-------------|-----------------|---------------------------|",
    ]
    for rec in mapping_records:
        md.append(
            f"| {rec['run_status']} | {rec['goal_status']} "
            f"| {rec['combined_status']} | {rec['next_action_recommendation']} |"
        )
    md += [
        "",
        "## Design Constraints",
        "",
        "- Bridge is observational/diagnostic only — not decisional by default",
        "- Shadow mode only — does not modify loop behavior",
        "- `combined=completed` only when `run=passed AND goal=completed`",
        "- `goal=completed` with `run=failed/blocked` → anomaly review, not completed",
        "- Mapping is deterministic and fully enumerated (4×4 = 16 pairs)",
        "",
        "## Evaluation: passed",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 875,
        "mapping_table_size": len(mapping_records),
        "run_statuses": sorted(RUN_STATUSES),
        "goal_statuses": sorted(GOAL_STATUSES),
        "combined_statuses": sorted(COMBINED_STATUSES),
        "validation": "passed",
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
