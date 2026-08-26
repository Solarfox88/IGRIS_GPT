"""Supervisor autorun and API-escalation helpers.

Standalone functions extracted from self_repair_supervisor.py for modularity
(Issue #1371). These cover:

- maybe_api_escalate: advisory API helper escalation path used during repair
  cycles when the supervisor cannot resolve a failure internally.
- autorun_guards: guard checks performed before auto-queuing a child run for
  the first sub-issue of a decomposition.
- autorun_first_subissue: fetch the first sub-issue from GitHub and queue a
  child supervised run, inheriting parent config with incremented autochain
  depth.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from igris.core.supervisor_models import _command_detail, _safe_redact

if TYPE_CHECKING:
    from igris.core.supervisor_models import RankSupervisorConfig, SupervisorRun


def maybe_api_escalate(
    supervisor,
    run: "SupervisorRun",
    config: "RankSupervisorConfig",
    *,
    failure: str,
    cycle: int,
    stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Attempt an advisory API helper escalation for the current failure.

    Returns the validated advice dict on success, or None when skipped or the
    helper call fails. Consumes call/USD budgets only when the helper is
    actually invoked.
    """
    if not config.allow_api_escalation:
        run.add("api_escalation", "skipped", "API escalation disabled by config.")
        return None
    if run.api_escalations_used >= config.max_api_escalations_per_run:
        run.add("api_escalation", "skipped", "API escalation call budget exhausted.", budget_type="calls")
        return None
    if run.api_budget_used_usd >= config.max_api_budget_usd:
        run.add("api_escalation", "skipped", "API escalation USD budget exhausted.", budget_type="usd")
        return None

    # Pre-flight: if the helper is not configured, skip without consuming
    # call budget.  The operator may have set allow_api_escalation=True but
    # not yet provided IGRIS_API_HELPER_COMMAND; burning budget here is
    # unhelpful and misleads the UI into showing api=N/api=N as exhausted.
    if not supervisor.backend.api_helper_is_configured():
        run.api_escalations_failed_unconfigured += 1
        run.add(
            "api_escalation",
            "not_configured",
            "API helper command is not configured (IGRIS_API_HELPER_COMMAND unset); "
            "escalation skipped without consuming call budget.",
            budget_type="unconfigured",
        )
        return None
    # Resolve effective mode: config field takes precedence over env var so
    # that per-run config can override the operator .env setting.
    effective_mode = config.api_helper_mode.strip() or os.getenv("IGRIS_API_HELPER_MODE", "").strip() or "auto"
    is_codex_only = effective_mode == "codex_only"

    packet = supervisor._build_api_escalation_packet(run, config, failure=failure, cycle=cycle, stage_statuses=stage_statuses)
    run.add(
        "api_escalation_request",
        "running",
        "Calling API helper for advisory diagnosis and recovery plan.",
        model=config.api_helper_model,
        max_tokens=config.max_tokens_per_escalation,
        api_helper_mode=effective_mode,
        api_helper_model_requested=config.api_helper_model,
        codex_only=is_codex_only,
        packet=packet,
    )
    result = supervisor.backend.call_api_helper(
        packet,
        model=config.api_helper_model,
        max_tokens=config.max_tokens_per_escalation,
        timeout=min(60, config.reasoning_timeout_seconds),
        mode=effective_mode,
    )
    # Only count as a used escalation when the helper was actually called
    # (configured, regardless of whether it succeeded).
    run.api_escalations_used += 1
    if not result.success:
        run.add("api_escalation_response", "failure", _command_detail(result),
                api_helper_mode=effective_mode, codex_only=is_codex_only)
        return None
    try:
        raw_payload = json.loads(result.output or "{}")
    except json.JSONDecodeError:
        run.add("api_escalation_response", "failure", "API helper returned invalid JSON.",
                api_helper_mode=effective_mode, codex_only=is_codex_only)
        return None
    valid, advice, error = supervisor._validate_helper_response(raw_payload)
    if not valid:
        run.add("api_escalation_response", "failure", error,
                api_helper_mode=effective_mode, codex_only=is_codex_only,
                payload=supervisor._sanitize_escalation_value(raw_payload))
        return None
    try:
        estimated_cost_usd = max(0.0, float(raw_payload.get("estimated_cost_usd", 0.0)))
    except (TypeError, ValueError):
        estimated_cost_usd = 0.0
    run.api_budget_used_usd += estimated_cost_usd
    # Extract observability fields from helper response
    model_resolved = str(raw_payload.get("api_helper_model_resolved", raw_payload.get("model", "")))
    helper_provider = str(raw_payload.get("api_helper_provider", ""))
    run.add(
        "api_escalation_response",
        "success",
        "API helper advice received and recorded.",
        advice=supervisor._sanitize_escalation_value(advice),
        estimated_cost_usd=estimated_cost_usd,
        helper_is_authority=False,
        api_helper_mode=effective_mode,
        api_helper_provider=helper_provider,
        api_helper_model_requested=config.api_helper_model,
        api_helper_model_resolved=model_resolved,
        helper_model=result.helper_model or config.api_helper_model,
        helper_alt_model=result.helper_ab_alt_model,
        helper_ab_active=result.helper_ab_active,
        helper_ab_shadow_mode=result.helper_ab_shadow_mode,
        helper_primary_score=result.helper_primary_score,
        helper_alt_score=result.helper_alt_score,
        helper_alt_used_for_decision=False,
        helper_switch_recommendation=result.helper_switch_recommendation,
        codex_only=is_codex_only,
    )
    if getattr(run, "behavior_tracker", None) is not None:
        try:
            tracker = run.behavior_tracker
            tracker.record_external_intervention(
                actor=str(helper_provider or model_resolved or "external_api_helper"),
                source="api_escalation",
                detail=f"External escalation used for failure={failure} cycle={cycle}.",
                severity="medium",
                escalated=True,
                stage_id="api_escalation",
                evidence=json.dumps(supervisor._sanitize_escalation_value(advice), sort_keys=True),
            )
        except (KeyError, TypeError, ValueError, AttributeError, RuntimeError):  # noqa: BLE001
            pass
    return advice


