"""Preflight phase extraction for the self-repair supervisor.

This module hosts :func:`run_preflight_phase`, which implements Phase 1 of a
supervised rank run: init, git status, baseline sanity tests, smoke checks,
assignment routing, and mission-plan construction. It is a pure mechanical
extraction of ``SelfRepairSupervisor._run_preflight_phase`` and preserves the
original behaviour exactly — ``self`` references became ``supervisor``.

To avoid circular imports (``supervisor_models`` <-> ``supervisor_repair_cycle``
and the supervisor facade), project imports are deferred to the function body.
Only standard-library modules are imported at module level.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

if TYPE_CHECKING:
    from igris.core.supervisor_models import RankSupervisorConfig, SupervisorRun


def run_preflight_phase(
    supervisor: Any,
    run: Optional["SupervisorRun"],
    config: "RankSupervisorConfig",
) -> Tuple["SupervisorRun", Optional[Dict[str, Any]]]:
    """Phase 1: init, git, baseline, smoke, assignment routing, mission plan.

    Returns (run, None) when blocked or cancelled, (run, ctx) on success.
    ctx keys: mission_plan, stage_statuses, assignment_decision, restart_command.
    """
    # Deferred imports to avoid circular imports at module load time.
    from igris.core.supervisor_models import (
        RankSupervisorConfig,
        SupervisorRun,
        _command_detail,
    )
    from igris.core.supervisor_analysis import (
        _allow_unrelated_vastai_baseline_failures,
        _baseline_failure_is_transient,
        _baseline_sanity_targets,
        _delta_baseline_failures,
        _diff_vs_main_is_empty,
        _extract_failed_pytest_nodes,
        _get_main_sha,
        _load_known_baseline_failures,
        _load_valid_baseline_cache,
        _save_baseline_cache,
        _save_known_baseline_failures,
    )

    # AssignmentRouter — lazy import to avoid circular deps at module load.
    _assignment_router_available = False
    AssignmentRouter: Any = None
    AssignmentRequest: Any = None
    try:
        from igris.core.assignment_router import (
            AssignmentRequest as _AssignmentRequest,
            AssignmentRouter as _AssignmentRouter,
        )
        AssignmentRouter = _AssignmentRouter
        AssignmentRequest = _AssignmentRequest
        _assignment_router_available = True
    except ImportError:
        pass

    run = run or SupervisorRun(run_id=uuid.uuid4().hex[:12], rank_id=config.rank_id)
    supervisor._configure_run_tracking(run, config)
    run.add("start", "running", "Supervisor started", dry_run=config.dry_run)

    # Hard dependency gate — fail fast if critical runtime deps missing (#525)
    try:
        from igris.core.dependency_checker import check_runtime_deps
        dep_result = check_runtime_deps()
        if dep_result.blocking_missing:
            run.add(
                "dependency_skip",
                "blocked",
                f"Critical runtime dependencies missing — mission aborted: {dep_result.blocking_missing}",
                missing=dep_result.blocking_missing,
                reason="critical dependencies missing — mission aborted",
            )
            return supervisor._blocked(
                run,
                "dependency_skip",
                f"Missing critical runtime deps: {dep_result.blocking_missing}",
            ), None
        if dep_result.warning_missing:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Non-blocking runtime deps missing (run continues): %s",
                dep_result.warning_missing,
            )
            run.add(
                "runtime_deps_check",  # distinct phase — not issue dependency_check
                "warning",
                f"Non-blocking runtime deps missing: {dep_result.warning_missing}",
                missing=dep_result.warning_missing,
            )
    except Exception:
        pass  # non-blocking if checker fails
    # Validate API escalation helper config at run start so problems are
    # visible immediately rather than discovered mid-repair-cycle.
    if config.allow_api_escalation and config.max_api_escalations_per_run > 0:
        if not supervisor.backend.api_helper_is_configured():
            run.add(
                "api_escalation_config",
                "not_configured",
                "API escalation is enabled (allow_api_escalation=True) but "
                "IGRIS_API_HELPER_COMMAND is not set. Escalation calls will be "
                "skipped without consuming call budget.",
                allow_api_escalation=config.allow_api_escalation,
                max_api_escalations_per_run=config.max_api_escalations_per_run,
            )
    cancelled = supervisor._cancel_if_requested(run)
    if cancelled is not None:
        return cancelled, None
    restart_command = config.service_restart_command
    if config.defer_service_restart and restart_command:
        run.add(
            "service_restart",
            "deferred",
            "Service restart deferred because this supervised run is owned by the API process.",
            command=restart_command,
        )
        restart_command = ""

    status = supervisor.backend.git_status()
    run.add("git_status", "success" if status.success else "failure", _command_detail(status))
    cancelled = supervisor._cancel_if_requested(run)
    if cancelled is not None:
        return cancelled, None
    if not status.success:
        return supervisor._blocked(run, "infrastructure_bug", "Unable to read git status"), None
    # Ignore untracked files (lines starting with "??") — they don't conflict with
    # git checkout/merge and are often leftover artefacts from previous runs.
    tracked_dirty = "\n".join(
        line for line in status.output.splitlines() if line and not line.startswith("??")
    ).strip()
    if tracked_dirty:
        return supervisor._blocked(run, "workspace_dirty", "Workspace is not clean"), None

    # Issue #615 — pre-run dependency validator
    if config.issue_number:
        try:
            from igris.core.dependency_checker import DependencyChecker
            _dep_checker = DependencyChecker(str(supervisor.project_root))
            _dep_ok, _dep_unsat = _dep_checker.check(config.issue_number)
            run.add(
                "dependency_check",
                "satisfied" if _dep_ok else "blocked",
                f"Issue #{config.issue_number}: deps {'all satisfied' if _dep_ok else f'unsatisfied: {_dep_unsat}'}",
                issue_number=config.issue_number,
                unsatisfied=_dep_unsat,
            )
            if not _dep_ok:
                return supervisor._blocked(
                    run,
                    "dependency_not_satisfied",
                    f"Issue #{config.issue_number} has unsatisfied dependencies: {_dep_unsat}. "
                    "Close or merge dependent issues first.",
                ), None
        except Exception as _dep_exc:
            # Dep check is best-effort: log but never block on error
            run.add("dependency_check", "error", f"dep check error (non-fatal): {_dep_exc}")

    head = supervisor.backend.git_log_head()
    run.add("git_head", "success" if head.success else "failure", _command_detail(head))
    head_sha = str((head.output or "").strip().split()[0] if head.success and (head.output or "").strip() else "")

    cache_hit = (
        _load_valid_baseline_cache(
            str(supervisor.project_root), head_sha,
            force_revalidate=config.force_revalidate_baseline,
        )
        if head_sha else None
    )
    if config.force_revalidate_baseline:
        run.add("baseline_revalidation", "triggered",
                "Baseline cache bypassed due to force_revalidate_baseline=True",
                reason="force_revalidate")
    if cache_hit:
        run.add(
            "baseline_tests",
            "skipped",
            "Reusing cached baseline result for current HEAD.",
            head_sha=head_sha,
            checked_at=float(cache_hit.get("checked_at", 0.0) or 0.0),
            policy=str(cache_hit.get("policy", "strict")),
        )
    else:
        baseline_targets = _baseline_sanity_targets(str(supervisor.project_root))
        run.add(
            "baseline_tests",
            "running",
            "Running baseline sanity pytest",
            timeout_seconds=config.test_timeout_seconds,
            exclude_slow=True,
            targets=baseline_targets,
        )
        baseline = supervisor.backend.run_tests(
            baseline_targets or None,
            timeout=config.test_timeout_seconds,
            hard_cap=config.test_hard_cap_seconds,
            exclude_slow=True,
        )
        run.add("baseline_tests", "success" if baseline.success else "failure", _command_detail(baseline))
        cancelled = supervisor._cancel_if_requested(run)
        if cancelled is not None:
            return cancelled, None
        if not baseline.success:
            run.add(
                "baseline_diagnostics",
                "running",
                "Running first-failure pytest diagnostics",
                timeout_seconds=min(config.test_timeout_seconds, 180),
            )
            diagnostics = supervisor.backend.run_test_diagnostics(
                timeout=min(config.test_timeout_seconds, 180),
            )
            run.add(
                "baseline_diagnostics",
                "success" if diagnostics.success else "failure",
                _command_detail(diagnostics),
            )
            if _allow_unrelated_vastai_baseline_failures(config.goal, baseline, diagnostics):
                run.add(
                    "baseline_gate",
                    "warning",
                    "Proceeding despite unrelated baseline failures in VastAI test suite",
                    policy="allow_unrelated_vastai_baseline_failures",
                )
                if head_sha:
                    try:
                        _save_baseline_cache(str(supervisor.project_root), head_sha, policy="allow_unrelated_vastai")
                    except OSError:
                        pass
            elif _baseline_failure_is_transient(baseline, diagnostics):
                return supervisor._blocked(run, "infra_timeout", "Baseline tests timed out or transient infra error"), None
            else:
                # Issue #626 — delta baseline: only block on NEW failures, not pre-existing ones.
                _diag_text = "\n".join([
                    diagnostics.output or "", diagnostics.error or "",
                ]) if diagnostics else ""
                _branch_failures = _extract_failed_pytest_nodes(
                    "\n".join([baseline.output or "", baseline.error or "", _diag_text])
                )
                _main_sha = _get_main_sha(str(supervisor.project_root))
                _known = _load_known_baseline_failures(str(supervisor.project_root), _main_sha) if _main_sha else None

                if _known is not None:
                    # We have a record of pre-existing failures — compute delta.
                    _delta = _delta_baseline_failures(_branch_failures, _known)
                    if not _delta:
                        # All failures are pre-existing — proceed.
                        run.add(
                            "baseline_gate", "warning",
                            f"All {len(_branch_failures)} baseline failure(s) are pre-existing on "
                            f"main ({_main_sha[:8]}) — proceeding.",
                            policy="preexisting_failures",
                            preexisting_count=len(_branch_failures),
                            delta_count=0,
                        )
                        if head_sha:
                            try:
                                _save_baseline_cache(
                                    str(supervisor.project_root), head_sha,
                                    policy="preexisting_failures",
                                )
                            except OSError:
                                pass
                    else:
                        return supervisor._blocked(
                            run, "pytest_failure",
                            f"Baseline tests introduced {len(_delta)} new failure(s) "
                            f"not present on main: {_delta[:5]}",
                        ), None
                elif _main_sha and (head_sha == _main_sha or _diff_vs_main_is_empty(str(supervisor.project_root), _main_sha)):
                    # Running on main itself (or branch identical to main) — record as pre-existing.
                    _save_known_baseline_failures(str(supervisor.project_root), _main_sha, _branch_failures)
                    run.add(
                        "baseline_gate", "warning",
                        f"Recorded {len(_branch_failures)} pre-existing failure(s) for "
                        f"main {_main_sha[:8]} — proceeding without blocking.",
                        policy="recording_preexisting_failures",
                        known_count=len(_branch_failures),
                    )
                    if head_sha:
                        try:
                            _save_baseline_cache(
                                str(supervisor.project_root), head_sha,
                                policy="preexisting_failures",
                            )
                        except OSError:
                            pass
                else:
                    # Unknown failures on a diverged branch — block conservatively.
                    return supervisor._blocked(run, "pytest_failure", "Baseline tests failed"), None
        elif head_sha:
            try:
                _save_baseline_cache(str(supervisor.project_root), head_sha, policy="strict")
            except OSError:
                pass

    run.add("baseline_smoke", "running", "Running baseline smoke")
    smoke = supervisor.backend.smoke(config.required_smoke_endpoints, restart_command)
    run.add("baseline_smoke", "success" if smoke.success else "failure", _command_detail(smoke))
    cancelled = supervisor._cancel_if_requested(run)
    if cancelled is not None:
        return cancelled, None
    if not smoke.success:
        return supervisor._blocked(run, "infrastructure_bug", "Baseline smoke failed"), None

    # Consult failure memory before any attempt — surface historical risk
    # so the operator can see early if similar goals have failed before.
    failure_risk = supervisor._failure_memory.check(config.goal)
    run.add(
        "failure_memory",
        "checked",
        f"Failure memory check: risk={failure_risk.risk_level} "
        f"similar_failures={failure_risk.similar_count}",
        risk_level=failure_risk.risk_level,
        similar_count=failure_risk.similar_count,
        dominant_failure=failure_risk.dominant_failure,
        notes=failure_risk.notes,
    )

    # Pre-flight assignment routing: decide role/profile/strategy before any attempt.
    assignment_decision: Optional[Any] = None
    if _assignment_router_available:
        try:
            _outcomes_path = str(Path(supervisor.project_root) / ".igris" / "assignment_outcomes.json")
            _router = AssignmentRouter(outcomes_path=_outcomes_path)
            # Merge prior capability_signals (from last failed run, passed by
            # the watchdog) with any signals already accumulated in this run.
            # This preserves no_diff_repair / reasoning_timeout counts across
            # watchdog cycles so the router can escalate to hard_debugging
            # (→ gpu_reasoning → VastAI) after repeated cross-run failures.
            _merged_signals: Dict[str, int] = dict(config.prior_capability_signals)
            for _sig, _cnt in run.capability_signals.items():
                _merged_signals[_sig] = _merged_signals.get(_sig, 0) + _cnt
            _req = AssignmentRequest(
                goal_text=config.goal,
                risk_level="medium",
                failure_class="",
                capability_signals=_merged_signals,
                prior_attempts=config.prior_attempts,
                local_model_available=True,
                budget_remaining_usd=float(config.max_api_budget_usd) or 10.0,
                required_tests=list(config.targeted_tests),
                is_repair=False,
                outcomes_path=_outcomes_path,
            )
            assignment_decision = _router.decide(_req)
            forced_planner_profile = str(
                os.getenv("IGRIS_ROLE_PLANNER_PROFILE", "mini_execution")
            ).strip() or "mini_execution"
            if (
                assignment_decision is not None
                and str(getattr(assignment_decision, "task_type", "")) == "memory_system"
                and forced_planner_profile
            ):
                prev_profile = str(getattr(assignment_decision, "preferred_profile", "") or "")
                if prev_profile != forced_planner_profile:
                    assignment_decision.preferred_profile = forced_planner_profile
                    run.add(
                        "assignment_routing_override",
                        "success",
                        f"Planner profile override applied for initial rank path: "
                        f"{prev_profile or 'unset'} -> {forced_planner_profile}",
                        task_type=str(getattr(assignment_decision, "task_type", "")),
                        previous_profile=prev_profile,
                        forced_profile=forced_planner_profile,
                    )
            if assignment_decision is not None:
                run.add(
                    "assignment_routing",
                    "success",
                    (
                        f"role={assignment_decision.agent_role} "
                        f"type={assignment_decision.task_type} "
                        f"profile={assignment_decision.preferred_profile} "
                        f"strategy={assignment_decision.execution_strategy} "
                        f"p={assignment_decision.estimated_success_probability:.2f} "
                        f"history={assignment_decision.history_matches}"
                    ),
                    **assignment_decision.to_dict(),
                )
        except Exception as _exc:
            run.add("assignment_routing", "skipped", f"AssignmentRouter error: {_exc}")

    mission_plan = supervisor._build_mission_plan(config)
    stage_statuses = supervisor._init_stage_statuses(mission_plan)
    run.add(
        "mission_plan",
        "success",
        "Mission execution strategy planned.",
        mode=mission_plan.mode,
        stage_ids=[stage.stage_id for stage in mission_plan.stages],
    )

    force_preemptive_decomposition = (
        str(os.getenv("IGRIS_FORCE_PREEMPTIVE_DECOMPOSITION", "true")).strip().lower() != "false"
    )
    if (
        force_preemptive_decomposition
        and supervisor._goal_needs_preflight_decomposition(config.goal)
        and config.allow_auto_subissues
        and not config.dry_run
        and config.autochain_depth <= supervisor._MAX_AUTOCHAIN_DEPTH
    ):
        run.add(
            "mission_planning",
            "decomposition_required",
            "Pre-emptive decomposition for large mission (policy shortcut) before long reasoning loops.",
        )
        decomposition = supervisor._ask_igris_decompose(run, config)
        return supervisor._blocked_decomposition_required(
            run,
            "preemptive_large_mission",
            "Large mission routed to decomposition-first execution policy.",
            decomposition,
            config=config,
            mission_plan=mission_plan,
            stage_statuses=stage_statuses,
        ), None

    # Pre-flight planning: read-only scope analysis before first attempt.
    # If the planning pass recommends decomposition, block proactively rather
    # than discovering the same thing after 3 failed repair cycles.
    if config.enable_mission_planning or supervisor._goal_needs_preflight_decomposition(config.goal):
        scope = supervisor._plan_mission(run, config)
        if scope and scope.get("decomposition_recommended"):
            run.add(
                "mission_planning",
                "decomposition_required",
                f"Pre-flight planning recommends decomposition before any attempt: "
                f"{scope.get('decomposition_reason', 'mission too large for single attempt')}",
            )
            decomposition = supervisor._ask_igris_decompose(run, config)
            return supervisor._blocked_decomposition_required(
                run,
                "pre_flight_planning",
                (
                    f"Pre-flight planning detected scope too large for single attempt: "
                    f"{scope.get('decomposition_reason', 'see mission_scope in report')}"
                ),
                decomposition,
                config=config,
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
            ), None

    return run, {
        "mission_plan": mission_plan,
        "stage_statuses": stage_statuses,
        "assignment_decision": assignment_decision,
        "restart_command": restart_command,
    }
