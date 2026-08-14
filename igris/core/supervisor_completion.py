"""Completion and cleanup helpers extracted from SelfRepairSupervisor.

Block 1 of #1356 Phase 4.  These functions were originally instance methods on
``SelfRepairSupervisor``.  They have been extracted to this module to reduce
the size of the monolith.  The original class retains thin delegation wrappers
for backward compatibility.

The functions are organised in two groups:

1. **Workspace cleanup** — ``cleanup_blocked_workspace``, ``cleanup_cancelled_workspace``
2. **Completion helpers** — ``complete_noop``, ``cancelled``, ``pr_body``,
   ``persist_assignment_outcome``
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Set

from igris.core.supervisor_models import (
    MissionPlan,
    SupervisorRun,
    _command_detail,
)


# ------------------------------------------------------------------
# Workspace cleanup
# ------------------------------------------------------------------

def cleanup_blocked_workspace(run: SupervisorRun, backend: Any) -> None:
    """Ensure blocked run does not leave dirty workspace state."""
    run.add(
        "blocked_workspace_cleanup",
        "running",
        "Ensuring blocked run does not leave dirty workspace state.",
    )
    status_before = backend.git_status()
    run.add(
        "blocked_workspace_state",
        "success" if status_before.success else "failure",
        _command_detail(status_before),
        dirty=bool(status_before.output.strip()) if status_before.success else False,
    )
    if not status_before.success:
        run.add(
            "blocked_workspace_cleanup",
            "failure",
            "Unable to read git status for blocked workspace cleanup.",
        )
        return
    if not status_before.output.strip():
        run.add(
            "blocked_workspace_cleanup",
            "success",
            "Workspace already clean at blocked exit.",
            no_op=True,
        )
        return
    diff_stat = backend.git_diff_stat()
    run.add(
        "blocked_workspace_diff",
        "success" if diff_stat.success else "failure",
        _command_detail(diff_stat),
    )
    restore = backend.restore_dangerous_diff()
    run.add(
        "blocked_workspace_cleanup",
        "success" if restore.success else "failure",
        _command_detail(restore),
    )
    # Switch back to main so rank branch is not the current HEAD
    checkout_result = backend.checkout_main()
    run.add(
        "blocked_workspace_checkout_main",
        "success" if checkout_result.success else "failure",
        _command_detail(checkout_result),
    )
    # Delete stale rank-* local branches left by supervised runs
    branch_cleanup = backend.delete_stale_rank_branches()
    run.add(
        "blocked_workspace_branch_cleanup",
        "success" if branch_cleanup.success else "failure",
        _command_detail(branch_cleanup),
    )
    status_after = backend.git_status()
    run.add(
        "blocked_workspace_state",
        "success" if status_after.success else "failure",
        _command_detail(status_after),
        dirty=bool(status_after.output.strip()) if status_after.success else False,
        after_cleanup=True,
    )


def cleanup_cancelled_workspace(run: SupervisorRun, backend: Any) -> None:
    """Ensure cancelled run leaves tracked workspace state."""
    run.add(
        "cancel_workspace_cleanup",
        "running",
        "Ensuring cancelled run leaves tracked workspace state.",
    )
    status_before = backend.git_status()
    dirty_before = bool(status_before.output.strip()) if status_before.success else False
    run.add(
        "cancel_workspace_state",
        "success" if status_before.success else "failure",
        _command_detail(status_before),
        dirty=dirty_before,
        before_cleanup=True,
    )
    if not status_before.success or not dirty_before:
        run.add(
            "cancel_workspace_cleanup",
            "skipped",
            "Workspace already clean or status unavailable; no restore executed.",
        )
        return
    restore = backend.restore_dangerous_diff()
    run.add(
        "cancel_workspace_cleanup",
        "success" if restore.success else "failure",
        _command_detail(restore),
    )
    status_after = backend.git_status()
    run.add(
        "cancel_workspace_state",
        "success" if status_after.success else "failure",
        _command_detail(status_after),
        dirty=bool(status_after.output.strip()) if status_after.success else False,
        after_cleanup=True,
    )


# ------------------------------------------------------------------
# Completion helpers
# ------------------------------------------------------------------

def complete_noop(
    supervisor: Any,
    run: SupervisorRun,
    *,
    completion_mode: str,
    runtime_refresh_required: bool,
    detail: str,
    post_merge_smoke: bool,
    mission_plan: Optional[MissionPlan] = None,
    stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    exclude_stage_ids: Optional[Set[str]] = None,
) -> SupervisorRun:
    """Handle no-op completion (mission goal already satisfied)."""
    # No-op completions never execute delivery stages; always exclude them so
    # the required-stages check does not reject a valid no-op because
    # pr_ci_merge / post_merge_runtime were not reached.
    _noop_exclude = (exclude_stage_ids or set()) | {
        "pr_ci_merge",
        "post_merge_runtime",
        "final_report",
    }
    run.completion_mode = completion_mode  # (#147)
    run.add("completion", "degraded", detail, mode=completion_mode)
    final_report_ok = True
    if stage_statuses and "final_report" in stage_statuses:
        if supervisor._required_stages_green(stage_statuses, exclude_stage_ids=_noop_exclude):
            supervisor._set_stage_status(run, stage_statuses, "final_report", "success", "No-op completion validated with required stages satisfied.")
        else:
            supervisor._set_stage_status(run, stage_statuses, "final_report", "failure", "No-op completion rejected: required stage missing.")
            final_report_ok = False
    if final_report_ok:
        supervisor._transition_run_status(run, "completed", "no-op completion reached")
        run.outcome = "Completed"
    else:
        supervisor._transition_run_status(run, "blocked", "no-op required stage missing")
        run.outcome = "Blocked"
        run.failure_class = "reasoning_loop_blocked"
    run.report = {
        "autonomous": True,
        "manual_remaining": "",
        "completion_mode": completion_mode,
        "degraded_completion": True,
        "degraded_completion_reason": (
            f"no-op completion ({completion_mode}): mission goal already satisfied; "
            "no delivery actions performed in this run"
        ),
        "post_merge_smoke": post_merge_smoke,
        "runtime_refresh_required": runtime_refresh_required,
        "no_op_completion": True,
    }
    run.report.update(supervisor._api_escalation_report_fragment(run))
    run.report.update(supervisor._stage_report_fragment(mission_plan, stage_statuses))
    run.touch()
    return run


def cancelled(
    supervisor: Any,
    run: SupervisorRun,
    reason: str,
    *,
    mission_plan: Optional[MissionPlan] = None,
    stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    cleanup_workspace: bool = True,
) -> SupervisorRun:
    """Mark run as cancelled and clean up workspace if requested."""
    run.cancel_requested = True
    run.cancel_reason = reason
    supervisor._transition_run_status(run, "cancelled", reason)
    run.outcome = "Cancelled"
    run.failure_class = "user_cancelled"
    run.add("cancelled", "cancelled", reason)
    if cleanup_workspace:
        cleanup_cancelled_workspace(run, supervisor.backend)
    if stage_statuses and "final_report" in stage_statuses:
        supervisor._set_stage_status(run, stage_statuses, "final_report", "failure", "Run cancelled by user.")
    run.report = {"autonomous": False, "cancelled_reason": reason, "blocked_reason": reason}
    run.report.update(supervisor._api_escalation_report_fragment(run))
    run.report.update(supervisor._stage_report_fragment(mission_plan, stage_statuses))
    run.touch()
    return run


def pr_body(run: SupervisorRun) -> str:
    """Generate a PR body for a supervised rank run."""
    lines = [
        "## Summary",
        f"- Supervised rank run `{run.run_id}` completed.",
        "",
        "## Safety",
        "- Full pytest passed before merge consideration.",
        "- No direct push to main.",
    ]
    # Append "Closes #N" so GitHub auto-closes the issue on merge.
    goal = getattr(run, "goal", "") or ""
    _m = re.search(r"#(\d+)", goal)
    if _m:
        lines += ["", f"Closes #{_m.group(1)}"]
    return "\n".join(lines)


def persist_assignment_outcome(
    run: "SupervisorRun",
    project_root: Any,
    assignment_decision: Any,
) -> None:
    """Append assignment outcome record for historical learning. No-op if unavailable."""
    # Lazy imports to avoid circular deps
    try:
        from igris.core.assignment_router import AssignmentDecision  # noqa: F401
        from igris.core.assignment_outcomes import compute_task_signature, save_assignment_outcome
    except ImportError:
        return
    if assignment_decision is None:
        return
    try:
        outcomes_path = str(Path(project_root) / ".igris" / "assignment_outcomes.json")
        total_cost = run.execution_budget_used_usd + run.api_budget_used_usd
        attempts = run.repair_cycles_used + 1
        cost_per_success = (
            round(total_cost / attempts, 6)
            if run.status == "completed" and attempts > 0
            else None
        )
        record = {
            "task_signature": compute_task_signature(getattr(run, "goal", "") or ""),
            "goal_excerpt": (getattr(run, "goal", "") or "")[:200],
            "agent_role": assignment_decision.agent_role,
            "task_type": assignment_decision.task_type,
            "preferred_profile": assignment_decision.preferred_profile,
            "execution_strategy": assignment_decision.execution_strategy,
            "model_used": assignment_decision.preferred_model,
            "fallback_model_path": list(assignment_decision.fallback_model_path),
            "outcome": run.status,
            "failure_class": run.failure_class,
            "capability_signals": dict(run.capability_signals),
            "cost_usd": total_cost,
            "execution_cost_usd": run.execution_budget_used_usd,
            "helper_cost_usd": run.api_budget_used_usd,
            "cost_per_success": cost_per_success,
            "attempts": attempts,
            "execution_provider": "",
            "execution_model": "",
            "created_at": run.created_at.isoformat() if hasattr(run, "created_at") and run.created_at else "",
        }
        save_assignment_outcome(outcomes_path, record)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("Failed to persist assignment outcome: %s", exc)