def autorun_guards(
    supervisor,
    run: "SupervisorRun",
    config: "RankSupervisorConfig",
    decomposition: Dict[str, Any],
    created_urls: List[str],
) -> Tuple[bool, str]:
    """Check all guards before auto-queuing a child run.

    Returns (ok, reason) — if ok is False, reason explains why autorun is skipped.
    """
    if not config.allow_auto_subissues:
        return False, "allow_auto_subissues=False"
    if config.dry_run:
        return False, "dry_run=True"
    # Cascade depth guard: stop auto-chaining after _MAX_AUTOCHAIN_DEPTH levels
    max_autochain_depth = type(supervisor)._MAX_AUTOCHAIN_DEPTH
    if config.autochain_depth >= max_autochain_depth:
        return False, f"max_autochain_depth: depth={config.autochain_depth}>={max_autochain_depth}"
    if not created_urls:
        return False, "no_sub_issue_urls"
    approval = decomposition.get("approval_status", "")
    if approval != "auto_approved_by_policy":
        return False, f"approval_status={approval!r} (not auto_approved)"
    if decomposition.get("decomposition_cycle_detected"):
        return False, "decomposition_cycle_detected"

    # Anti-loop: first sub-issue must not be the same as any URL referenced in parent goal
    first_url = created_urls[0]
    parent_goal_lower = config.goal.lower()
    # Extract issue numbers from first_url and goal
    import re as _re
    first_num_m = _re.search(r"/issues/(\d+)", first_url)
    if first_num_m:
        first_num = first_num_m.group(1)
        if f"/issues/{first_num}" in parent_goal_lower or f"#{first_num}" in parent_goal_lower:
            return False, f"anti_loop: sub-issue #{first_num} matches parent goal"

    # Check if a run for this sub-issue URL is already active
    import igris.core.self_repair_supervisor as _self_mod
    RUN_LOCK = _self_mod.RUN_LOCK
    RUN_STORE = _self_mod.RUN_STORE
    with RUN_LOCK:
        active_runs = list(RUN_STORE.values())
    for r in active_runs:
        if r.run_id == run.run_id:
            continue
        if r.status in ("running", "cancelling"):
            if first_url in r.goal or first_url in str(r.report):
                return False, f"sub_issue_already_running: run_id={r.run_id}"

    # Budget check (0 means unlimited)
    max_cost_per_run = supervisor._get_max_cost_per_run()
    if max_cost_per_run > 0 and run.execution_budget_used_usd >= max_cost_per_run:
        return False, f"budget_exceeded: {run.execution_budget_used_usd:.4f}>={max_cost_per_run:.4f}"

    return True, ""


