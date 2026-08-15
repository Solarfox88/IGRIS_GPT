"""Extracted rank execution loop for the self-repair supervisor.

This module contains :func:`run_rank_loop`, the main rank attempt loop and
finalization phase previously inlined as
``SelfRepairSupervisor._run_rank_loop``. The logic is identical — only the
``self`` receiver has been replaced with an explicit ``supervisor`` parameter
so the function can live outside the class.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from igris.core.acceptance_gate import check_acceptance_evidence
from igris.core.supervisor_models import (
    REPAIRABLE_FAILURES,
    CommandResult,
    MissionPlan,
    RankSupervisorConfig,
    SupervisorRun,
    _command_detail,
    _failure_error_code,
)
from igris.core.supervisor_analysis import (
    _baseline_sanity_targets,
    _has_immediately_dangerous_diff,
    _has_ui_surface_change,
    _is_llm_provider_unavailable,
    _touches_rank_ui_contract_files,
    classify_failure,
)


def run_rank_loop(
    supervisor: Any,
    run: SupervisorRun,
    config: RankSupervisorConfig,
    *,
    mission_plan: MissionPlan,
    stage_statuses: Dict[str, Dict[str, Any]],
    assignment_decision: Optional[Any],
    restart_command: str,
) -> SupervisorRun:
    """Phase 2: rank attempt loop and finalization."""
    repair_cycles = 0
    attempt = 1
    attempt_limit = config.max_rank_attempts
    final_validation_extension_used = False
    # Issue #715 — write-first / execution-effectiveness telemetry
    _no_diff_count: int = 0
    _time_to_first_diff_s: Optional[float] = None
    _attempt_start_time: float = time.time()
    _attempt_outcomes: List[str] = []
    _decompose_count: int = 0
    while attempt <= attempt_limit:
        cancelled = supervisor._cancel_if_requested(run, mission_plan=mission_plan, stage_statuses=stage_statuses)
        if cancelled is not None:
            return cancelled
        branch = f"rank-{config.rank_id.lower()}-{int(time.time())}-{attempt}"
        run.branch = branch
        # Always start rank branch from latest main so every run has all committed fixes.
        _pre_checkout = supervisor.backend.checkout_main()
        if not _pre_checkout.success:
            run.add("rank_branch_pre_checkout", "warning", f"Could not checkout main before branch creation: {_command_detail(_pre_checkout)}")
        branch_result = supervisor.backend.create_branch(branch)
        run.add("rank_branch", "success" if branch_result.success else "failure", _command_detail(branch_result), branch=branch)
        cancelled = supervisor._cancel_if_requested(run, mission_plan=mission_plan, stage_statuses=stage_statuses)
        if cancelled is not None:
            return cancelled
        if not branch_result.success:
            return supervisor._blocked(run, "infrastructure_bug", "Could not create rank branch")

        stage_failure = ""
        if mission_plan.mode == "staged":
            reasoning, stage_failure, runtime_refresh_required = supervisor._execute_staged_reasoning(
                run,
                config,
                mission_plan,
                stage_statuses,
            )
            reasoning_status = str(reasoning.get("status", ""))
            stop_reason = str(reasoning.get("stop_reason", ""))
            modified_files = list(reasoning.get("files_modified") or [])
        else:
            supervisor._set_stage_status(
                run,
                stage_statuses,
                "single_stage_execution",
                "running",
                "Running supervised rank reasoning as single stage.",
            )
            _routed_profile = (
                assignment_decision.preferred_profile
                if assignment_decision is not None
                else None
            )
            _routed_task_type = (
                assignment_decision.task_type
                if assignment_decision is not None
                else "code_reasoning"
            )
            max_reasoning_steps = max(40, int(os.getenv("IGRIS_RANK_MAX_STEPS", "120")))
            reasoning_timeout = config.reasoning_timeout_seconds
            # Profile-aware timeout adjustment:
            # Strong cloud models (DeepSeek V4 Pro, GPT-4o) take ~40-60s per step.
            # At 900s limit → only ~18 steps → never enough for full implementation.
            # Boost timeout for strong profiles; cap for local profiles.
            _STRONG_PROFILES = {"strong_execution", "strong_cloud_reasoning", "gpu_reasoning"}
            _LOCAL_PROFILES_SET = {"local_light", "local_coder", "mini_execution"}
            _profile = (_routed_profile or "")
            if _profile in _STRONG_PROFILES:
                # Strong models need more time: env var or 2.5× the base timeout.
                reasoning_timeout = int(os.getenv(
                    "IGRIS_STRONG_REASONING_TIMEOUT_SECONDS",
                    str(max(reasoning_timeout * 3, 2400)),
                ))
            elif supervisor._goal_needs_preflight_decomposition(config.goal) and _profile in _LOCAL_PROFILES_SET:
                # Cap local-profile timeout on large missions — phi4-mini spins without progress.
                reasoning_timeout = min(
                    reasoning_timeout,
                    int(os.getenv("IGRIS_LARGE_MISSION_REASONING_TIMEOUT", "240")),
                )
            # Log the actual adjusted timeout — event was previously logged before
            # the profile-aware adjustment, showing 900s even when strong models
            # would use 2700s. Now logged AFTER adjustment for accurate audit trail.
            run.add(
                "rank_reasoning",
                "running",
                "Running supervised rank reasoning",
                timeout_seconds=reasoning_timeout,
            )
            reasoning = supervisor.backend.run_reasoning(
                config.goal,
                max_steps=max_reasoning_steps,
                initial_context=supervisor._rank_initial_context(config, run=run),
                timeout=reasoning_timeout,
                task_type=_routed_task_type,
                preferred_profile=_routed_profile,
            )
            reasoning_status = str(reasoning.get("status", ""))
            stop_reason = str(reasoning.get("stop_reason", ""))
            modified_files = list(reasoning.get("files_modified") or [])
            runtime_refresh_required = any(
                str(path).startswith("igris/")
                for path in modified_files
            )
            run.add(
                "rank_reasoning",
                reasoning_status,
                reasoning.get("final_summary", ""),
                loop_id=reasoning.get("loop_id", ""),
                stop_reason=stop_reason,
                files_modified=modified_files,
                steps_completed=reasoning.get("steps_completed", 0),
                orchestrator_used=reasoning.get("orchestrator_used", False),
                reasoning_execution_provider=reasoning.get("reasoning_execution_provider", ""),
                reasoning_execution_model=reasoning.get("reasoning_execution_model", ""),
                reasoning_execution_profile=reasoning.get("reasoning_execution_profile", ""),
                execution_provider=reasoning.get("reasoning_execution_provider", ""),
                execution_model=reasoning.get("reasoning_execution_model", ""),
                local_model_available=reasoning.get("local_model_available", False),
            )
            if reasoning_status == "finished":
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "single_stage_execution",
                    "success",
                    "Single-stage reasoning completed.",
                )
            else:
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "single_stage_execution",
                    "failure",
                    f"Single-stage reasoning ended with {reasoning_status}/{stop_reason}.",
                )
                # Short-circuit the full_pytest validation when the reasoning
                # loop itself signals "no_diff_repair" AND produced no files.
                # In that case running 3000+ tests on an unchanged tree is pure
                # waste — the staged path already does this inside
                # _execute_staged_reasoning; we mirror the behaviour here.
                # For other stop reasons (reasoning_timeout, max_steps, blocked…)
                # we leave stage_failure empty so the normal repair → decomposition
                # escalation path is preserved.
                if stop_reason == "no_diff_repair" and not modified_files:
                    stage_failure = "reasoning_loop_blocked"
                    # Record capability signal immediately so the decomposition
                    # decision threshold is still updated even though the normal
                    # classify_failure path (inside `if not failure:`) is skipped.
                    supervisor._record_capability_signal(run, "no_diff_repair")

        ui_visibility_required = supervisor._goal_requires_ui_visibility(config.goal)
        ui_card_contract_goal = supervisor._goal_targets_rank_ui_card(config.goal)
        ui_visibility_changed = supervisor._has_ui_visibility_change(modified_files)
        run.add(
            "rank_reasoning",
            reasoning_status,
            reasoning.get("final_summary", ""),
            loop_id=reasoning.get("loop_id", ""),
            stop_reason=stop_reason,
            files_modified=modified_files,
            steps_completed=reasoning.get("steps_completed", 0),
            orchestrator_used=reasoning.get("orchestrator_used", False),
            reasoning_execution_provider=reasoning.get("reasoning_execution_provider", ""),
            reasoning_execution_model=reasoning.get("reasoning_execution_model", ""),
            reasoning_execution_profile=reasoning.get("reasoning_execution_profile", ""),
            local_model_available=reasoning.get("local_model_available", False),
            ui_visibility_required=ui_visibility_required,
            ui_visibility_changed=ui_visibility_changed,
            mission_orchestration_mode=mission_plan.mode,
        )
        if (
            stage_failure == "reasoning_loop_blocked"
            and stop_reason == "no_diff_repair"
            and not modified_files
        ):
            triggering_signal = supervisor._detect_capability_limit(run)
            if triggering_signal:
                return supervisor._handle_capability_limit(
                    run, triggering_signal, config, mission_plan, stage_statuses,
                    cleanup_workspace=True,
                )
        cancelled = supervisor._cancel_if_requested(run, mission_plan=mission_plan, stage_statuses=stage_statuses)
        if cancelled is not None:
            return cancelled

        if stage_failure == "reasoning_loop_blocked" and stop_reason == "no_diff_repair" and not modified_files:
            diff_stat = CommandResult(True, "")
            diff = CommandResult(True, "")
            run.add("diff_stat", "skipped", "Skipped diff collection after no_diff_repair with no modified files.")
        else:
            diff_stat = supervisor.backend.git_diff_stat()
            diff = supervisor.backend.git_diff()
            run.add("diff_stat", "success" if diff_stat.success else "failure", _command_detail(diff_stat))
        # Issue #715 — track whether this attempt produced any file changes.
        _has_diff_this_attempt: bool = bool(diff_stat.output.strip())
        if _has_diff_this_attempt and _time_to_first_diff_s is None:
            _time_to_first_diff_s = round(time.time() - _attempt_start_time, 1)
        if not _has_diff_this_attempt:
            _no_diff_count += 1
        # Persist the full diff to disk immediately so _complete_rank can
        # recover if the working tree is unexpectedly reverted before the
        # commit (e.g. watchdog cleanup racing during branch transitions).
        if diff_stat.output.strip() and diff.output.strip():
            try:
                _patch_path = Path(supervisor.project_root) / ".igris" / "rank_pending.patch"
                _patch_path.parent.mkdir(parents=True, exist_ok=True)
                _patch_path.write_text(diff.output, encoding="utf-8")
                run.add("diff_patch_saved", "success", str(_patch_path))
            except Exception as _pe:
                run.add("diff_patch_saved", "failure", str(_pe))
        if (
            ui_visibility_required
            and not ui_visibility_changed
            and _has_ui_surface_change(diff.output)
        ):
            ui_visibility_changed = True
            run.add(
                "ui_visibility",
                "success",
                "UI visibility inferred from validated diff paths",
                inferred_from_diff=True,
            )
            if mission_plan.mode == "staged":
                supervisor._track_non_blocking_behavior(
                    run,
                    stage_statuses,
                    "ui_dashboard_change",
                    "ui_visibility_inferred_from_diff",
                    "UI visibility metadata was inferred from diff paths.",
                )
        ui_contract_locked = (
            ui_card_contract_goal
            and ui_visibility_required
            and supervisor._rank_ui_card_contract_satisfied()
            and supervisor._rank_ui_visibility_signal_present()
        )
        if (
            ui_contract_locked
            and _touches_rank_ui_contract_files(diff.output)
            and not _has_ui_surface_change(diff.output)
        ):
            restore = supervisor.backend.restore_dangerous_diff()
            run.add(
                "rank_restore",
                "success" if restore.success else "failure",
                "Protected UI contract files were modified despite already satisfied objective.",
            )
            if not restore.success:
                return supervisor._blocked(
                    run,
                    "infrastructure_bug",
                    "Could not restore unsupported edits to satisfied UI contract files",
                )
            return supervisor._complete_noop(
                run,
                completion_mode="already_satisfied",
                runtime_refresh_required=runtime_refresh_required,
                detail=(
                    "Restored unsupported edits to satisfied UI contract files; "
                    "completed as verified no-op."
                ),
                post_merge_smoke=False,
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
            )
        targeted = CommandResult(True, "Targeted tests skipped")
        full = CommandResult(True, "Full pytest skipped")
        final_smoke = CommandResult(True, "Final smoke skipped")
        failure = stage_failure or ""
        if not failure:
            # Issue #731 — gate is only active when enable_semantic_gate=True.
            # Disabling the semantic gate (e.g. in tests) skips both the
            # pre-apply quality gate and the post-reasoning acceptance gate.
            should_gate = (
                config.enable_semantic_gate
                and (reasoning_status == "finished" or stop_reason == "finish")
                and (bool(modified_files) or bool((diff.output or "").strip()))
            )
            if should_gate:
                run.add("quality_gate_preapply", "running", "Running pre-apply quality gate")
                gate_ok, gate_reasons = supervisor._preapply_quality_gate(config.goal, diff.output, modified_files)
                if gate_ok:
                    run.add("quality_gate_preapply", "success", "Pre-apply quality gate passed")
                else:
                    failure = "semantic_incomplete"
                    run.add(
                        "quality_gate_preapply",
                        "failure",
                        "Pre-apply quality gate failed",
                        reasons=gate_reasons,
                        error_code=_failure_error_code("semantic_incomplete"),
                    )
            else:
                run.add(
                    "quality_gate_preapply",
                    "skipped",
                    "Skipped pre-apply quality gate (no candidate patch from finished reasoning).",
                )

        if failure:
            run.add(
                "validation_short_circuit",
                "running",
                f"Skipping attempt validation because required stage failed: {failure}",
            )
            run.add("targeted_tests", "skipped", "Skipped because a required stage failed before validation.")
            run.add("full_pytest", "skipped", "Skipped because a required stage failed before validation.")
            run.add("smoke", "skipped", "Skipped because a required stage failed before validation.")
            if "targeted_tests" in stage_statuses:
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "targeted_tests",
                    "skipped",
                    "Skipped because a required implementation stage failed.",
                )
            if "full_pytest" in stage_statuses:
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "full_pytest",
                    "skipped",
                    "Skipped because a required implementation stage failed.",
                )
        elif _has_immediately_dangerous_diff(diff.output):
            # Dangerous tokens (.env, .venv) or structural deletions (def create_app,
            # class) — restore without running tests as these would definitely break
            # the app regardless of what else the model added.
            run.add("safety", "blocked", "Immediately dangerous diff detected (tokens or structural deletion)")
            supervisor.backend.restore_dangerous_diff()
            failure = "destructive_diff"
        else:
            if config.targeted_tests:
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "targeted_tests",
                    "running",
                    "Running targeted pytest validation.",
                )
                run.add(
                    "targeted_tests",
                    "running",
                    "Running targeted pytest",
                    targets=" ".join(config.targeted_tests),
                    timeout_seconds=config.test_timeout_seconds,
                )
                targeted = supervisor.backend.run_tests(
                    config.targeted_tests,
                    timeout=config.test_timeout_seconds,
                    hard_cap=config.test_hard_cap_seconds,
                )
            else:
                targeted = CommandResult(True, "No targeted tests configured")
                if mission_plan.mode == "staged" and "targeted_tests" in stage_statuses:
                    supervisor._set_stage_status(
                        run,
                        stage_statuses,
                        "targeted_tests",
                        "skipped",
                        "No targeted tests configured for this mission.",
                        no_op=True,
                    )
            supervisor._set_stage_status(
                run,
                stage_statuses,
                "full_pytest",
                "running",
                "Running full pytest validation.",
            )
            full_targets: Optional[List[str]] = None
            full_validation_mode = "full"
            # Structural policy: during local supervised execution (no PR/merge),
            # avoid paying full-suite cost on every attempt. Use a stable
            # validation suite focused on service health + rank contract.
            if not config.allow_github_pr and not config.allow_merge_if_green:
                full_targets = _baseline_sanity_targets(str(supervisor.project_root))
                full_validation_mode = "sanity"
            run.add(
                "full_pytest",
                "running",
                "Running full pytest (-m 'not slow')" if full_validation_mode == "full" else "Running validation sanity suite",
                timeout_seconds=config.test_timeout_seconds,
                exclude_slow=True,
                targets=full_targets or [],
                validation_mode=full_validation_mode,
            )
            full = supervisor.backend.run_tests(
                full_targets or None,
                timeout=config.test_timeout_seconds,
                hard_cap=config.test_hard_cap_seconds,
                exclude_slow=True,
            )
            run.add("smoke", "running", "Running final smoke")
            final_smoke = supervisor.backend.smoke(config.required_smoke_endpoints, restart_command)
            run.add("targeted_tests", "success" if targeted.success else "failure", _command_detail(targeted))
            run.add("full_pytest", "success" if full.success else "failure", _command_detail(full))
            run.add("smoke", "success" if final_smoke.success else "failure", _command_detail(final_smoke))
            if config.targeted_tests:
                supervisor._set_stage_status(
                    run,
                    stage_statuses,
                    "targeted_tests",
                    "success" if targeted.success else "failure",
                    "Targeted tests passed." if targeted.success else "Targeted tests failed.",
                )
            supervisor._set_stage_status(
                run,
                stage_statuses,
                "full_pytest",
                "success" if full.success else "failure",
                "Full pytest passed." if full.success else "Full pytest failed.",
            )
        already_satisfied_noop = (
            not failure
            and supervisor._ui_noop_completion_eligible(
                config,
                diff_stat,
                targeted,
                full,
                final_smoke,
            )
        )
        if already_satisfied_noop:
            return supervisor._complete_noop(
                run,
                completion_mode="already_satisfied",
                runtime_refresh_required=runtime_refresh_required,
                detail="Rank objective already satisfied; completed as verified no-op.",
                post_merge_smoke=final_smoke.success,
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
            )
        required_stages_complete = supervisor._required_stages_green(
            stage_statuses,
            exclude_stage_ids={"pr_ci_merge", "post_merge_runtime", "final_report"},
        )
        staged_noop_completion = (
            mission_plan.mode == "staged"
            and not failure
            and not diff_stat.output.strip()
            and targeted.success
            and full.success
            and final_smoke.success
            and required_stages_complete
        )
        if staged_noop_completion:
            return supervisor._complete_noop(
                run,
                completion_mode="already_satisfied",
                runtime_refresh_required=runtime_refresh_required,
                detail="All required staged mission phases were already satisfied; completed as verified no-op.",
                post_merge_smoke=final_smoke.success,
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
        )
        rank_passed = supervisor._rank_passed(reasoning, diff_stat, targeted, full, final_smoke)
        if not failure:
            if rank_passed:
                if ui_visibility_required and not ui_visibility_changed:
                    failure = "missing_ui_visibility"
            else:
                failure = classify_failure(reasoning, diff.output, targeted, full, final_smoke)
                # Record reasoning_timeout signal when the model timed out, hit
                # budget, or explicitly refused the task — all indicate capability
                # limit that should trigger decomposition after N occurrences.
                if failure == "reasoning_loop_blocked" and stop_reason in {
                    "reasoning_timeout", "budget_exceeded", "blocked",
                }:
                    supervisor._record_capability_signal(run, "reasoning_timeout")
                if failure == "reasoning_loop_blocked" and stop_reason == "no_diff_repair":
                    supervisor._record_capability_signal(run, "no_diff_repair")
        # Record pytest_hang when the full test subprocess was killed for
        # producing no output (idle timeout) — repeated hangs indicate the
        # model's change consistently breaks the test suite in a way it
        # cannot self-repair.
        if not full.success and "Command killed:" in (full.error or ""):
            supervisor._record_capability_signal(run, "pytest_hang")
        triggering_signal_early = supervisor._should_fast_track_capability_limit(
            run,
            failure,
        )
        if triggering_signal_early:
            run.add(
                "capability_ceiling",
                "detected",
                (
                    "Capability limit reached during active attempt; "
                    "fast-tracking decomposition before exhausting repair budget."
                ),
                triggering_signal=triggering_signal_early,
                capability_signals=dict(run.capability_signals),
                failure_class=failure,
            )
            return supervisor._handle_capability_limit(
                run,
                triggering_signal_early,
                config,
                mission_plan,
                stage_statuses,
                cleanup_workspace=True,
            )
        if not failure and mission_plan.mode == "staged" and not required_stages_complete:
            failure = "reasoning_loop_blocked"
            run.add(
                "stage_gate",
                "blocked",
                "Required mission stage not completed; refusing completed status.",
            )
        reasoning_text = "\n".join(
            str(reasoning.get(key, ""))
            for key in ("final_summary", "error", "stop_reason")
        )
        if failure == "infrastructure_bug" and _is_llm_provider_unavailable(reasoning_text):
            # LLM unavailability is a structural capability wall — no repair cycle
            # will succeed without a working model.  Decompose immediately so the
            # auto-chain can hand the task to a sub-mission that may reach a cloud
            # provider, rather than blocking the entire run indefinitely.
            supervisor._record_capability_signal(run, "reasoning_timeout")
            decomposition = supervisor._ask_igris_decompose(run, config)
            return supervisor._blocked_decomposition_required(
                run,
                "reasoning_timeout",
                "LLM unavailable — decomposing to sub-mission for capable model",
                decomposition,
                config=config,
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
                cleanup_workspace=True,
            )

        if not failure and rank_passed:
            completion_mode = "direct"
            if reasoning_status != "finished" or stop_reason != "finish":
                completion_mode = "verified_diff"
                run.add(
                    "completion",
                    "degraded",
                    "Rank completed by verification after reasoning did not finish cleanly",
                    mode=completion_mode,
                    stop_reason=stop_reason,
                )
                if mission_plan.mode == "staged":
                    stage_id = "single_stage_execution"
                    supervisor._track_non_blocking_behavior(
                        run,
                        stage_statuses,
                        stage_id,
                        "verified_diff_completion",
                        "Completed by validated diff despite non-clean reasoning stop.",
                    )

            # --- Semantic acceptance gate ---
            # Verify the diff is a genuine implementation, not a stub.
            if config.enable_semantic_gate:
                # When targeted tests pass, include their file paths so the gate
                # knows test coverage exists even if a repair cycle only touched
                # the implementation file (tests were already written earlier and
                # restored workspace left them absent from files_modified).
                gate_files = list(modified_files)
                if targeted.success and config.targeted_tests:
                    for tf in config.targeted_tests:
                        if tf not in gate_files:
                            gate_files.append(tf)
                acceptance = check_acceptance_evidence(
                    config.goal,
                    diff.output,
                    gate_files,
                )
                # Store on the run object so it survives any subsequent run.report overwrites.
                run.acceptance_evidence = {
                    "passed": acceptance.passed,
                    "found_evidence": acceptance.found_evidence,
                    "missing_evidence": acceptance.missing_evidence,
                    "required_endpoints": acceptance.required_endpoints,
                }
                if not acceptance.passed:
                    run.add(
                        "semantic_check",
                        "incomplete",
                        "Mission acceptance gate failed: implementation appears to be a stub. "
                        + "; ".join(acceptance.missing_evidence),
                        missing_evidence=acceptance.missing_evidence,
                        found_evidence=acceptance.found_evidence,
                        required_endpoints=acceptance.required_endpoints,
                    )
                    failure = "semantic_incomplete"
                    rank_passed = False
                else:
                    run.add(
                        "semantic_check",
                        "passed",
                        "Mission acceptance gate passed.",
                        found_evidence=acceptance.found_evidence,
                        required_endpoints=acceptance.required_endpoints,
                    )

            if rank_passed:
                supervisor._persist_assignment_outcome(run, supervisor.project_root, assignment_decision)
                _done = supervisor._complete_rank(
                    run,
                    config,
                    branch,
                    completion_mode=completion_mode,
                    runtime_refresh_required=runtime_refresh_required,
                    mission_plan=mission_plan,
                    stage_statuses=stage_statuses,
                )
                supervisor._maybe_autoselect_next_roadmap(run, config)
                return _done

        run.failure_class = failure
        run.add("failure", "classified", failure, error_code=_failure_error_code(failure))
        # Issue #715 — record per-attempt outcome for telemetry.
        _attempt_outcomes.append(
            "no_diff" if not _has_diff_this_attempt else (failure or "failed")
        )
        if failure not in REPAIRABLE_FAILURES or repair_cycles >= config.max_repair_cycles:
            triggering_signal = supervisor._detect_capability_limit(run)
            if triggering_signal:
                return supervisor._handle_capability_limit(
                    run, triggering_signal, config, mission_plan, stage_statuses,
                    cleanup_workspace=True,
                )
            # Issue #715 — no_diff_terminal_report: surface when attempts consistently
            # produced no file changes so callers know the agent is structurally stuck.
            if _no_diff_count >= 1:
                run.add(
                    "no_diff_terminal_report",
                    "blocked",
                    f"Attempt(s) produced no diff (no_diff_count={_no_diff_count}). "
                    "Stopping to avoid further wasted cycles.",
                    no_diff_count=_no_diff_count,
                    attempt=attempt,
                )
            _telemetry = supervisor._build_telemetry_fragment(
                _time_to_first_diff_s, _no_diff_count, _decompose_count,
                _attempt_outcomes, attempt,
            )
            _done = supervisor._blocked(
                run,
                failure,
                "Rank failed and repair budget is exhausted or not repairable",
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
                cleanup_workspace=True,
            )
            _done.report.update(_telemetry)
            return _done

        repair_cycles += 1
        run.repair_cycles_used = repair_cycles
        if not supervisor._repair_cycle(
            run,
            config,
            failure,
            repair_cycles,
            preserve_validated_progress=mission_plan.mode == "staged",
            stage_statuses=stage_statuses if mission_plan.mode == "staged" else None,
        ):
            triggering_signal = supervisor._detect_capability_limit(run)
            if triggering_signal:
                return supervisor._handle_capability_limit(
                    run, triggering_signal, config, mission_plan, stage_statuses,
                    cleanup_workspace=True,
                )
            return supervisor._blocked(
                run,
                failure,
                "Repair cycle failed validation",
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
                cleanup_workspace=True,
            )
        if attempt == attempt_limit:
            if repair_cycles < config.max_repair_cycles:
                attempt_limit += 1
                run.add(
                    "rank_attempt_extension",
                    "running",
                    "Extending rank attempts after successful repair on final configured attempt.",
                    attempt_limit=attempt_limit,
                    repair_cycles_used=repair_cycles,
                )
            elif not final_validation_extension_used:
                attempt_limit += 1
                final_validation_extension_used = True
                run.add(
                    "rank_attempt_extension",
                    "running",
                    "Granting one final validation attempt after successful repair at repair budget limit.",
                    attempt_limit=attempt_limit,
                    repair_cycles_used=repair_cycles,
                    final_validation_only=True,
                )
        attempt += 1

    triggering_signal = supervisor._detect_capability_limit(run)
    if triggering_signal:
        supervisor._persist_assignment_outcome(run, supervisor.project_root, assignment_decision)
        return supervisor._handle_capability_limit(
            run, triggering_signal, config, mission_plan, stage_statuses,
            cleanup_workspace=True,
        )
    supervisor._persist_assignment_outcome(run, supervisor.project_root, assignment_decision)
    _done = supervisor._blocked(
        run,
        run.failure_class or "max_rank_attempts",
        "Rank attempts exhausted",
        mission_plan=mission_plan,
        stage_statuses=stage_statuses,
        cleanup_workspace=True,
    )
    # Issue #715 — append execution-effectiveness telemetry to the final report.
    _done.report.update(supervisor._build_telemetry_fragment(
        _time_to_first_diff_s, _no_diff_count, _decompose_count,
        _attempt_outcomes, max(attempt - 1, 1),
    ))
    supervisor._maybe_autoselect_next_roadmap(run, config)
    return _done
