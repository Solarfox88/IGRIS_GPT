"""Rank completion workflow extracted from SelfRepairSupervisor.

This module hosts ``complete_rank``, originally the ``_complete_rank`` instance
method on ``SelfRepairSupervisor``.  It handles rank completion: commit, push,
PR, CI, merge, post-merge smoke, degraded completion computation, and the final
report.

The original class retains a thin delegation wrapper for backward compatibility.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from igris.core.supervisor_models import _command_detail
import logging


_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from igris.core.supervisor_models import (
        CommandResult,
        MissionPlan,
        RankSupervisorConfig,
        SupervisorRun,
    )


def complete_rank(
    supervisor: Any,
    run: "SupervisorRun",
    config: "RankSupervisorConfig",
    branch: str,
    *,
    completion_mode: str = "direct",
    runtime_refresh_required: bool = False,
    mission_plan: Optional["MissionPlan"] = None,
    stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
) -> "SupervisorRun":
    cancelled = supervisor._cancel_if_requested(run, mission_plan=mission_plan, stage_statuses=stage_statuses)
    if cancelled is not None:
        return cancelled
    restart_command = config.service_restart_command if not config.defer_service_restart else ""
    post_merge_smoke: Optional[CommandResult] = None
    manual_remaining = ""
    if stage_statuses and "pr_ci_merge" in stage_statuses:
        supervisor._set_stage_status(run, stage_statuses, "pr_ci_merge", "running", "Executing PR/CI/merge workflow.")
    if config.dry_run:
        manual_remaining = "delivery skipped by dry_run"
        run.add("github", "dry_run", "Commit/PR/merge skipped by dry_run")
        if stage_statuses and "pr_ci_merge" in stage_statuses:
            supervisor._set_stage_status(
                run,
                stage_statuses,
                "pr_ci_merge",
                "skipped",
                "PR/CI/merge skipped because dry_run is enabled.",
                no_op=True,
            )
        if stage_statuses and "post_merge_runtime" in stage_statuses:
            supervisor._set_stage_status(
                run,
                stage_statuses,
                "post_merge_runtime",
                "skipped",
                "Post-merge runtime checks skipped because dry_run is enabled.",
                no_op=True,
            )
    else:
        commit = supervisor.backend.commit(f"feat: complete supervised {config.rank_id}", ["igris", "tests"])
        run.add("commit", "success" if commit.success else "failure", _command_detail(commit))
        if not commit.success and "nothing to commit" in (commit.output or "") + (commit.error or ""):
            # Working tree unexpectedly clean — attempt patch-based recovery.
            # The diff was saved to disk before tests ran; apply it now.
            _patch_path = Path(supervisor.project_root) / ".igris" / "rank_pending.patch"
            if _patch_path.exists():
                run.add("commit_patch_recovery", "running", "Applying saved diff patch to recover working tree")
                apply = supervisor.backend.git_apply_patch(
                    str(_patch_path),
                    timeout=30,
                )
                run.add(
                    "commit_patch_recovery",
                    "success" if apply.success else "failure",
                    _command_detail(apply),
                )
                if apply.success:
                    commit = supervisor.backend.commit(
                        f"feat: complete supervised {config.rank_id}", None
                    )
                    run.add(
                        "commit",
                        "success" if commit.success else "failure",
                        _command_detail(commit),
                    )
                try:
                    _patch_path.unlink(missing_ok=True)
                except OSError as exc:
                    _log.debug("supervisor_complete_rank: narrowed catch failed: %s", exc, exc_info=True)
        elif commit.success:
            try:
                (Path(supervisor.project_root) / ".igris" / "rank_pending.patch").unlink(missing_ok=True)
            except OSError as exc:
                _log.debug("supervisor_complete_rank: narrowed catch failed: %s", exc, exc_info=True)
        if not commit.success:
            return supervisor._blocked(
                run,
                "infrastructure_bug",
                "Commit failed",
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
            )
        if config.allow_github_pr:
            push = supervisor.backend.push_branch(branch)
            run.add("push", "success" if push.success else "failure", _command_detail(push))
            pr = supervisor.backend.open_pr(branch, f"feat: supervised {config.rank_id}", supervisor._pr_body(run))
            run.add("pr", "success" if pr.success else "failure", _command_detail(pr))
            ci = supervisor.backend.wait_ci()
            run.add("ci", "success" if ci.success else "failure", _command_detail(ci))
            if stage_statuses and "pr_ci_merge" in stage_statuses:
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "pr_ci_merge",
                    "success" if ci.success else "failure",
                    "PR workflow green." if ci.success else "PR workflow failed or CI not green.",
                )
            if config.allow_merge_if_green and ci.success:
                merge = supervisor.backend.merge_pr()
                run.add("merge", "success" if merge.success else "failure", _command_detail(merge))
                pull = supervisor.backend.pull_main()
                run.add("pull_main", "success" if pull.success else "failure", _command_detail(pull))
                if config.defer_service_restart and runtime_refresh_required:
                    run.add(
                        "post_merge_smoke",
                        "deferred",
                        "Post-merge smoke deferred until the runtime is restarted and refreshed.",
                        runtime_refresh_required=True,
                    )
                    if stage_statuses and "post_merge_runtime" in stage_statuses:
                        supervisor._set_stage_status(
                            run,
                            stage_statuses,
                            "post_merge_runtime",
                            "skipped",
                            "Post-merge runtime smoke deferred until runtime refresh.",
                            no_op=True,
                        )
                else:
                    post_merge_smoke = supervisor.backend.smoke(
                        config.required_smoke_endpoints,
                        restart_command,
                    )
                    assert post_merge_smoke is not None
                    run.add(
                        "post_merge_smoke",
                        "success" if post_merge_smoke.success else "failure",
                        _command_detail(post_merge_smoke),
                    )
                    if stage_statuses and "post_merge_runtime" in stage_statuses:
                        supervisor._set_stage_status(
                            run,
                            stage_statuses,
                            "post_merge_runtime",
                            "success" if post_merge_smoke.success else "failure",
                            "Post-merge runtime smoke passed."
                            if post_merge_smoke.success
                            else "Post-merge runtime smoke failed.",
                        )
                    if not post_merge_smoke.success:
                        supervisor._transition_run_status(run, "blocked", "post-merge smoke failed")
                        run.outcome = "Blocked"
                        run.failure_class = "infrastructure_bug"
                        _deg, _deg_reason = supervisor._compute_degraded_completion(
                            completion_mode=completion_mode,
                            runtime_refresh_required=runtime_refresh_required,
                            post_merge_smoke_success=False,
                            smoke_was_applicable=True,  # smoke ran (but failed)
                            failure_class=run.failure_class,
                            stage_statuses=stage_statuses,
                        )
                        run.report = {
                            "autonomous": True,
                            "manual_remaining": "post-merge verification failed",
                            "completion_mode": completion_mode,
                            "degraded_completion": _deg,
                            "degraded_completion_reason": _deg_reason,
                            "post_merge_smoke": False,
                            "runtime_refresh_required": runtime_refresh_required,
                        }
                        if run.acceptance_evidence is not None:
                            run.report["acceptance_evidence"] = run.acceptance_evidence
                        run.report.update(supervisor._api_escalation_report_fragment(run))
                        run.report.update(supervisor._stage_report_fragment(mission_plan, stage_statuses))
                        run.touch()
                        return run
            elif config.allow_merge_if_green and not ci.success:
                manual_remaining = "merge skipped because CI is not green"
                if stage_statuses and "post_merge_runtime" in stage_statuses:
                    supervisor._set_stage_status(
                        run,
                        stage_statuses,
                        "post_merge_runtime",
                        "skipped",
                        "Post-merge runtime checks skipped because merge did not occur.",
                        no_op=True,
                    )
            else:
                manual_remaining = "merge disabled by config"
                if stage_statuses and "post_merge_runtime" in stage_statuses:
                    supervisor._set_stage_status(
                        run,
                        stage_statuses,
                        "post_merge_runtime",
                        "skipped",
                        "Post-merge runtime checks skipped because merge is disabled by config.",
                        no_op=True,
                    )
        else:
            manual_remaining = "GitHub PR/merge workflow disabled by config"
            if stage_statuses and "pr_ci_merge" in stage_statuses:
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "pr_ci_merge",
                    "skipped",
                    "PR workflow disabled by config.",
                    no_op=True,
                )
            if stage_statuses and "post_merge_runtime" in stage_statuses:
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "post_merge_runtime",
                    "skipped",
                    "Post-merge runtime checks skipped because PR workflow is disabled.",
                    no_op=True,
                )
    final_report_ok = True
    if stage_statuses and "final_report" in stage_statuses:
        if supervisor._required_stages_green(stage_statuses):
            supervisor._set_stage_status(run, stage_statuses, "final_report", "success", "All required mission stages are green.")
        else:
            supervisor._set_stage_status(run, stage_statuses, "final_report", "failure", "Required mission stage is missing or failed.")
            final_report_ok = False
    if final_report_ok:
        supervisor._transition_run_status(run, "completed", "rank completion reached")
        run.outcome = "Completed"
    else:
        supervisor._transition_run_status(run, "blocked", "final_report required stage failure")
        run.outcome = "Blocked"
        run.failure_class = "infrastructure_bug"
    post_smoke_success = False if post_merge_smoke is None else post_merge_smoke.success
    # post_merge_smoke is only non-None when a merge was actually executed
    smoke_applicable = post_merge_smoke is not None
    degraded, degraded_reason = supervisor._compute_degraded_completion(
        completion_mode=completion_mode,
        runtime_refresh_required=runtime_refresh_required,
        post_merge_smoke_success=post_smoke_success,
        smoke_was_applicable=smoke_applicable,
        failure_class=run.failure_class,
        stage_statuses=stage_statuses,
    )
    run.completion_mode = completion_mode  # (#147) expose for MBOP Phase 11
    run.report = {
        "autonomous": True,
        "manual_remaining": manual_remaining,
        "completion_mode": completion_mode,
        "degraded_completion": degraded,
        "degraded_completion_reason": degraded_reason,
        "post_merge_smoke": post_smoke_success,
        "runtime_refresh_required": runtime_refresh_required,
    }
    if run.acceptance_evidence is not None:
        run.report["acceptance_evidence"] = run.acceptance_evidence
    run.report.update(supervisor._api_escalation_report_fragment(run))
    run.report.update(supervisor._stage_report_fragment(mission_plan, stage_statuses))
    run.touch()
    return run