def autorun_first_subissue(
    supervisor,
    run: "SupervisorRun",
    config: "RankSupervisorConfig",
    decomposition: Dict[str, Any],
    created_urls: List[str],
    triggering_signal: str,
) -> Optional[str]:
    """Fetch the first sub-issue from GitHub and queue a child supervised run.

    Returns the child run_id on success, None if skipped or failed.
    """
    import igris.core.self_repair_supervisor as _self_mod

    ok, skip_reason = autorun_guards(supervisor, run, config, decomposition, created_urls)
    if not ok:
        run.add(
            "submission_autorun_skipped",
            "skipped",
            f"Auto-run skipped: {skip_reason}",
            reason=skip_reason,
        )
        run.autorun_skipped_reason = skip_reason
        run.report.update({
            "autorun_policy": "skipped",
            "autorun_skipped_reason": skip_reason,
        })
        return None

    first_url = created_urls[0]
    run.add(
        "submission_autorun_queued",
        "running",
        f"Fetching sub-issue to prepare child run: {_safe_redact(first_url)}",
        sub_issue_url=_safe_redact(first_url),
    )

    # Fetch sub-issue data from GitHub
    fetch_result = supervisor.backend.fetch_issue(first_url)
    if not fetch_result.success:
        reason = f"fetch_issue_failed: {_safe_redact(fetch_result.error)[:120]}"
        run.add("submission_autorun_skipped", "failure", reason, sub_issue_url=_safe_redact(first_url))
        run.autorun_skipped_reason = reason
        run.report.update({"autorun_policy": "skipped", "autorun_skipped_reason": reason})
        return None

    try:
        issue_data = json.loads(fetch_result.output or "{}")
    except json.JSONDecodeError:
        issue_data = {}

    issue_title = _safe_redact(str(issue_data.get("title", "") or ""))
    issue_body = _safe_redact(str(issue_data.get("body", "") or ""))
    issue_number = issue_data.get("number", "")

    # Build goal from sub-issue title + body (first 2000 chars of body)
    body_excerpt = issue_body[:2000].strip()
    child_goal = f"{issue_title}\n\n{body_excerpt}" if body_excerpt else issue_title
    if not child_goal.strip():
        child_goal = decomposition.get("first_sub_mission", first_url)

    # Derive child rank_id from parent + issue number
    child_rank_id = f"{run.rank_id}-sub{issue_number}" if issue_number else f"{run.rank_id}-sub1"

    # Inherit parent config but override goal and rank_id
    child_data: Dict[str, Any] = {
        "goal": child_goal,
        "rank_id": child_rank_id,
        "dry_run": False,
        "max_rank_attempts": config.max_rank_attempts,
        "max_repair_cycles": config.max_repair_cycles,
        "allow_github_pr": config.allow_github_pr,
        "allow_merge_if_green": config.allow_merge_if_green,
        "service_restart_command": config.service_restart_command,
        "required_smoke_endpoints": list(config.required_smoke_endpoints),
        "test_timeout_seconds": config.test_timeout_seconds,
        "test_hard_cap_seconds": config.test_hard_cap_seconds,
        "reasoning_timeout_seconds": config.reasoning_timeout_seconds,
        "allow_api_escalation": config.allow_api_escalation,
        "max_api_escalations_per_run": config.max_api_escalations_per_run,
        "max_api_budget_usd": config.max_api_budget_usd,
        "max_tokens_per_escalation": config.max_tokens_per_escalation,
        "api_helper_model": config.api_helper_model,
        "enable_mission_planning": config.enable_mission_planning,
        "allow_auto_subissues": config.allow_auto_subissues,
        "enable_semantic_gate": config.enable_semantic_gate,
        "api_helper_mode": config.api_helper_mode,
        # Increment depth so grandchild hits max_autochain_depth guard
        "autochain_depth": config.autochain_depth + 1,
        # Mark so child knows its parent
        "_parent_run_id": run.run_id,
        "_parent_sub_issue_url": first_url,
        "_parent_triggering_signal": triggering_signal,
    }

    try:
        child_run = _self_mod.start_supervised_rank_async(child_data, project_root=str(supervisor.project_root))
        child_run_id = child_run.run_id
    except Exception as exc:  # noqa: BLE001
        reason = f"child_run_start_failed: {_safe_redact(str(exc))[:120]}"
        run.add("submission_autorun_skipped", "failure", reason, sub_issue_url=_safe_redact(first_url))
        run.autorun_skipped_reason = reason
        run.report.update({"autorun_policy": "skipped", "autorun_skipped_reason": reason})
        return None

    run.autorun_child_run_id = child_run_id
    run.autorun_policy = "auto_create_subissues"
    run.add(
        "submission_autorun_run_id",
        "success",
        f"Child run {child_run_id} queued for sub-issue {_safe_redact(first_url)}",
        child_run_id=child_run_id,
        sub_issue_url=_safe_redact(first_url),
        sub_issue_title=issue_title,
        child_rank_id=child_rank_id,
    )
    run.report.update({
        "next_subissue_url": _safe_redact(first_url),
        "next_subissue_number": str(issue_number),
        "autorun_child_run_id": child_run_id,
        "autorun_policy": "auto_create_subissues",
        "autorun_skipped_reason": "",
    })
    return child_run_id
