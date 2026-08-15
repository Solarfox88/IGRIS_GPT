"""Small helpers for supervisor repair-cycle bookkeeping.

Behavior-preserving extraction from ``self_repair_supervisor`` (#1107).
These helpers are intentionally narrow and deterministic.

This module also hosts the extracted ``repair_cycle`` function (#1371), which
contains the full repair-cycle orchestration logic previously inlined in
``SelfRepairSupervisor._repair_cycle``.  The supervisor delegates to
``repair_cycle`` via a thin wrapper so the behavior remains identical.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from igris.core.supervisor_models import RankSupervisorConfig, SupervisorRun


def _event_fields(event: Any) -> Tuple[str, str, str, Dict[str, Any]]:
    """Normalize event access across SupervisorEvent objects and dict payloads.

    Repair diagnostics are assembled from a mix of in-memory event objects and
    serialized event dicts loaded from persisted runs.  Normalizing the fields in
    one place keeps the repair-cycle context stable across resume/cancel paths.
    """

    if isinstance(event, dict):
        data = event.get("data") or {}
        return (
            str(event.get("phase", "") or ""),
            str(event.get("status", "") or ""),
            str(event.get("detail", "") or ""),
            data if isinstance(data, dict) else {},
        )

    data = getattr(event, "data", {}) or {}
    return (
        str(getattr(event, "phase", "") or ""),
        str(getattr(event, "status", "") or ""),
        str(getattr(event, "detail", "") or ""),
        data if isinstance(data, dict) else {},
    )


def _event_data(event: Any) -> Dict[str, Any]:
    if isinstance(event, dict):
        data = event.get("data")
        if isinstance(data, dict):
            return data
        return event
    if hasattr(event, "data"):
        data = getattr(event, "data") or {}
        return data if isinstance(data, dict) else {}
    return {}


def collect_repair_diagnostics(run: Any) -> Dict[str, Any]:
    """Collect prior-attempt diagnostics for repair-context injection."""
    diag: Dict[str, Any] = {
        "repair_cycles_used": int(getattr(run, "repair_cycles_used", 0) or 0),
        "same_failure_count": int(getattr(run, "same_failure_count", 0) or 0),
    }

    events = getattr(run, "events", []) or []
    if not events:
        return diag

    for ev in reversed(events):
        phase, _, detail, _ = _event_fields(ev)
        if phase in ("rank_reasoning", "repair_reasoning"):
            stop = _event_data(ev).get("stop_reason", "")
            if stop or detail:
                diag["previous_stop_reason"] = str(stop)[:200] if stop else ""
                diag["previous_reasoning_summary"] = str(detail)[:300]
                break

    for ev in reversed(events):
        phase, status, detail, _ = _event_fields(ev)
        if phase in ("full_pytest", "targeted_tests", "baseline_tests") and status == "failure":
            diag["previous_pytest_failure"] = str(detail or "")[:500]
            break

    modified_files: List[str] = []
    for ev in reversed(events):
        fm = _event_data(ev).get("files_modified")
        if fm:
            modified_files = list(fm)[:10]
            break
    if modified_files:
        diag["previous_files_modified"] = modified_files

    for ev in reversed(events):
        phase, _, _, _ = _event_fields(ev)
        if phase == "repair_strategy_decision":
            ev_data = _event_data(ev)
            diag["previous_repair_strategy"] = {
                "task_type": ev_data.get("task_type", ""),
                "profile": ev_data.get("profile", ""),
                "notes": str(ev_data.get("notes", ""))[:200],
            }
            break

    for ev in reversed(events):
        phase, status, detail, _ = _event_fields(ev)
        if phase == "mbop_phase9_quality_gate":
            ev_data = _event_data(ev)
            diag["previous_quality_gate_status"] = str(status)[:50]
            diag["previous_quality_gate_reason"] = str(detail)[:200]
            diag["previous_quality_gate_failed_checks"] = ev_data.get("stub_patterns", [])[:5]
            break

    for ev in reversed(events):
        phase, _, _, _ = _event_fields(ev)
        if phase == "mbop_phase10_satisfaction_gate":
            ev_data = _event_data(ev)
            missing = ev_data.get("criteria_missing", [])
            covered = ev_data.get("criteria_covered", [])
            checked = ev_data.get("criteria_checked", [])
            diag["previous_satisfaction_score"] = f"{len(covered)}/{len(checked)}" if checked else "unknown"
            diag["previous_satisfaction_missing_acs"] = [str(ac)[:100] for ac in missing[:5]]
            diag["previous_satisfaction_covered_acs"] = [str(ac)[:100] for ac in covered[:5]]
            break

    for ev in reversed(events):
        phase, _, _, _ = _event_fields(ev)
        if phase == "mbop_phase11_post_task_eval":
            ev_data = _event_data(ev)
            lessons = ev_data.get("lessons", [])
            diag["mbop_lessons"] = [str(item)[:150] for item in lessons[:5]]
            diag["mbop_recommended_strategy"] = str(ev_data.get("failure_class", ""))[:100]
            break

    for ev in reversed(events):
        phase, _, _, _ = _event_fields(ev)
        if phase == "mbop_phase12_next_step":
            ev_data = _event_data(ev)
            suggestions = ev_data.get("suggestions", [])
            diag["mbop_next_step"] = [str(item)[:150] for item in suggestions[:3]]
            break

    return diag


def update_same_failure_tracking(run: Any, failure: str) -> int:
    """Update same-failure counters without changing runtime semantics."""
    if failure and failure == getattr(run, "last_repair_failure", ""):
        run.same_failure_count = int(getattr(run, "same_failure_count", 0) or 0) + 1
    else:
        run.same_failure_count = 0
    run.last_repair_failure = failure
    return int(run.same_failure_count or 0)


# --- repair_cycle extraction (#1371) -----------------------------------------
# NOTE: ``supervisor_models`` imports ``collect_repair_diagnostics`` and
# ``update_same_failure_tracking`` from this module, so we cannot import
# ``supervisor_models`` at module level here without creating a circular
# import.  The imports are deferred to function scope inside ``repair_cycle``.


def repair_cycle(
    supervisor: Any,
    run: SupervisorRun,
    config: RankSupervisorConfig,
    failure: str,
    cycle: int,
    *,
    preserve_validated_progress: bool = False,
    stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
) -> bool:
    """Run a single supervised repair cycle (#1371).

    This is a behavior-preserving extraction of
    ``SelfRepairSupervisor._repair_cycle``.  The ``supervisor`` argument
    receives the original ``self`` so all ``self.<attr>`` / ``self.<method>``
    references continue to resolve on the supervisor instance.
    """
    # Deferred imports to avoid circular import: supervisor_models imports
    # collect_repair_diagnostics/update_same_failure_tracking from this module.
    from igris.core.supervisor_models import (
        CommandResult,
        RETRYABLE_REPAIR_FAILURES,
        _command_detail,
        _failure_error_code,
    )
    from igris.core.supervisor_analysis import (
        _has_destructive_diff,
        _has_flask_test_client_in_diff,
        _has_invalid_fastapi_bootstrap_diff,
        _has_ui_surface_change,
        _is_product_only_ui_task_diff,
        _is_valid_missing_tests_repair_diff,
        _is_valid_ui_test_diff,
        _parse_pytest_collection_error,
    )

    title = f"{config.rank_id}: supervised repair for {failure}"
    body = f"Supervisor detected {failure} during run {run.run_id}."

    def _restore_or_preserve(detail: str, *, force_restore: bool = False) -> bool:
        if preserve_validated_progress and not force_restore:
            run.add(
                "repair_restore",
                "skipped",
                f"{detail} Progress preserved because stage orchestration validated earlier stages.",
                preserved_progress=True,
            )
            return True
        restore_result = supervisor.backend.restore_dangerous_diff()
        run.add("repair_restore", "success" if restore_result.success else "failure", detail or _command_detail(restore_result))
        return restore_result.success

    if config.allow_github_pr and not config.dry_run:
        if supervisor._repair_issue_already_created(run, failure):
            run.add(
                "repair_issue",
                "skipped",
                "Repair issue already exists for this run/failure",
                failure_class=failure,
            )
        else:
            issue = supervisor.backend.create_issue(title, body)
            run.add(
                "repair_issue",
                "success" if issue.success else "failure",
                _command_detail(issue),
                failure_class=failure,
            )
    else:
        run.add("repair_issue", "dry_run", title, failure_class=failure)
    helper_advice = supervisor._maybe_api_escalate(
        run,
        config,
        failure=failure,
        cycle=cycle,
        stage_statuses=stage_statuses,
    )
    high_risk_advice = False
    if helper_advice:
        risk = str(helper_advice.get("risk", "unknown")).lower()
        try:
            confidence = float(helper_advice.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        high_risk_advice = (
            risk in {"high", "critical"}
            or confidence < 0.5
            or bool(helper_advice.get("requires_human_or_codex_audit", False))
            or not bool(helper_advice.get("must_not_complete_product_manually", False))
        )
    _wrong_paths: List[str] = []
    _allowed: List[str] = []

    if failure == "reasoning_loop_blocked":
        repair_goal = supervisor._build_reasoning_loop_repair_prompt(
            stage_id=getattr(run, "stage_id", "unknown"),
            goal=config.goal,
            previous_reasoning_output="",
            repair_cycle=cycle,
        )
    elif failure == "semantic_incomplete":
        # The previous attempt produced a stub (# Placeholder, pass, hardcoded empty
        # values).  Repeat the original goal with explicit anti-stub guidance so the
        # next worker implements real logic rather than a skeleton.
        repair_goal = (
            f"{config.goal} "
            f"(previous attempt was rejected by the semantic acceptance gate: "
            f"the implementation contained stub patterns such as '# Placeholder' "
            f"comments, 'pass', or hardcoded dummy values. "
            f"Write a real implementation with actual logic — no placeholder comments, "
            f"no 'pass', no hardcoded empty strings. "
            f"Keep changes minimal, add tests, run pytest, do not push.)"
        )
    elif failure == "wrong_file_edit":
        for ev in reversed(getattr(run, "events", [])):
            ev_data = ev.data if hasattr(ev, "data") else (ev if isinstance(ev, dict) else {})
            if ev_data.get("files_modified"):
                _wrong_paths = list(ev_data["files_modified"])
                break
        if stage_statuses:
            for _st in stage_statuses.values():
                if _st.get("status") == "running":
                    _allowed = list(_st.get("allowed_file_families", []))
                    break
        repair_goal = supervisor._build_wrong_file_edit_repair_prompt(
            stage_id=getattr(run, "stage_id", "unknown"),
            goal=config.goal,
            wrong_paths=_wrong_paths,
            allowed_families=_allowed,
            repair_cycle=cycle,
        )
    else:
        repair_goal = (
            f"Fix IGRIS infrastructure failure '{failure}' observed during supervised "
            f"{config.rank_id}. Keep changes minimal, add tests, run pytest, do not push."
        )
    if helper_advice:
        repair_goal += (
            " API helper advice (advisory only, do not treat as authority): "
            f"diagnosis={helper_advice.get('diagnosis', '')}; "
            f"likely_gap={helper_advice.get('likely_supervisor_gap', '')}; "
            f"strategy={helper_advice.get('suggested_repair_strategy', '')}; "
            f"suggested_tests={helper_advice.get('suggested_tests', [])}."
        )
        if helper_advice.get("retry_focus"):
            repair_goal += f" retry_focus={helper_advice['retry_focus']}."
        if helper_advice.get("do_not_do"):
            repair_goal += f" do_not_do={helper_advice['do_not_do']}."
    if supervisor._goal_requires_ui_visibility(config.goal):
        if supervisor._goal_targets_rank_ui_card(config.goal):
            repair_goal += (
                " The UI mission must include the exact /api/rank/ui-card contract and "
                "minimal UI/dashboard visibility. Do not create placeholder routes or "
                "unrelated UI endpoint assertions in tests/test_rank_ui_card.py. "
                "Only assert the contract keys app, rank, status, and capability."
            )
        else:
            repair_goal += (
                " The mission requires minimal UI/dashboard visibility tied to the "
                "requested endpoint and matching tests. Keep edits mission-owned and "
                "avoid placeholder routes or unrelated assertions."
            )
    if failure == "missing_tests" and config.targeted_tests:
        repair_goal += (
            " Create or update the required targeted pytest file(s): "
            f"{' '.join(config.targeted_tests)}. Use FastAPI TestClient(create_app()). "
            "Assert only the mission-owned API endpoint from the goal and avoid "
            "unrelated endpoints such as /api/rank/status or /dashboard."
        )
    if failure == "pytest_failure":
        # --- Targeted collection-error diagnosis ---
        # Extract the latest full_pytest failure detail from run events so we can
        # build a precise repair goal instead of a generic "fix pytest" instruction.
        _pytest_output: str = ""
        for _ev in reversed(run.events):
            if getattr(_ev, "phase", "") == "full_pytest" and getattr(_ev, "status", "") == "failure":
                _pytest_output = getattr(_ev, "detail", "") or ""
                break
        if not _pytest_output:
            # Also check targeted_tests events as fallback
            for _ev in reversed(run.events):
                if getattr(_ev, "phase", "") == "targeted_tests" and getattr(_ev, "status", "") == "failure":
                    _pytest_output = getattr(_ev, "detail", "") or ""
                    break

        _collection_err = _parse_pytest_collection_error(_pytest_output) if _pytest_output else None

        if _collection_err:
            _err_type = _collection_err.get("error_type", "")
            if _err_type == "missing_symbol":
                _sym = _collection_err.get("missing_symbol", "")
                _mod = _collection_err.get("source_module", "")
                repair_goal = (
                    f"Fix pytest collection ImportError: the test suite tries to import "
                    f"'{_sym}' from '{_mod}' but that symbol does not exist there. "
                    f"Steps: (1) read the failing test file(s) to understand how '{_sym}' "
                    f"is used; (2) implement '{_sym}' in '{_mod}' (or the correct module) "
                    f"with the exact API the tests expect; (3) run pytest and confirm "
                    f"collection succeeds and all tests pass. "
                    f"Keep changes minimal — do not refactor unrelated code."
                )
            elif _err_type == "missing_module":
                _missing_mod = _collection_err.get("missing_module", "")
                repair_goal = (
                    f"Fix pytest collection ModuleNotFoundError: module '{_missing_mod}' "
                    f"is imported by the test suite but cannot be found. "
                    f"Steps: (1) check if '{_missing_mod}' is a project module that needs "
                    f"to be created or if it is a missing dependency; (2) if it is a "
                    f"project module, create it with the minimum API required by the tests; "
                    f"(3) if it is a third-party package, add it to requirements and "
                    f"install it; (4) run pytest and confirm collection succeeds. "
                    f"Keep changes minimal."
                )
            elif _err_type == "collection_error":
                _tf = _collection_err.get("failing_test_file", "")
                repair_goal = (
                    f"Fix pytest collection error{' in ' + _tf if _tf else ''}. "
                    f"The test collection phase failed (EEE / no tests ran). "
                    f"Steps: (1) run 'python -m pytest --collect-only' to reproduce the "
                    f"exact error; (2) read the failing test file{'  ' + _tf if _tf else ''} "
                    f"and the module(s) it imports; (3) fix the root cause (missing class, "
                    f"wrong import path, syntax error, etc.); (4) run pytest and confirm "
                    f"all tests are collected and pass. Keep changes minimal."
                )

        # Always append the FastAPI test-client reminder
        repair_goal += (
            " CRITICAL — this is a FastAPI application. Any test file MUST use "
            "'from fastapi.testclient import TestClient' and instantiate the client as "
            "'client = TestClient(create_app())'. Do NOT use the Flask-style "
            "'app.test_client()' — FastAPI app objects have no test_client() method and "
            "its use causes AttributeError at pytest collection time (EEE errors). "
            "If existing test files contain 'test_client(' they must be rewritten to "
            "use 'TestClient(create_app())' from fastapi.testclient. "
            "Verify that target API endpoints exist in igris/web/server.py before writing "
            "tests for them; if they are missing, add the endpoint implementation first."
        )
    # Track same-failure count: increment when the same failure class recurs.
    update_same_failure_tracking(run, failure)

    # Issue #715 — adaptive retry ladder: when the same failure recurs, emit a
    # strategy_switch event so that the reasoning worker can use a different approach.
    if run.same_failure_count >= 1:
        run.add(
            "adaptive_retry",
            "strategy_switch",
            f"Same failure '{failure}' recurred {run.same_failure_count + 1} time(s); "
            "switching to focused single-file task type for this repair cycle.",
            attempt=cycle,
            task_type="single_file_single_test",
            same_failure_count=run.same_failure_count,
        )

    # Execution budget guard — checked before spending reasoning resources.
    budget_failure = supervisor._check_execution_budget(run)
    if budget_failure:
        run.add(
            "execution_budget",
            "exceeded",
            f"Execution budget exceeded (IGRIS_MAX_COST_PER_RUN); aborting repair.",
            failure_class=budget_failure,
            execution_budget_used_usd=run.execution_budget_used_usd,
            max_cost_per_run=supervisor._get_max_cost_per_run(),
        )
        run.failure_class = budget_failure
        run.status = "failed"
        return False

    repair_context = supervisor._rank_initial_context(config, run=run)
    repair_context.update({
        "repair_cycle": cycle,
        "failure_class": failure,
        "supervised_repair": True,
        "repair_goal": repair_goal,
        "api_helper_advice": helper_advice or {},
        "api_helper_advisory_only": True,
    })

    # --- #1103 — MBOP post-run feedback for repair cycles ---
    # Inject diagnostics from the CURRENT run's prior attempts so the
    # repair reasoning knows exactly why the previous attempt failed
    # and which acceptance criteria are still missing.
    repair_context.update(
        supervisor._collect_repair_diagnostics(run, failure, cycle)
    )
    if failure == "wrong_file_edit" and _wrong_paths:
        repair_context["constraint_wrong_file_history"] = {
            "previous_wrong_paths": _wrong_paths,
            "allowed_families": _allowed,
            "instruction": (
                "You MUST only modify files in allowed_families. "
                "Any edit outside this list will be reverted and counted as a failure."
            ),
        }

    # Determine execution strategy when helper has provided an execution plan.
    has_execution_plan = bool(helper_advice and str(helper_advice.get("execution_plan", "")).strip())
    strategy, strategy_profile = supervisor._strategy_for_repair(run, has_execution_plan)
    if strategy and helper_advice is not None:
        run.strategy_used = strategy
        # Inject structured plan fields so the reasoning worker can use them.
        repair_context.update({
            "execution_plan": helper_advice.get("execution_plan", ""),
            "file_targets": helper_advice.get("file_targets", []),
            "operations": helper_advice.get("operations", []),
            "acceptance_matrix": helper_advice.get("acceptance_matrix", []),
            "required_tests": helper_advice.get("required_tests", []),
            "do_not_do": helper_advice.get("do_not_do", []),
            "retry_focus": helper_advice.get("retry_focus", ""),
            "helper_advice_strategy": strategy,
            "helper_advice_only": True,
        })

    # Escalate to cloud-first execution for repeated semantic failures or
    # when the local model is unavailable (would otherwise silently degrade
    # to deterministic fallback producing empty/stub output).
    repair_task_type = "code_reasoning"
    repair_profile: Optional[str] = None
    if failure in {"semantic_incomplete", "stub_detected", "reasoning_loop_blocked"}:
        repair_task_type = "semantic_repair"
    elif failure in {"missing_tests", "pytest_failure"} and cycle > 1:
        repair_task_type = "code_generation"
    elif failure == "max_steps":
        # Reasoning hit the step ceiling without making progress — the cheap model
        # couldn't complete the task. Escalate to strong_execution (gpt-4o) so the
        # repair attempt uses a more capable model rather than repeating the same failure.
        repair_profile = "strong_execution"
    # Issue #715 — adaptive retry ladder: same failure recurring → switch to a
    # focused single-file strategy so the model works on one file at a time.
    if run.same_failure_count >= 1 and repair_task_type == "code_reasoning":
        repair_task_type = "single_file_single_test"
    # Strategy profile takes precedence, then env override, then task default.
    if strategy_profile:
        repair_profile = strategy_profile
    env_profile = os.environ.get("IGRIS_EXECUTION_PREFERRED_PROFILE", "")
    if env_profile and not strategy_profile:
        repair_profile = env_profile
    # Epic #1074 — Wire decide_repair_strategy() for explicit, auditable strategy.
    # The strategy module makes the same decision as the inline logic above but
    # in a pure, testable function. We use it here to:
    #   (a) emit a structured 'repair_strategy_decision' event for audit
    #   (b) early-exit with skip_repair=True when the strategy says so
    #   (c) prepend strategy.goal_prefix to the repair_goal for context
    try:
        from igris.core.repair_strategy import RepairContext, decide_repair_strategy
        _rs_ctx = RepairContext(
            failure_class=failure,
            cycle=cycle,
            same_failure_count=int(run.same_failure_count or 0),
            max_repair_cycles=int(config.max_repair_cycles or 3),
            base_timeout_seconds=int(config.reasoning_timeout_seconds or 900),
            has_high_risk_advice=high_risk_advice,
            has_execution_plan=has_execution_plan,
            capability_signals=dict(run.capability_signals or {}),
        )
        _rs = decide_repair_strategy(_rs_ctx)
        run.add(
            "repair_strategy_decision",
            "skip" if _rs.skip_repair else "proceed",
            (
                f"strategy: task_type={_rs.task_type} profile={_rs.profile!r} "
                f"timeout={_rs.timeout_seconds}s skip={_rs.skip_repair}"
                + (f" reason={_rs.skip_reason}" if _rs.skip_repair else "")
                + (f" escalate_decompose={_rs.escalate_to_decomposition}" if _rs.escalate_to_decomposition else "")
            ),
            task_type=_rs.task_type,
            profile=_rs.profile,
            timeout_seconds=_rs.timeout_seconds,
            skip_repair=_rs.skip_repair,
            skip_reason=_rs.skip_reason,
            escalate_to_decomposition=_rs.escalate_to_decomposition,
            same_failure_count=int(run.same_failure_count or 0),
            notes=_rs.notes,
        )
        if _rs.skip_repair:
            return False
        # Prepend goal_prefix for additional context (does not override full goal logic above)
        if _rs.goal_prefix and not repair_goal.startswith(_rs.goal_prefix):
            repair_goal = f"{_rs.goal_prefix} {repair_goal}"
    except Exception as _rs_exc:
        run.add(
            "repair_strategy_decision",
            "skipped",
            f"decide_repair_strategy unavailable: {_rs_exc}",
        )

    run.add(
        "repair_reasoning",
        "running",
        f"Starting repair reasoning cycle {cycle}",
        task_type=repair_task_type,
        preferred_profile=repair_profile,
        failure_class=failure,
        error_code=_failure_error_code(failure),
        strategy_used=strategy or "",
        helper_model=config.api_helper_model if helper_advice else "",
        has_execution_plan=has_execution_plan,
        same_failure_count=run.same_failure_count,
    )
    # Fast provider health-check before burning repair budget (#1059).
    # If all LLM providers are unavailable (silent timeouts), skip the repair
    # cycle immediately rather than blocking for up to 900 s.
    _provider_ok = supervisor._quick_provider_check()
    if not _provider_ok:
        run.add(
            "repair_reasoning",
            "skipped",
            "All LLM providers unavailable — skipping repair cycle to preserve budget",
            failure_class=failure,
            provider_check="failed",
        )
        return False

    # Strong models need extended repair timeout (same logic as main reasoning).
    _repair_timeout = config.reasoning_timeout_seconds
    _STRONG_PROFILES = {"strong_execution", "strong_cloud_reasoning", "gpu_reasoning"}
    if (repair_profile or "") in _STRONG_PROFILES or repair_task_type in ("semantic_repair", "endpoint_implementation"):
        _repair_timeout = int(os.getenv(
            "IGRIS_STRONG_REASONING_TIMEOUT_SECONDS",
            str(max(_repair_timeout * 3, 2400)),
        ))
    result = supervisor.backend.run_reasoning(
        repair_goal,
        max_steps=160,
        initial_context=repair_context,
        timeout=_repair_timeout,
        task_type=repair_task_type,
        preferred_profile=repair_profile,
    )
    # Accumulate execution cost for budget tracking.
    try:
        step_cost = float(result.get("estimated_cost", 0) or 0)
    except (TypeError, ValueError):
        step_cost = 0.0
    run.execution_budget_used_usd += step_cost
    run.add(
        "repair_reasoning",
        str(result.get("status", "")),
        result.get("final_summary", ""),
        orchestrator_used=result.get("orchestrator_used", False),
        reasoning_execution_provider=result.get("reasoning_execution_provider", ""),
        reasoning_execution_model=result.get("reasoning_execution_model", ""),
        reasoning_execution_profile=result.get("reasoning_execution_profile", ""),
        local_model_available=result.get("local_model_available", False),
        strategy_used=strategy or "",
        execution_model=result.get("reasoning_execution_model", ""),
        task_type=repair_task_type,
        prompt_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
        estimated_cost=step_cost,
        same_failure_count=run.same_failure_count,
    )
    # Record a reasoning_timeout signal when repair reasoning times out, hits
    # budget, or explicitly refuses — all indicate the model cannot make progress.
    if str(result.get("stop_reason", "")) in {"reasoning_timeout", "budget_exceeded", "blocked"}:
        supervisor._record_capability_signal(run, "reasoning_timeout")
    # Record a capability signal when repair also hits max_steps — the escalated
    # model (strong_execution) exhausted its step budget too, confirming a
    # capability ceiling rather than a transient model availability issue.
    if str(result.get("stop_reason", "")) == "max_steps" and repair_profile == "strong_execution":
        supervisor._record_capability_signal(run, "max_steps_ceiling")
    # Restore working tree when reasoning timed out. Partial changes from an
    # interrupted worker are unreliable (e.g. broken imports in test files) and
    # must never reach repair_tests. For pytest_failure, try to re-scaffold the
    # targeted test to preserve mission progress. For all other failures, return
    # False so the outer loop can detect capability limits and trigger decomposition.
    if str(result.get("stop_reason", "")) == "reasoning_timeout":
        _restore_or_preserve(
            "Repair reasoning timed out; restoring working tree to prevent broken "
            "partial changes from reaching repair_tests.",
            force_restore=True,
        )
        if failure == "pytest_failure" and supervisor._re_scaffold_targeted_test_if_missing(run, config):
            run.add(
                "repair_completion",
                "degraded",
                "Restored failed pytest repair and re-scaffolded targeted tests to preserve mission progress.",
            )
            return True
        return False
    diff_stat = supervisor.backend.git_diff_stat()
    diff = supervisor.backend.git_diff()
    run.add("repair_diff_stat", "success" if diff_stat.success else "failure", _command_detail(diff_stat))
    if not diff_stat.success:
        return _restore_or_preserve(_command_detail(diff_stat), force_restore=True) and False
    if _has_destructive_diff(diff.output):
        if not _restore_or_preserve("Destructive repair diff rejected; restoring.", force_restore=True):
            return False
        if failure in RETRYABLE_REPAIR_FAILURES:
            supervisor._preserve_targeted_tests_after_restore_retry(run, config, failure)
            run.add(
                "repair_retry",
                "running",
                "Destructive repair diff was rejected; retrying with remaining budget.",
                failure_class="destructive_diff",
            )
            return True
        return False
    if _has_invalid_fastapi_bootstrap_diff(diff.output):
        if not _restore_or_preserve(
            "Invalid FastAPI bootstrap diff rejected before repair validation",
            force_restore=True,
        ):
            return False
        run.add(
            "repair_retry",
            "running",
            "Invalid FastAPI bootstrap diff was rejected; retrying with remaining budget.",
            failure_class="invalid_bootstrap",
        )
        supervisor._preserve_targeted_tests_after_restore_retry(run, config, failure)
        return True
    if failure == "missing_tests" and not _is_valid_missing_tests_repair_diff(diff.output, config.goal):
        if not _restore_or_preserve(
            "Missing-tests repair diff rejected before validation",
            force_restore=True,
        ):
            return False
        scaffold = supervisor._scaffold_missing_tests_target(config)
        run.add("repair_scaffold", "success" if scaffold.success else "failure", _command_detail(scaffold))
        if scaffold.success:
            diff_stat = supervisor.backend.git_diff_stat()
            diff = supervisor.backend.git_diff()
            run.add("repair_scaffold_diff", "success" if diff_stat.success else "failure", _command_detail(diff_stat))
            if not diff.output.strip():
                synthetic_diff = supervisor._synthetic_missing_tests_diff(config)
                if synthetic_diff:
                    diff = CommandResult(True, synthetic_diff, "", 0)
                    run.add(
                        "repair_scaffold_diff",
                        "success",
                        "Synthesized missing-tests diff from untracked scaffold file.",
                        synthesized_untracked=True,
                    )
        if (
            not scaffold.success
            or not _is_valid_missing_tests_repair_diff(diff.output, config.goal)
        ):
            if scaffold.success:
                _restore_or_preserve(
                    "Scaffolded missing-tests diff was invalid; restored.",
                    force_restore=True,
                )
            run.add(
                "repair_retry",
                "running",
                "Missing-tests repair diff was rejected; retrying with remaining budget.",
                failure_class="wrong_file_edit",
            )
            return True
    ui_visibility_goal = supervisor._goal_requires_ui_visibility(config.goal)
    ui_card_goal = supervisor._goal_targets_rank_ui_card(config.goal)
    if ui_visibility_goal and ui_card_goal and _is_product_only_ui_task_diff(diff.output):
        allow_safe_ui_repair = (
            _has_ui_surface_change(diff.output)
            and failure in {"missing_ui_visibility", "reasoning_loop_blocked"}
        )
        if failure == "pytest_failure":
            allow_safe_ui_repair = True
        if not allow_safe_ui_repair:
            if not _restore_or_preserve(
                "Product-only UI task diff rejected before repair validation",
                force_restore=True,
            ):
                return False
            run.add(
                "repair_retry",
                "running",
                "Product-only UI task diff was rejected; retrying with remaining budget.",
                failure_class="wrong_file_edit",
            )
            supervisor._preserve_targeted_tests_after_restore_retry(run, config, failure)
            return True
    if ui_visibility_goal and ui_card_goal and not _is_valid_ui_test_diff(diff.output):
        if not _restore_or_preserve(
            "Invalid UI test diff rejected before repair validation",
            force_restore=True,
        ):
            return False
        run.add(
            "repair_retry",
            "running",
            "Invalid UI test diff was rejected; retrying with remaining budget.",
            failure_class="wrong_file_edit",
        )
        supervisor._preserve_targeted_tests_after_restore_retry(run, config, failure)
        return True
    # For pytest_failure repairs: reject diffs that introduce Flask-style test_client()
    # calls.  FastAPI apps have no test_client() method; using it causes AttributeError
    # at collection time (EEE errors).  Detecting and rejecting this pattern early avoids
    # repeated repair cycles that add the wrong client without making progress.
    if failure == "pytest_failure" and _has_flask_test_client_in_diff(diff.output):
        if not _restore_or_preserve(
            "Repair diff uses Flask-style test_client() which is incompatible with "
            "this FastAPI application; restoring and retrying with FastAPI TestClient "
            "guidance.",
            force_restore=True,
        ):
            return False
        run.add(
            "repair_retry",
            "running",
            "Flask test_client() detected in repair diff for FastAPI app; "
            "diff rejected. Retrying with explicit FastAPI TestClient(create_app()) guidance.",
            failure_class="wrong_file_edit",
        )
        supervisor._preserve_targeted_tests_after_restore_retry(run, config, failure)
        return True
    if not diff.output.strip():
        # Count repairs that produce no diff — a model that cannot propose any
        # change after multiple cycles has hit a capability wall.
        supervisor._record_capability_signal(run, "no_diff_repair")
        _restore_or_preserve("Repair produced no validated diff; restoring working tree state.")
        if failure == "pytest_failure" and supervisor._re_scaffold_targeted_test_if_missing(run, config):
            run.add(
                "repair_completion",
                "degraded",
                "No-diff pytest repair restored and re-scaffolded targeted tests; continuing rank attempts.",
            )
            return True
        if failure in RETRYABLE_REPAIR_FAILURES:
            supervisor._preserve_targeted_tests_after_restore_retry(run, config, failure)
            run.add(
                "repair_retry",
                "running",
                "Repair reasoning produced no validated diff; retrying with remaining budget.",
                failure_class=failure,
            )
            return True
        return False
    run.add(
        "repair_tests",
        "running",
        "Running repair validation pytest (-m 'not slow')",
        timeout_seconds=config.test_timeout_seconds,
        exclude_slow=True,
    )
    tests = supervisor.backend.run_tests(timeout=config.test_timeout_seconds, hard_cap=config.test_hard_cap_seconds, exclude_slow=True)
    run.add("repair_tests", "success" if tests.success else "failure", _command_detail(tests))
    if not tests.success and "Command killed:" in (tests.error or ""):
        # Repair validation also hung — counts against the same capability-limit budget.
        supervisor._record_capability_signal(run, "pytest_hang")
    if not tests.success:
        if failure == "missing_tests" and _is_valid_missing_tests_repair_diff(diff.output, config.goal):
            run.add(
                "repair_completion",
                "degraded",
                "Preserved valid missing-tests scaffold despite failing full pytest; continuing rank attempts.",
            )
            return True
        _restore_or_preserve("Repair validation failed; restoring unless preserving validated stage progress.")
        if failure == "pytest_failure" and supervisor._re_scaffold_targeted_test_if_missing(run, config):
            run.add(
                "repair_completion",
                "degraded",
                "Restored failed pytest repair and re-scaffolded targeted tests to preserve mission progress.",
            )
            return True
        if failure in RETRYABLE_REPAIR_FAILURES:
            supervisor._preserve_targeted_tests_after_restore_retry(run, config, failure)
            run.add(
                "repair_retry",
                "running",
                "Repair validation failed; retrying with remaining budget.",
                failure_class=failure,
            )
            return True
        return False
    if str(result.get("status", "")) != "finished":
        run.add(
            "repair_completion",
            "degraded",
            "Repair reasoning did not finish cleanly but the validated diff was accepted.",
            stop_reason=result.get("stop_reason", ""),
            files_modified=result.get("files_modified", []),
        )
    if high_risk_advice:
        run.add(
            "repair_high_risk_validation",
            "running",
            "High-risk helper advice detected; running stronger validation smoke.",
        )
        strong_smoke = supervisor.backend.smoke(config.required_smoke_endpoints, "")
        run.add(
            "repair_high_risk_validation",
            "success" if strong_smoke.success else "failure",
            _command_detail(strong_smoke),
        )
        if not strong_smoke.success:
            _restore_or_preserve("High-risk advisory validation smoke failed; restoring.", force_restore=True)
            if failure in RETRYABLE_REPAIR_FAILURES:
                run.add(
                    "repair_retry",
                    "running",
                    "High-risk advisory smoke failed; retrying with remaining budget.",
                    failure_class="infrastructure_bug",
                )
                return True
            return False
    return True
