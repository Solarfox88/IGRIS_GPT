"""Autonomous self-repair supervisor for controlled rank missions.

The supervisor coordinates an IGRIS rank attempt and bounded infrastructure
repair cycles. It does not expose free-form shell execution: the default
backend runs fixed argv commands only, and tests can inject a fake backend.

This module serves as the public facade — all symbols are re-exported from
the sub-modules for backward compatibility. Internal organization:
  - supervisor_models.py:   dataclasses, constants, helpers
  - supervisor_backend.py:  SupervisorBackend Protocol, LocalSupervisorBackend
  - supervisor_analysis.py: failure classification, diff analysis, baseline cache
  - supervisor_api.py:      run management API (start, cancel, list, summarize)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

from igris.core.safety import redact_secrets
from igris.core.failure_memory import FailureMemory, FailureRisk
from igris.core.acceptance_gate import check_acceptance_evidence
from igris.core.supervisor_run_store import SupervisorRunStore
from igris.core.supervisor_lifecycle import (
    is_terminal_status as _lifecycle_is_terminal_status,
    configure_run_tracking as _lifecycle_configure_run_tracking,
    transition_run_status as _lifecycle_transition_run_status,
)
from igris.core.supervisor_repair_cycle import (
    collect_repair_diagnostics as _collect_repair_diagnostics_helper,
    update_same_failure_tracking as _update_same_failure_tracking_helper,
)
from igris.core.supervisor_repair_cycle import repair_cycle as _repair_cycle_fn

from igris.core.supervisor_rank_loop import run_rank_loop as _run_rank_loop_fn

from igris.core.supervisor_preflight import run_preflight_phase as _run_preflight_phase_fn

# Re-export everything from sub-modules for backward compatibility.
from igris.core.supervisor_models import (  # noqa: F401
    AUDIT_STATUSES,
    CAPABILITY_LIMIT_SIGNALS,
    CAPABILITY_LIMIT_THRESHOLD,
    DECOMPOSITION_REQUIRED_FIELDS,
    DEFAULT_BASELINE_TIMEOUT_SECONDS,
    DEFAULT_MAX_REPAIR_CYCLES,
    DEFAULT_PREFLIGHT_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_PING_TIMEOUT_SECONDS,
    DEFAULT_REPAIR_TIMEOUT_SECONDS,
    DEFAULT_SMOKE_TIMEOUT_SECONDS,
    FAILURE_ERROR_CODES,
    NO_DIFF_SIGNAL_THRESHOLD,
    PLANNING_MAX_STEPS,
    PLANNING_TIMEOUT_SECONDS,
    REPAIRABLE_FAILURES,
    RETRYABLE_REPAIR_FAILURES,
    SUPERVISOR_BRANCH_PREFIX,
    UNSAFE_STATUS_PREFIXES,
    WRITE_ACTION_TYPES,
    CommandResult,
    MissionPlan,
    MissionStage,
    RankSupervisorConfig,
    RunPhase,
    SupervisorEvent,
    SupervisorRun,
    _as_bool,
    _command_detail,
    _failure_error_code,
    _infer_dry_run,
    _infer_targeted_tests,
    _parse_issue_number,
    _safe_redact,
    _safe_text,
    classify_failure_from_output,
    classify_failure_severity,
)

from igris.core.supervisor_backend import (  # noqa: F401
    LocalSupervisorBackend,
    SupervisorBackend,
)

from igris.core.supervisor_analysis import (  # noqa: F401
    CORE_FILE_PATTERNS,
    _allow_unrelated_vastai_baseline_failures,
    _baseline_cache_path,
    _baseline_failure_is_transient,
    _baseline_sanity_targets,
    _changed_paths_between_diffs,
    _delta_baseline_failures,
    _diff_changed_paths,
    _diff_sections_by_path,
    _diff_vs_main_is_empty,
    _extract_attempted_write_paths,
    _extract_failed_pytest_nodes,
    _get_main_sha,
    _has_destructive_diff,
    _parse_pytest_collection_error,
    _has_flask_test_client_in_diff,
    _has_immediately_dangerous_diff,
    _has_invalid_fastapi_bootstrap_diff,
    _has_ui_surface_change,
    _is_core_file,
    _is_llm_provider_unavailable,
    _is_missing_test_target_error,
    _is_product_only_ui_task_diff,
    _is_valid_missing_tests_repair_diff,
    _is_valid_ui_test_diff,
    _known_failures_path,
    _load_known_baseline_failures,
    _load_valid_baseline_cache,
    _normalize_candidate_path,
    _required_endpoint_from_goal,
    _save_baseline_cache,
    _save_known_baseline_failures,
    _smoke_output_is_valid,
    _touches_rank_ui_contract_files,
    classify_failure,
)

from igris.core.supervisor_api import (  # noqa: F401
    RUN_LOCK,
    RUN_STORE,
    TERMINAL_RUN_STATUSES,
    _timestamp_is_due_check,
    _audit_counts_from_events,
    _enforce_completion_failure_invariant,
    _extract_issue_url_from_text,
    _is_terminal_status,
    _load_persisted_recent_runs,
    _reconcile_run_records,
    _run_has_resolved_failure,
    _safe_float,
    _stage_summary_from_run_dict,
    _timestamp_sort_key,
    cancel_supervised_run,
    get_supervised_run,
    get_supervisor_audit_summary,
    list_active_supervised_run_summaries,
    list_active_supervised_runs,
    list_supervised_runs,
    start_supervised_rank,
    start_supervised_rank_async,
    summarize_supervised_run,
)

from igris.core.supervisor_helpers import (  # noqa: F401
    _api_escalation_report_fragment as _api_escalation_report_fragment_helper,
    _build_reasoning_loop_repair_prompt as _build_reasoning_loop_repair_prompt_helper,
    _build_telemetry_fragment as _build_telemetry_fragment_helper,
    _build_wrong_file_edit_repair_prompt as _build_wrong_file_edit_repair_prompt_helper,
    _check_execution_budget as _check_execution_budget_helper,
    _compute_degraded_completion as _compute_degraded_completion_helper,
    _detect_capability_limit as _detect_capability_limit_helper,
    _get_max_codex_direct_budget_usd as _get_max_codex_direct_budget_usd_helper,
    _get_max_cost_per_issue as _get_max_cost_per_issue_helper,
    _get_max_cost_per_run as _get_max_cost_per_run_helper,
    _get_max_same_failure_retries as _get_max_same_failure_retries_helper,
    _goal_needs_preflight_decomposition as _goal_needs_preflight_decomposition_helper,
    _goal_prefers_tool_first as _goal_prefers_tool_first_helper,
    _goal_requires_backend_change as _goal_requires_backend_change_helper,
    _goal_requires_docs_or_config as _goal_requires_docs_or_config_helper,
    _goal_requires_tests as _goal_requires_tests_helper,
    _goal_requires_ui_visibility as _goal_requires_ui_visibility_helper,
    _goal_targets_rank_ui_card as _goal_targets_rank_ui_card_helper,
    _has_ui_visibility_change as _has_ui_visibility_change_helper,
    _infer_parent_issue_url as _infer_parent_issue_url_helper,
    _is_codex_direct_execution_enabled as _is_codex_direct_execution_enabled_helper,
    _is_structural_ceiling as _is_structural_ceiling_helper,
    _record_capability_signal as _record_capability_signal_helper,
    _repair_issue_already_created as _repair_issue_already_created_helper,
    _required_stages_green as _required_stages_green_helper,
    _sanitize_escalation_value as _sanitize_escalation_value_helper,
    _should_fast_track_capability_limit as _should_fast_track_capability_limit_helper,
    _stage_status_list as _stage_status_list_helper,
    _stage_status_template as _stage_status_template_helper,
    _strategy_for_repair as _strategy_for_repair_helper,
    _targeted_test_file as _targeted_test_file_helper,
    _timestamp_is_due as _timestamp_is_due_helper,
    _timestamp_now_iso as _timestamp_now_iso_helper,
    _timestamp_to_iso as _timestamp_to_iso_helper,
    _ui_stage_hard_forbidden_paths as _ui_stage_hard_forbidden_paths_helper,
    _validate_helper_response as _validate_helper_response_helper,
)

from igris.core.supervisor_mission_planning import (  # noqa: F401
    build_mission_plan as _build_mission_plan_helper,
    compute_degraded_completion as _compute_degraded_completion_mp_helper,
    init_stage_statuses as _init_stage_statuses_helper,
    mission_is_non_trivial as _mission_is_non_trivial_helper,
    path_in_allowed_family as _path_in_allowed_family_helper,
    required_stages_green as _required_stages_green_mp_helper,
    restore_ui_stage_scope as _restore_ui_stage_scope_helper,
    set_stage_status as _set_stage_status_helper,
    stage_is_already_satisfied as _stage_is_already_satisfied_helper,
    stage_status_list as _stage_status_list_mp_helper,
    stage_status_template as _stage_status_template_mp_helper,
    track_non_blocking_behavior as _track_non_blocking_behavior_helper,
    ui_stage_hard_forbidden_paths as _ui_stage_hard_forbidden_paths_mp_helper,
    ui_stage_retry_goal as _ui_stage_retry_goal_helper,
    validate_new_stage_paths as _validate_new_stage_paths_helper,
)
from igris.core.supervisor_completion import (  # noqa: F401
    cancelled as _cancelled_helper,
    cleanup_blocked_workspace as _cleanup_blocked_workspace_helper,
    cleanup_cancelled_workspace as _cleanup_cancelled_workspace_helper,
    complete_noop as _complete_noop_helper,
    persist_assignment_outcome as _persist_assignment_outcome_helper,
    pr_body as _pr_body_helper,
)
from igris.core.supervisor_repair_helpers import (  # noqa: F401
    preserve_targeted_tests_after_restore_retry as _preserve_targeted_tests_helper,
    quick_provider_check as _quick_provider_check_helper,
    re_scaffold_targeted_test_if_missing as _re_scaffold_helper,
    scaffold_missing_tests_target as _scaffold_missing_tests_helper,
    synthetic_missing_tests_diff as _synthetic_missing_tests_diff_helper,
)
from igris.core.supervisor_audit import (  # noqa: F401
    load_audit_index as _load_audit_index_helper,
    persist_audit_index as _persist_audit_index_helper,
    load_runs_index as _load_runs_index_helper,
    persist_runs_index as _persist_runs_index_helper,
    persist_run_snapshot as _persist_run_snapshot_helper,
    resolve_event_audit as _resolve_event_audit_helper,
    record_audit_checkpoint as _record_audit_checkpoint_helper,
)
from igris.core.supervisor_decomposition import (  # noqa: F401
    DECOMP_SHORT_PROMPT as _DECOMP_SHORT_PROMPT,
    api_helper_decompose as _api_helper_decompose_fn,
    ask_igris_decompose as _ask_igris_decompose_fn,
    blocked_decomposition_required as _blocked_decomposition_required_fn,
    deterministic_decompose_fallback as _deterministic_decompose_fallback_fn,
    plan_mission as _plan_mission_fn,
    run_decomposed_parallel as _run_decomposed_parallel_fn,
)

# AssignmentRouter — lazy import to avoid circular deps at module load
_assignment_router_available = False
try:
    from igris.core.assignment_router import AssignmentRequest, AssignmentDecision, AssignmentRouter
    from igris.core.assignment_outcomes import compute_task_signature, save_assignment_outcome
    _assignment_router_available = True
except ImportError:
    pass

# MissionBrain Advisory — lazy import, monitoring-only, never blocks run (#914)
_selected_advisory_available = False
try:
    from igris.agent.mission.selected_advisory import (
        enrich_cycle_selected as _enrich_cycle_selected,
        make_selected_monitoring_config as _make_selected_monitoring_config,
    )
    _selected_advisory_available = True
except ImportError:
    pass


class SelfRepairSupervisor:
    def __init__(self, project_root: str, backend: Optional[SupervisorBackend] = None):
        self.project_root = project_root
        self.backend = backend or LocalSupervisorBackend(project_root)
        self._run_store = SupervisorRunStore(project_root=project_root, strict_transitions=True)
        self._audit_path = Path(project_root) / ".igris" / "supervisor_audit.json"
        self._audit_index = self._load_audit_index()
        self._runs_path = Path(project_root) / ".igris" / "supervisor_runs.json"
        self._runs_lock = threading.RLock()
        self._runs_index = self._load_runs_index()
        self._failure_memory = FailureMemory(
            store_path=Path(project_root) / ".igris" / "failure_patterns.json"
        )
        # Issue #722 — mark zombie 'running' runs as 'interrupted' on startup
        self._startup_cleanup_zombie_runs()
        # Issue #733 — delete stale rank_pending.patch left by a crashed run
        self._startup_cleanup_stale_patch()

    def _startup_cleanup_zombie_runs(self) -> None:
        """Mark any run with status='running' as 'interrupted' on supervisor init.

        When the server restarts, runs that were active at shutdown are stuck
        forever as 'running'.  We detect them here by checking that their PID
        is not the current process (or has no PID at all) and transition them
        to 'interrupted' so the UI is not misleading.  (Issue #722)

        Parallel-run fix: runs already registered in the module-level RUN_STORE
        are actively managed by this process — skip them.  This allows multiple
        concurrent supervised runs (one SelfRepairSupervisor per run) without
        each new instantiation cancelling the others.
        """
        _logger = logging.getLogger("igris.supervisor.startup")
        current_pid = os.getpid()
        interrupted_ids = []
        with self._runs_lock:
            for run_id, record in self._runs_index.items():
                status = str(record.get("status", "")).strip().lower()
                if status not in ("running", "cancelling"):
                    continue
                # Skip runs that are already in the in-memory store — they are
                # live runs managed by this process (parallel multi-run support).
                if run_id in RUN_STORE:
                    continue
                run_pid = record.get("pid")
                if run_pid is not None and int(run_pid) == current_pid:
                    continue  # Started by this process — still live
                record["status"] = "interrupted"
                record["interrupted_at"] = time.time()
                record.setdefault("events", []).append({
                    "phase": "startup_cleanup",
                    "status": "interrupted",
                    "detail": f"Run was stuck as '{status}' on server restart; marked interrupted.",
                    "ts": time.time(),
                })
                interrupted_ids.append(run_id)
            if interrupted_ids:
                self._persist_runs_index()
        if interrupted_ids:
            _logger.warning(
                "Startup cleanup: %d zombie run(s) marked interrupted: %s",
                len(interrupted_ids), interrupted_ids,
            )

    def _startup_cleanup_stale_patch(self) -> None:
        """Delete rank_pending.patch left over from a crashed run.  (Issue #733)"""
        _logger = logging.getLogger("igris.supervisor.startup")
        patch_path = Path(self.project_root) / ".igris" / "rank_pending.patch"
        if patch_path.exists():
            try:
                patch_path.unlink()
                _logger.warning(
                    "Startup cleanup: removed stale rank_pending.patch "
                    "(leftover from previous crashed run)."
                )
            except OSError as exc:
                _logger.warning("Startup cleanup: could not remove stale patch: %s", exc)

    def _load_audit_index(self) -> Dict[str, Dict[str, Any]]:
        return _load_audit_index_helper(self)

    def _persist_audit_index(self) -> None:
        _persist_audit_index_helper(self)

    def _load_runs_index(self) -> Dict[str, Dict[str, Any]]:
        return _load_runs_index_helper(self)

    def _persist_runs_index(self) -> None:
        _persist_runs_index_helper(self)

    @staticmethod
    def _timestamp_to_iso(ts: Optional[float]) -> str:
        return _timestamp_to_iso_helper(ts)

    def _persisted_run_record(self, run: SupervisorRun) -> Dict[str, Any]:
        snapshot = summarize_supervised_run(run)
        payload = run.to_dict()
        events = payload.get("events") or []
        first_event_ts = events[0].get("timestamp") if events else None
        last_event = events[-1] if events else {}
        current_stage = str(snapshot.get("current_stage", "")).strip()
        failed_stage = str(snapshot.get("failed_stage", "")).strip()
        latest_event_summary = {
            "phase": str(last_event.get("phase", "")),
            "status": str(last_event.get("status", "")),
            "detail": str(last_event.get("detail", ""))[:500],
            "timestamp": last_event.get("timestamp"),
        }
        report_data = self._sanitize_escalation_value(payload.get("report") or {})
        cancelled_reason = str(report_data.get("cancelled_reason", "") or payload.get("cancel_reason", "") or "")
        record = {
            "run_id": payload.get("run_id", ""),
            "rank_id": payload.get("rank_id", ""),
            "issue_number": _parse_issue_number(
                (payload.get("report") or {}).get("issue_number", 0),
                str(payload.get("goal", "")),
            ) or None,
            "status": payload.get("status", ""),
            "outcome": payload.get("outcome", ""),
            "branch": payload.get("branch", ""),
            "current_stage": current_stage,
            "failed_stage": failed_stage,
            "failure_class": payload.get("failure_class", ""),
            "repair_cycles_used": int(payload.get("repair_cycles_used", 0) or 0),
            "max_repair_cycles": int(payload.get("max_repair_cycles", 0) or 0),
            "api_escalations_used": int(payload.get("api_escalations_used", 0) or 0),
            "api_escalations_failed_unconfigured": int(payload.get("api_escalations_failed_unconfigured", 0) or 0),
            "max_api_escalations_per_run": int(payload.get("max_api_escalations_per_run", 0) or 0),
            "api_budget_used_usd": round(_safe_float(payload.get("api_budget_used_usd", 0.0)), 6),
            "max_api_budget_usd": round(_safe_float(payload.get("max_api_budget_usd", 0.0)), 6),
            "escalation_issue_url": str(snapshot.get("escalation_issue_url", "")),
            "latest_event": latest_event_summary,
            "created_at": self._timestamp_to_iso(first_event_ts) or self._timestamp_now_iso(),
            "updated_at": self._timestamp_to_iso(snapshot.get("updated_at")) or self._timestamp_now_iso(),
            "final_report": report_data,
            "blocked_reason": str(report_data.get("blocked_reason", "")),
            "cancelled_reason": cancelled_reason,
            "next_action": str(snapshot.get("next_action", "")),
            "resolved_failure": bool((payload.get("report") or {}).get("resolved_failure", False)),
            "degraded_completion": bool((payload.get("report") or {}).get("degraded_completion", False)),
            "degraded_completion_reason": str((payload.get("report") or {}).get("degraded_completion_reason", "")),
            "state_conflict": bool(snapshot.get("state_conflict", False)),
            "warning": str(snapshot.get("warning", "")),
        }
        return _enforce_completion_failure_invariant(record)

    def _persist_run_snapshot(self, run: SupervisorRun) -> None:
        _persist_run_snapshot_helper(self, run)

    def _configure_run_tracking(self, run: SupervisorRun, config: RankSupervisorConfig) -> None:
        _lifecycle_configure_run_tracking(
            run=run,
            config=config,
            run_store=self._run_store,
            audit_resolver=self._resolve_event_audit,
            update_hook=self._persist_run_snapshot,
        )

    def _transition_run_status(self, run: SupervisorRun, new_status: str, reason: str = "") -> None:
        _lifecycle_transition_run_status(
            run=run,
            new_status=new_status,
            reason=reason,
            run_store=self._run_store,
        )

    def _cancel_if_requested(
        self,
        run: SupervisorRun,
        *,
        mission_plan: Optional[MissionPlan] = None,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[SupervisorRun]:
        if not bool(run.cancel_requested):
            return None
        reason = str(run.cancel_reason or "Cancelled by user").strip() or "Cancelled by user"
        return self._cancelled(
            run,
            reason,
            mission_plan=mission_plan,
            stage_statuses=stage_statuses,
            cleanup_workspace=True,
        )

    @staticmethod
    def _sanitize_escalation_value(value: Any) -> Any:
        return _sanitize_escalation_value_helper(value)

    def _event_scope_hash(self, event: SupervisorEvent) -> str:
        canonical = {
            "phase": event.phase,
            "status": event.status,
            "detail": _safe_redact(event.detail),
            "data": self._sanitize_escalation_value(event.data),
        }
        return sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _timestamp_now_iso() -> str:
        return _timestamp_now_iso_helper()

    @staticmethod
    def _timestamp_is_due(next_review_after: str) -> bool:
        return _timestamp_is_due_helper(next_review_after)

    def _resolve_event_audit(self, event: SupervisorEvent) -> None:
        _resolve_event_audit_helper(self, event)

    def record_audit_checkpoint(
        self,
        scope_hash: str,
        *,
        audit_status: str,
        reviewed_by: str = "supervisor",
        review_id: str = "",
        next_review_after: str = "",
        resolution_pr: str = "",
        notes: str = "",
    ) -> None:
        _record_audit_checkpoint_helper(
            self,
            scope_hash,
            audit_status=audit_status,
            reviewed_by=reviewed_by,
            review_id=review_id,
            next_review_after=next_review_after,
            resolution_pr=resolution_pr,
            notes=notes,
        )

    def _build_api_escalation_packet(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
        *,
        failure: str,
        cycle: int,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        recent_events = []
        for event in run.events[-10:]:
            recent_events.append({
                "phase": event.phase,
                "status": event.status,
                "detail": _safe_redact(event.detail),
                "data": self._sanitize_escalation_value(event.data),
                "audit_status": event.audit_status,
                "audit_scope_hash": event.audit_scope_hash,
            })
        packet = {
            "run_id": run.run_id,
            "rank_id": run.rank_id,
            "branch": run.branch,
            "goal": self._sanitize_escalation_value(config.goal),
            "failure_class": failure,
            "repair_cycle": cycle,
            "repair_cycles_used": run.repair_cycles_used,
            "mission_orchestration_mode": "staged" if stage_statuses else "single-stage-or-unknown",
            "stage_statuses": self._sanitize_escalation_value(stage_statuses or {}),
            "recent_events": recent_events,
            "policy": {
                "helper_output_is_advice_not_authority": True,
                "must_not_complete_product_manually": True,
                "no_secrets": True,
                "sanitized_logs_only": True,
            },
        }
        return self._sanitize_escalation_value(packet)

    @staticmethod
    def _validate_helper_response(payload: Any) -> Tuple[bool, Dict[str, Any], str]:
        return _validate_helper_response_helper(payload)

    def _maybe_api_escalate(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
        *,
        failure: str,
        cycle: int,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
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
        if not self.backend.api_helper_is_configured():
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

        packet = self._build_api_escalation_packet(run, config, failure=failure, cycle=cycle, stage_statuses=stage_statuses)
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
        result = self.backend.call_api_helper(
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
        valid, advice, error = self._validate_helper_response(raw_payload)
        if not valid:
            run.add("api_escalation_response", "failure", error,
                    api_helper_mode=effective_mode, codex_only=is_codex_only,
                    payload=self._sanitize_escalation_value(raw_payload))
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
            advice=self._sanitize_escalation_value(advice),
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
                    evidence=json.dumps(self._sanitize_escalation_value(advice), sort_keys=True),
                )
            except Exception:  # noqa: BLE001
                pass
        return advice

    # ------------------------------------------------------------------
    # Cost-policy execution strategy helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_max_same_failure_retries() -> int:
        """Max consecutive same-failure repairs before escalating to strong model."""
        return _get_max_same_failure_retries_helper()

    @staticmethod
    def _get_max_cost_per_run() -> float:
        """USD cap per supervised run; 0 means unlimited."""
        return _get_max_cost_per_run_helper()

    @staticmethod
    def _is_codex_direct_execution_enabled() -> bool:
        """Experimental Codex direct execution — off by default.

        Only active when IGRIS_ENABLE_CODEX_DIRECT_EXECUTION=true.
        Uses its own budget: IGRIS_MAX_CODEX_DIRECT_BUDGET_USD (default 0 = disabled).
        """
        return _is_codex_direct_execution_enabled_helper()

    @staticmethod
    def _get_max_codex_direct_budget_usd() -> float:
        """USD cap for experimental codex direct execution; 0 means disabled."""
        return _get_max_codex_direct_budget_usd_helper()

    @staticmethod
    def _get_max_cost_per_issue() -> float:
        """USD cap per issue; 0 means unlimited. Not yet enforced cross-run."""
        return _get_max_cost_per_issue_helper()

    @staticmethod
    def _collect_repair_diagnostics(
        run: "SupervisorRun",
        failure: str,
        cycle: int,
    ) -> Dict[str, Any]:
        """Collect diagnostics from prior attempts in the CURRENT run (#1103).

        Returns a dict of context keys that get merged into ``repair_context``
        so the repair reasoning worker knows:
        * why the previous attempt failed (stop_reason, failure_class, detail)
        * what tests failed (pytest output snippet)
        * how many repair cycles have been used
        * prior repair strategy decisions (for strategy awareness)
        """
        _ = (failure, cycle)  # preserve call signature and behavior contract
        return _collect_repair_diagnostics_helper(run)

    @staticmethod
    def _strategy_for_repair(
        run: SupervisorRun,
        has_execution_plan: bool,
    ) -> Tuple[str, Optional[str]]:
        """Return (strategy_name, preferred_profile) for the next repair cycle.

        Rules:
        - No execution plan → no strategy override (return empty/None).
        - same_failure_count < threshold → mini strategy (cheap, helper-guided).
        - same_failure_count >= threshold → strong strategy (gpt-4o escalation).

        Codex direct execution is experimental and NOT selected here; it requires
        IGRIS_ENABLE_CODEX_DIRECT_EXECUTION=true and is handled separately.
        """
        return _strategy_for_repair_helper(run, has_execution_plan)

    def _quick_provider_check(self, timeout: int = 10) -> bool:
        """Fast health-check: ping the configured LLM provider with a 10s timeout."""
        return _quick_provider_check_helper(timeout)

    @staticmethod
    def _check_execution_budget(run: SupervisorRun) -> Optional[str]:
        """Return failure_class string if execution budget is exceeded, else None."""
        return _check_execution_budget_helper(run)

    @staticmethod
    def _build_telemetry_fragment(
        time_to_first_diff_s: Optional[float],
        no_diff_count: int,
        decompose_count: int,
        attempt_outcomes: List[str],
        total_attempts: int,
    ) -> Dict[str, Any]:
        """Build execution-effectiveness telemetry fragment for run.report (Issue #715)."""
        return _build_telemetry_fragment_helper(
            time_to_first_diff_s, no_diff_count, decompose_count,
            attempt_outcomes, total_attempts,
        )

    @staticmethod
    def _repair_issue_already_created(run: SupervisorRun, failure: str) -> bool:
        return _repair_issue_already_created_helper(run, failure)

    @staticmethod
    def _goal_requires_backend_change(goal: str) -> bool:
        return _goal_requires_backend_change_helper(goal)

    @staticmethod
    def _goal_requires_docs_or_config(goal: str) -> bool:
        return _goal_requires_docs_or_config_helper(goal)

    @staticmethod
    def _goal_requires_tests(goal: str) -> bool:
        return _goal_requires_tests_helper(goal)

    def _mission_is_non_trivial(self, config: RankSupervisorConfig) -> bool:
        return _mission_is_non_trivial_helper(config)

    def _build_mission_plan(self, config: RankSupervisorConfig) -> MissionPlan:
        return _build_mission_plan_helper(config)

    @staticmethod
    def _stage_status_template(stage: MissionStage) -> Dict[str, Any]:
        return _stage_status_template_helper(stage)

    def _init_stage_statuses(self, plan: MissionPlan) -> Dict[str, Dict[str, Any]]:
        return _init_stage_statuses_helper(plan)

    def _set_stage_status(
        self,
        run: SupervisorRun,
        statuses: Dict[str, Dict[str, Any]],
        stage_id: str,
        status: str,
        detail: str,
        *,
        no_op: bool = False,
    ) -> None:
        _set_stage_status_helper(run, statuses, stage_id, status, detail, no_op=no_op)

    def _track_non_blocking_behavior(
        self,
        run: SupervisorRun,
        statuses: Dict[str, Dict[str, Any]],
        stage_id: str,
        code: str,
        detail: str,
    ) -> None:
        _track_non_blocking_behavior_helper(run, statuses, stage_id, code, detail)

    @staticmethod
    def _required_stages_green(
        statuses: Dict[str, Dict[str, Any]],
        *,
        include_final_report: bool = False,
        exclude_stage_ids: Optional[Set[str]] = None,
    ) -> bool:
        return _required_stages_green_helper(
            statuses,
            include_final_report=include_final_report,
            exclude_stage_ids=exclude_stage_ids,
        )

    @staticmethod
    def _compute_degraded_completion(
        *,
        completion_mode: str,
        runtime_refresh_required: bool,
        post_merge_smoke_success: bool,
        smoke_was_applicable: bool,
        failure_class: str,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]],
    ) -> Tuple[bool, str]:
        return _compute_degraded_completion_helper(
            completion_mode=completion_mode,
            runtime_refresh_required=runtime_refresh_required,
            post_merge_smoke_success=post_merge_smoke_success,
            smoke_was_applicable=smoke_was_applicable,
            failure_class=failure_class,
            stage_statuses=stage_statuses,
        )

    @staticmethod
    def _stage_status_list(statuses: Dict[str, Dict[str, Any]], plan: MissionPlan) -> List[Dict[str, Any]]:
        return _stage_status_list_helper(statuses, plan)

    def _stage_is_already_satisfied(self, stage: MissionStage, config: RankSupervisorConfig) -> bool:
        return _stage_is_already_satisfied_helper(stage, config, self.project_root)

    @staticmethod
    def _ui_stage_hard_forbidden_paths(
        statuses: Dict[str, Dict[str, Any]],
        config: RankSupervisorConfig,
    ) -> Set[str]:
        return _ui_stage_hard_forbidden_paths_helper(statuses, config)

    def _ui_stage_retry_goal(
        self,
        *,
        base_goal: str,
        stage: MissionStage,
        hard_forbidden: Set[str],
        retry_attempt: int,
        invalid_paths: List[str],
    ) -> str:
        return _ui_stage_retry_goal_helper(
            base_goal=base_goal,
            stage=stage,
            hard_forbidden=hard_forbidden,
            retry_attempt=retry_attempt,
            invalid_paths=invalid_paths,
        )

    def _restore_ui_stage_scope(
        self,
        run: SupervisorRun,
        stage: MissionStage,
        changed_paths: Set[str],
        observed_paths: List[str],
    ) -> Tuple[bool, List[str]]:
        return _restore_ui_stage_scope_helper(
            run, stage, changed_paths, observed_paths, self.backend,
        )

    @staticmethod
    def _path_in_allowed_family(path: str, families: List[str]) -> bool:
        return _path_in_allowed_family_helper(path, families)

    def _validate_new_stage_paths(
        self,
        stage: MissionStage,
        before_paths: Set[str],
        after_paths: Set[str],
        touched_files: List[str],
        changed_paths: Optional[Set[str]] = None,
    ) -> Tuple[bool, str]:
        return _validate_new_stage_paths_helper(
            stage, before_paths, after_paths, touched_files, changed_paths,
        )

    def _execute_staged_reasoning(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
        plan: MissionPlan,
        statuses: Dict[str, Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], str, bool]:
        aggregated_files: List[str] = []
        summaries: List[str] = []
        stage_failure = ""
        runtime_refresh_required = False
        last_status = "finished"
        last_stop_reason = "finish"
        loop_ids: List[str] = []

        for stage in plan.stages:
            if stage.stage_id in {"targeted_tests", "full_pytest", "pr_ci_merge", "post_merge_runtime", "final_report"}:
                continue

            if not stage.required and stage.stage_id == "docs_config_update" and not self._goal_requires_docs_or_config(config.goal):
                self._set_stage_status(
                    run,
                    statuses,
                    stage.stage_id,
                    "skipped",
                    "Optional docs/config stage skipped: mission does not require docs/config updates.",
                    no_op=True,
                )
                continue

            if not stage.required:
                self._set_stage_status(
                    run,
                    statuses,
                    stage.stage_id,
                    "skipped",
                    "Stage is optional for this mission and was skipped.",
                    no_op=True,
                )
                continue

            current_status = statuses.get(stage.stage_id, {}).get("status")
            if current_status in {"success", "skipped"}:
                self._set_stage_status(
                    run,
                    statuses,
                    stage.stage_id,
                    "success",
                    "Stage already validated; preserving progress across attempts.",
                    no_op=True,
                )
                continue

            if self._stage_is_already_satisfied(stage, config):
                self._set_stage_status(
                    run,
                    statuses,
                    stage.stage_id,
                    "success",
                    "Stage already satisfied; marked complete as no-op.",
                    no_op=True,
                )
                continue

            if stage.stage_id == "understand_locate":
                self._set_stage_status(
                    run,
                    statuses,
                    stage.stage_id,
                    "success",
                    "Mission scope classified and relevant files located.",
                    no_op=True,
                )
                continue

            ui_retry_attempt = 0
            ui_retry_budget = 2
            ui_retry_invalid_paths: List[str] = []
            ui_seen_paths: Set[str] = set()
            ui_hard_forbidden = (
                self._ui_stage_hard_forbidden_paths(statuses, config)
                if stage.stage_id == "ui_dashboard_change"
                else set()
            )
            while True:
                before_diff = self.backend.git_diff()
                before_paths = set(_diff_changed_paths(before_diff.output))
                stage_goal = (
                    self._ui_stage_retry_goal(
                        base_goal=config.goal,
                        stage=stage,
                        hard_forbidden=ui_hard_forbidden,
                        retry_attempt=ui_retry_attempt,
                        invalid_paths=ui_retry_invalid_paths,
                    )
                    if stage.stage_id == "ui_dashboard_change"
                    else (
                        f"{config.goal}\n\n"
                        f"[stage:{stage.stage_id}] {stage.goal}\n"
                        f"Allowed file families: {', '.join(stage.allowed_file_families) or 'mission-owned minimal scope'}.\n"
                        f"Acceptance criteria: {'; '.join(stage.acceptance_criteria)}"
                    )
                )
                stage_context = self._rank_initial_context(config, run=run)
                stage_context.update({
                    "mission_orchestration_mode": plan.mode,
                    "mission_stage_id": stage.stage_id,
                    "mission_stage_goal": stage.goal,
                    "mission_stage_allowed_file_families": stage.allowed_file_families,
                    "mission_stage_acceptance_criteria": stage.acceptance_criteria,
                    "mission_stage_validation": stage.validation,
                    "mission_stage_repair_strategy": stage.repair_strategy,
                })
                rank_task_type = (
                    "semantic_repair"
                    if stage.stage_id and "endpoint" in str(stage.stage_id).lower()
                    else "code_reasoning"
                )
                run.add(
                    "rank_reasoning",
                    "running",
                    f"Running staged mission reasoning: {stage.stage_id}",
                    stage_id=stage.stage_id,
                    timeout_seconds=config.reasoning_timeout_seconds,
                    task_type=rank_task_type,
                )
                result = self.backend.run_reasoning(
                    stage_goal,
                    max_steps=140,
                    initial_context=stage_context,
                    timeout=config.reasoning_timeout_seconds,
                    task_type=rank_task_type,
                )
                status = str(result.get("status", ""))
                stop_reason = str(result.get("stop_reason", ""))
                files_modified = list(result.get("files_modified") or [])
                attempted_write_paths = _extract_attempted_write_paths(result)
                if files_modified:
                    for path in files_modified:
                        if path not in aggregated_files:
                            aggregated_files.append(path)
                summaries.append(f"[{stage.stage_id}] {result.get('final_summary', '')}")
                loop_id = str(result.get("loop_id", ""))
                if loop_id:
                    loop_ids.append(loop_id)
                run.add(
                    "rank_reasoning",
                    status,
                    result.get("final_summary", ""),
                    stage_id=stage.stage_id,
                    loop_id=loop_id,
                    stop_reason=stop_reason,
                    files_modified=files_modified,
                    attempted_write_paths=attempted_write_paths,
                    orchestrator_used=result.get("orchestrator_used", False),
                    reasoning_execution_provider=result.get("reasoning_execution_provider", ""),
                    reasoning_execution_model=result.get("reasoning_execution_model", ""),
                    reasoning_execution_profile=result.get("reasoning_execution_profile", ""),
                    local_model_available=result.get("local_model_available", False),
                )
                after_diff = self.backend.git_diff()
                after_paths = set(_diff_changed_paths(after_diff.output))
                changed_paths = _changed_paths_between_diffs(before_diff.output, after_diff.output)
                observed_paths = list(dict.fromkeys(files_modified + attempted_write_paths + sorted(changed_paths)))
                valid_paths, invalid_paths = self._validate_new_stage_paths(
                    stage,
                    before_paths,
                    after_paths,
                    observed_paths,
                    changed_paths=changed_paths,
                )
                if not valid_paths:
                    invalid_path_list = [path.strip() for path in invalid_paths.split(",") if path.strip()]
                    if stage.stage_id == "ui_dashboard_change":
                        for path in observed_paths:
                            if self._path_in_allowed_family(path, stage.allowed_file_families):
                                ui_seen_paths.add(path)
                        if any(path in ui_hard_forbidden for path in invalid_path_list):
                            ui_retry_invalid_paths = invalid_path_list
                            restored_ok, restored_paths = self._restore_ui_stage_scope(
                                run,
                                stage,
                                changed_paths,
                                observed_paths,
                            )
                            if not restored_ok:
                                self._set_stage_status(
                                    run,
                                    statuses,
                                    stage.stage_id,
                                    "failure",
                                    "UI-stage recovery failed while restoring stage-local edits.",
                                )
                                stage_failure = "wrong_file_edit"
                                last_status = status or "blocked"
                                last_stop_reason = stop_reason or "blocked"
                                break
                            if ui_retry_attempt < ui_retry_budget:
                                ui_retry_attempt += 1
                                run.add(
                                    "ui_stage_retry",
                                    "running",
                                    "Retrying ui_dashboard_change with UI-only constraints after stage-local wrong_file_edit.",
                                    retry_attempt=ui_retry_attempt,
                                    retry_budget=ui_retry_budget,
                                    hard_forbidden=sorted(ui_hard_forbidden),
                                    restored_paths=restored_paths,
                                    invalid_paths=invalid_path_list,
                                )
                                continue
                            searched = sorted(ui_seen_paths) or ["(none)"]
                            self._set_stage_status(
                                run,
                                statuses,
                                stage.stage_id,
                                "failure",
                                "UI-only recovery exhausted after repeated wrong_file_edit attempts. "
                                f"UI files searched/touched: {', '.join(searched)}. "
                                f"Attempted forbidden edits: {', '.join(sorted(set(ui_retry_invalid_paths)) or ['(none)'])}.",
                            )
                            stage_failure = "wrong_file_edit"
                            last_status = status or "blocked"
                            last_stop_reason = stop_reason or "blocked"
                            break
                    self._set_stage_status(
                        run,
                        statuses,
                        stage.stage_id,
                        "failure",
                        f"Stage touched out-of-scope files: {invalid_paths}",
                    )
                    stage_failure = "wrong_file_edit"
                    last_status = status or "blocked"
                    last_stop_reason = stop_reason or "blocked"
                    break
                # Guard: a required stage with allowed_file_families that produced no
                # diff and is not pre-satisfied must be treated as failure, not success.
                # Without this check _validate_new_stage_paths returns (True, "") for
                # empty candidate_paths, and the stage falls through to success —
                # a false positive ("stage required segnato success senza evidence").
                # Only fires when status == "finished": timeout/blocked paths are handled
                # by the existing `if status != "finished":` block below.
                if (
                    status == "finished"
                    and stage.required
                    and stage.allowed_file_families
                    and not changed_paths
                    and not observed_paths
                    and not self._stage_is_already_satisfied(stage, config)
                ):
                    self._set_stage_status(
                        run,
                        statuses,
                        stage.stage_id,
                        "failure",
                        f"Required stage '{stage.stage_id}' produced no file changes "
                        "and is not already satisfied.",
                    )
                    stage_failure = "reasoning_loop_blocked"
                    last_status = status or "blocked"
                    last_stop_reason = stop_reason or "no_change"
                    break
                runtime_refresh_required = runtime_refresh_required or any(str(path).startswith("igris/") for path in files_modified)
                if status != "finished":
                    if (
                        stage.stage_id == "ui_dashboard_change"
                        and stop_reason in {"reasoning_timeout", "budget_exceeded"}
                    ):
                        has_ui_diff = _has_ui_surface_change(after_diff.output)
                        stage_satisfied = self._stage_is_already_satisfied(stage, config)
                        if has_ui_diff or stage_satisfied:
                            self._track_non_blocking_behavior(
                                run,
                                statuses,
                                stage.stage_id,
                                "ui_stage_timeout_accepted",
                                "UI stage timed out but validated UI visibility evidence was present; accepting stage with degraded status.",
                            )
                            self._set_stage_status(
                                run,
                                statuses,
                                stage.stage_id,
                                "success",
                                "UI stage accepted after timeout because mission-owned UI visibility evidence is present.",
                            )
                            last_status = "finished"
                            last_stop_reason = stop_reason or "reasoning_timeout"
                            break
                    if status in {"blocked", "error", "stopped"} or stop_reason in {"blocked", "ask_user", "max_steps", "reasoning_timeout", "budget_exceeded"}:
                        self._set_stage_status(
                            run,
                            statuses,
                            stage.stage_id,
                            "failure",
                            result.get("final_summary", "") or f"Stage {stage.stage_id} did not finish cleanly.",
                        )
                        stage_failure = classify_failure(reasoning_result=result)
                        last_status = status
                        last_stop_reason = stop_reason
                        break
                    self._track_non_blocking_behavior(
                        run,
                        statuses,
                        stage.stage_id,
                        "degraded_reasoning",
                        f"Stage {stage.stage_id} accepted with degraded reasoning status {status}/{stop_reason}.",
                    )
                self._set_stage_status(
                    run,
                    statuses,
                    stage.stage_id,
                    "success",
                    result.get("final_summary", "") or f"Stage {stage.stage_id} completed.",
                )
                last_status = status or "finished"
                last_stop_reason = stop_reason or "finish"
                break
            if stage_failure:
                break

        aggregated = {
            "status": last_status,
            "stop_reason": last_stop_reason,
            "files_modified": aggregated_files,
            "final_summary": "\n".join(part for part in summaries if part).strip(),
            "loop_id": ",".join(loop_ids),
            "goal": config.goal,
        }
        return aggregated, stage_failure, runtime_refresh_required

    def _run_preflight_phase(
        self,
        run: Optional["SupervisorRun"],
        config: RankSupervisorConfig,
    ) -> "Tuple[SupervisorRun, Optional[Dict[str, Any]]]":
        """Phase 1: init, git, baseline, smoke, assignment routing, mission plan.

        Returns (run, None) when blocked or cancelled, (run, ctx) on success.
        ctx keys: mission_plan, stage_statuses, assignment_decision, restart_command.
        """
        return _run_preflight_phase_fn(self, run, config)

    def _maybe_autoselect_next_roadmap(
        self,
        run: "SupervisorRun",
        config: RankSupervisorConfig,
    ) -> None:
        """Select and persist the next roadmap target after a completed run."""
        if not config.allow_roadmap_autoselect:
            return
        _next = self._select_next_roadmap_issue(config)
        if not _next:
            return

        # Issue #616 — skip candidates whose dependencies are unsatisfied
        try:
            from igris.core.dependency_checker import DependencyChecker
            _dep_checker = DependencyChecker(str(self.project_root))
            _dep_ok, _dep_unsat = _dep_checker.check(_next["number"])
            if not _dep_ok:
                run.add(
                    "watchdog_dependency_skip",
                    "skipped",
                    f"Roadmap candidate #{_next['number']} skipped: unsatisfied deps {_dep_unsat}",
                    issue_number=_next["number"],
                    unsatisfied_deps=_dep_unsat,
                )
                return
        except (ImportError, OSError, ValueError, KeyError) as _dep_exc:
            # Best-effort — never block roadmap autoselect on dep check error
            run.add("watchdog_dependency_skip", "error",
                    f"dep check error (non-fatal): {_dep_exc}", issue_number=_next["number"])

        run.add(
            "roadmap_next_target",
            "selected",
            f"Next roadmap target: #{_next['number']} — {_next.get('title', '')}",
            issue_number=_next["number"],
            issue_title=_next.get("title", ""),
        )
        try:
            _hint_path = Path(self.project_root) / ".igris" / "next_roadmap_target.json"
            _hint_path.parent.mkdir(parents=True, exist_ok=True)
            _hint_path.write_text(
                json.dumps(
                    {
                        "issue_number": _next["number"],
                        "issue_title": _next.get("title", ""),
                        "selected_at": time.time(),
                        "selected_by_run": run.run_id,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as _e:
            run.add("roadmap_next_target", "write_failed", str(_e))


    def _run_rank_loop(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
        *,
        mission_plan: MissionPlan,
        stage_statuses: Dict[str, Dict[str, Any]],
        assignment_decision: Optional[Any],
        restart_command: str,
    ) -> SupervisorRun:
        """Phase 2: rank attempt loop and finalization.

        Delegates to :func:`igris.core.supervisor_rank_loop.run_rank_loop`.
        """
        return _run_rank_loop_fn(
            self,
            run,
            config,
            mission_plan=mission_plan,
            stage_statuses=stage_statuses,
            assignment_decision=assignment_decision,
            restart_command=restart_command,
        )

    def _select_next_roadmap_issue(
        self, config: "RankSupervisorConfig"
    ) -> Optional[Dict[str, Any]]:
        """Query GitHub for next roadmap issue. Only for root runs (autochain_depth=0)."""
        if config.autochain_depth != 0:
            return None
        try:
            import subprocess as _sub
            result = _sub.run(
                ["gh", "issue", "list", "--label", "roadmap", "--state", "open",
                 "--json", "number,title,labels", "--limit", "200"],
                capture_output=True, text=True, cwd=self.project_root, timeout=30,
            )
            if result.returncode != 0:
                return None
            issues = json.loads(result.stdout or "[]")
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError, TypeError, ValueError):
            return None

        EPIC_SKIP = ("epic", "phase", "milestone", "overview", "arch", "design")

        def _is_epic(issue: Dict[str, Any]) -> bool:
            title = (issue.get("title") or "").lower()
            labels = [l.get("name", "").lower() for l in (issue.get("labels") or [])]
            # Use word-boundary matching to avoid false positives from substrings:
            # e.g. "arch" must not match "hierarchy", "phase" must not match "phase-2bis" label.
            # We check labels by membership (exact element), not substring.
            _is_epic_title = any(
                re.search(r"\b" + k + r"\b", title) for k in EPIC_SKIP
            )
            return _is_epic_title or "epic" in labels

        def _priority(issue: Dict[str, Any]) -> tuple:
            labels = [l.get("name", "").lower() for l in (issue.get("labels") or [])]
            p = 99
            if any(x in labels for x in ("p1", "priority: high", "priority:high")):
                p = 1
            elif any(x in labels for x in ("p2", "priority: medium", "priority:medium")):
                p = 2
            return (p, issue.get("number", 9999))

        candidates = [i for i in issues if not _is_epic(i)]
        if not candidates:
            return None
        candidates.sort(key=_priority)
        return candidates[0]

    def _rank_passed(
        self,
        reasoning: Dict[str, Any],
        diff_stat: CommandResult,
        targeted: CommandResult,
        full: CommandResult,
        smoke: CommandResult,
    ) -> bool:
        has_diff = bool(diff_stat.output.strip())
        stop_reason = str(reasoning.get("stop_reason", ""))
        files_modified: List[str] = list(reasoning.get("files_modified") or [])
        # `git diff --stat` only shows tracked file changes. When the reasoning worker
        # creates NEW files (untracked), they won't appear in the diff even though real
        # work was done. Detect this by checking whether the reported modified paths
        # actually exist on disk — if they do, treat it as a valid diff.
        if not has_diff and files_modified:
            has_diff = any(
                (Path(self.project_root) / f).exists()
                for f in files_modified
            )
        delivered_changes = bool(files_modified) or (
            has_diff and stop_reason == "reasoning_timeout"
        )
        reasoning_finished = reasoning.get("status") == "finished"
        return (
            (reasoning_finished or delivered_changes)
            and delivered_changes
            and has_diff
            and targeted.success
            and full.success
            and smoke.success
        )

    def _ui_noop_completion_eligible(
        self,
        config: RankSupervisorConfig,
        diff_stat: CommandResult,
        targeted: CommandResult,
        full: CommandResult,
        smoke: CommandResult,
    ) -> bool:
        if not self._goal_requires_ui_visibility(config.goal):
            return False
        if not self._goal_targets_rank_ui_card(config.goal):
            return False
        if diff_stat.output.strip():
            return False
        if not (targeted.success and full.success and smoke.success):
            return False
        return self._rank_ui_card_contract_satisfied() and self._rank_ui_visibility_signal_present()

    def _rank_initial_context(
        self,
        config: RankSupervisorConfig,
        run: Optional["SupervisorRun"] = None,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "rank_test": config.rank_id,
            "project_root": self.project_root,
            "must_not_push_directly_to_main": True,
            "must_not_merge_if_tests_fail": True,
            "suppress_human_gate": True,
            "must_not_ask_user": True,
            "supervised": True,
            "expected_endpoint_file": "igris/web/server.py",
            "safe_edit_policy": (
                "For existing large files use insert_after, insert_before, "
                "replace_range or append_file. Never full-file write server.py."
            ),
            "fastapi_test_policy": (
                "API tests must import create_app from igris.web.server and use "
                "TestClient(create_app()). Do not import app from igris.web.server."
            ),
            "implementation_quality_policy": (
                "Write real implementation code, not stubs. "
                "Do NOT add '# Placeholder', '# TODO', '# FIXME', or 'pass' in the "
                "function body. Do NOT return empty dicts, empty lists, or empty strings "
                "as field values. The implementation will be rejected by the semantic "
                "acceptance gate if stub patterns are detected."
            ),
        }
        if self._goal_prefers_tool_first(config.goal):
            context["tool_first_policy"] = (
                "For broad analysis/mapping tasks, prefer deterministic tool-first work. "
                "Collect compact facts with ripgrep/python scripts, then reason on the summary "
                "instead of loading many files into LLM context."
            )
            context["tool_first_snapshot"] = self._build_tool_first_snapshot()
        if self._goal_requires_ui_visibility(config.goal):
            ui_card_contract_goal = self._goal_targets_rank_ui_card(config.goal)
            ui_contract_satisfied = ui_card_contract_goal and self._rank_ui_card_contract_satisfied()
            context["must_add_ui_visibility"] = True
            context["ui_visibility_policy"] = (
                "If the goal requires UI/dashboard visibility, modify a UI surface "
                "such as igris/web/templates/index.html, igris/web/static/js/app.js, "
                "or igris/web/static/css/style.css. Backend-only changes are not enough."
            )
            context["ui_contract_already_satisfied"] = ui_contract_satisfied
            if ui_contract_satisfied:
                context["ui_contract_policy"] = (
                    "The /api/rank/ui-card contract is already satisfied in "
                    "igris/web/server.py. Do not modify this route. Focus only on "
                    "minimal UI/dashboard visibility edits and related UI checks."
                )
            if ui_card_contract_goal:
                context["ui_test_policy"] = (
                    "UI tests must stay minimal and exact. Do not add placeholder routes, "
                    "commented example paths, or unrelated assertions. Test the exact "
                    "required endpoint plus the minimal UI/dashboard visibility signal. "
                    "For /api/rank/ui-card, only assert the contract keys app, rank, status, "
                    "and capability. Do not assert extra JSON keys such as data."
                )
            else:
                context["ui_test_policy"] = (
                    "UI/dashboard tests must stay minimal and exact for this mission. "
                    "Validate only the required endpoint contract and the requested "
                    "visibility signal. Do not add placeholder routes or unrelated assertions."
                )
        for target in config.targeted_tests:
            if target.startswith("tests/test_") and target.endswith(".py"):
                target_path = Path(self.project_root) / target
                if target_path.exists():
                    context["targeted_test_file_exists"] = target
                    context["targeted_test_policy"] = (
                        f"{target} already exists. Edit this file in place when needed. "
                        "Do not rediscover tests/ and do not recreate the file."
                    )
                else:
                    context["must_create_test_file"] = target
                    context["anti_loop_instruction"] = (
                        f"Do not repeat test discovery after tests/ is known. "
                        f"Create {target} directly."
                    )
                break

        # --- Inject MBOP Phase 1 intake fields (#1040) ---
        # These let the reasoning loop know the exact target file/module and acceptance
        # criteria from the start, eliminating blind find_files exploration.
        _intake = getattr(run, "mbop_intake", None) if run is not None else None
        if _intake is not None:
            try:
                if getattr(_intake, "what", ""):
                    context["mbop_what"] = str(_intake.what)[:300]
                if getattr(_intake, "where", ""):
                    context["mbop_where"] = str(_intake.where)[:300]
                if getattr(_intake, "why", ""):
                    context["mbop_why"] = str(_intake.why)[:300]
                if getattr(_intake, "acceptance_criteria", []):
                    context["mbop_acceptance_criteria"] = list(_intake.acceptance_criteria[:10])
                if getattr(_intake, "constraints", []):
                    context["mbop_constraints"] = list(_intake.constraints[:5])
                if getattr(_intake, "extraction_ok", False):
                    context["mbop_intake_ok"] = True
            except (TypeError, AttributeError, ValueError):
                pass  # best-effort — never block the run

        # --- Inject MBOP Phase 10-11 prior-run lessons for the same issue (BUG2 fix) ---
        # Phases 10-11 fire after supervisor.run() returns, so they're not available
        # during the CURRENT run's repair cycle.  However, for SUBSEQUENT runs on the
        # same issue, these lessons prevent repeating the same mistakes.
        if config.issue_number:
            try:
                from igris.core.mbop_log import read_for_issue
                prior_events = read_for_issue(str(self.project_root), config.issue_number)
                # Extract most recent Phase 11 lessons and Phase 10 criteria_missing
                prior_lessons: list = []
                prior_criteria_missing: list = []
                for ev in reversed(prior_events):
                    if ev.get("phase") == "mbop_phase11_post_task_eval" and not prior_lessons:
                        extra = ev.get("extra", {}) or {}
                        lessons_raw = extra.get("lessons", [])
                        prior_lessons = [str(l) for l in lessons_raw if l][:5]
                for ev in reversed(prior_events):
                    if ev.get("phase") == "mbop_phase10_satisfaction_gate" and not prior_criteria_missing:
                        extra = ev.get("extra", {}) or {}
                        prior_criteria_missing = [str(c) for c in extra.get("criteria_missing", []) if c][:5]
                        break
                if prior_lessons:
                    context["mbop_prior_lessons"] = prior_lessons
                if prior_criteria_missing:
                    context["mbop_prior_criteria_missing"] = prior_criteria_missing
            except (ImportError, OSError, ValueError, KeyError, TypeError):
                pass  # best-effort — never block the run

        return context

    @staticmethod
    def _goal_prefers_tool_first(goal: str) -> bool:
        return _goal_prefers_tool_first_helper(goal)

    def _build_tool_first_snapshot(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {"project_root": str(self.project_root), "file_count": 0, "top_dirs": []}
        try:
            proc = subprocess.run(
                ["rg", "--files"],
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8,
                check=False,
            )
            files = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
            snapshot["file_count"] = len(files)
            counts: Dict[str, int] = {}
            for rel in files:
                top = rel.split("/", 1)[0]
                counts[top] = counts.get(top, 0) + 1
            snapshot["top_dirs"] = [
                {"name": name, "files": count}
                for name, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:8]
            ]
        except (subprocess.SubprocessError, OSError):
            return snapshot
        return snapshot

    def _preapply_quality_gate(self, goal: str, diff_text: str, files_modified: List[str]) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        lowered_goal = (goal or "").lower()
        lowered_diff = (diff_text or "").lower()
        if any(tok in lowered_goal for tok in ("test", "pytest")) and not any("test" in str(path).lower() for path in files_modified):
            reasons.append("goal_mentions_tests_but_no_test_file_touched")
        if any(marker in lowered_diff for marker in ("# placeholder", "# todo", "# fixme", "\n+pass\n", "+    pass", "+        pass")):
            reasons.append("stub_pattern_detected_in_diff")

        # Self-modification gate — blocks patches that touch core files without approval (#523)
        # Fail-closed for core files: if gate is unavailable and a core file is being modified,
        # block the patch rather than silently allowing it.
        has_core_file = any(_is_core_file(str(f)) for f in (files_modified or []))
        try:
            from igris.core.self_modification_gate import SelfModificationGate
            gate = SelfModificationGate(str(self.project_root))
            gate_result = gate.check(diff=diff_text or "", run_smoke=False)
            if not gate_result.approved:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "SelfModificationGate blocked patch (touched_core=%s): %s",
                    gate_result.touched_core,
                    gate_result.reason,
                )
                reasons.append(f"self_modification_gate_blocked:{gate_result.reason}")
        except ImportError as _exc:
            import logging as _logging
            if has_core_file:
                # Fail-closed: cannot verify safety of core file modification
                _logging.getLogger(__name__).error(
                    "SelfModificationGate unavailable for core file(s) %s — blocked (fail-closed): %s",
                    [f for f in (files_modified or []) if _is_core_file(str(f))],
                    _exc,
                )
                reasons.append(f"self_modification_gate_unavailable_core_blocked:{_exc}")
            else:
                # Non-core: degraded-safe, allow with warning
                _logging.getLogger(__name__).warning(
                    "SelfModificationGate unavailable for non-core file(s) (degraded): %s", _exc
                )
        except (OSError, ValueError, TypeError, AttributeError) as _exc:
            import logging as _logging
            if has_core_file:
                _logging.getLogger(__name__).error(
                    "SelfModificationGate error for core file(s) — blocked: %s", _exc
                )
                reasons.append(f"self_modification_gate_error_core_blocked:{_exc}")
            else:
                _logging.getLogger(__name__).warning(
                    "SelfModificationGate error for non-core file(s) (degraded): %s", _exc
                )

        return (len(reasons) == 0), reasons

    def _preapply_quality_gate_file(self, file_path: str, patch_content: str) -> Tuple[bool, str]:
        """Per-file quality gate. Fail-closed for core files if gate unavailable."""
        is_core = _is_core_file(file_path)
        try:
            from igris.core.self_modification_gate import SelfModificationGate
            gate = SelfModificationGate(str(self.project_root))
            decision = gate.check(diff=patch_content or "", run_smoke=False)
            if not decision.approved:
                return False, f"SelfModificationGate blocked: {decision.reason}"
            return True, "gate_ok"
        except ImportError as e:
            if is_core:
                return False, f"SelfModificationGate unavailable for core file '{file_path}' — blocked (fail-closed): {e}"
            else:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "SelfModificationGate unavailable for non-core file %s (degraded): %s", file_path, e
                )
                return True, "gate_degraded_non_core"
        except (OSError, ValueError, TypeError, AttributeError) as e:
            if is_core:
                return False, f"SelfModificationGate error for core file '{file_path}' — blocked: {e}"
            else:
                import logging as _logging
                _logging.getLogger(__name__).warning("SelfModificationGate error for non-core %s: %s", file_path, e)
                return True, "gate_error_non_core"

    def _rank_ui_card_contract_satisfied(self) -> bool:
        server_path = Path(self.project_root) / "igris/web/server.py"
        if not server_path.exists():
            return False
        try:
            content = server_path.read_text(encoding="utf-8")
        except OSError:
            return False

        route_present = (
            "@app.get('/api/rank/ui-card')" in content
            or '@app.get("/api/rank/ui-card")' in content
        )
        if not route_present:
            return False

        def _has_pair(key: str, value: str) -> bool:
            return (
                f"'{key}': '{value}'" in content
                or f'"{key}": "{value}"' in content
            )

        return all(
            _has_pair(key, value)
            for key, value in (
                ("app", "IGRIS_GPT"),
                ("rank", "A++"),
                ("status", "ok"),
                ("capability", "ui-visible-supervised"),
            )
        )

    def _rank_ui_visibility_signal_present(self) -> bool:
        index_path = Path(self.project_root) / "igris/web/templates/index.html"
        if not index_path.exists():
            return False
        try:
            content = index_path.read_text(encoding="utf-8").lower()
        except OSError:
            return False
        return "rank-ui-card" in content and "ui-visible-supervised" in content

    @staticmethod
    def _goal_requires_ui_visibility(goal: str) -> bool:
        return _goal_requires_ui_visibility_helper(goal)

    @staticmethod
    def _goal_targets_rank_ui_card(goal: str) -> bool:
        return _goal_targets_rank_ui_card_helper(goal)

    @staticmethod
    def _build_reasoning_loop_repair_prompt(
        stage_id: str,
        goal: str,
        previous_reasoning_output: str,
        repair_cycle: int,
    ) -> str:
        """
        Costruisce un repair goal progressivo per reasoning_loop_blocked.

        Ciclo 1: semplifica il task, output minimo, approccio incrementale.
        Ciclo 2+: suddividi nel componente più piccolo risolvibile, ignora ottimizzazioni.
        """
        return _build_reasoning_loop_repair_prompt_helper(
            stage_id, goal, previous_reasoning_output, repair_cycle,
        )

    @staticmethod
    def _build_wrong_file_edit_repair_prompt(
        stage_id: str,
        goal: str,
        wrong_paths: List[str],
        allowed_families: List[str],
        repair_cycle: int,
    ) -> str:
        """
        Costruisce un repair goal per wrong_file_edit che:
        1. Elenca i file modificati fuori scope
        2. Elenca i file consentiti per lo stage
        3. Chiede di ripetere SOLO la modifica consentita
        4. Al ciclo 2+: aggiunge vincolo hard
        """
        return _build_wrong_file_edit_repair_prompt_helper(
            stage_id, goal, wrong_paths, allowed_families, repair_cycle,
        )

    @staticmethod
    def _has_ui_visibility_change(files_modified: List[str]) -> bool:
        return _has_ui_visibility_change_helper(files_modified)

    @staticmethod
    def _targeted_test_file(config: RankSupervisorConfig) -> str:
        return _targeted_test_file_helper(config)

    def _synthetic_missing_tests_diff(self, config: RankSupervisorConfig) -> str:
        target = self._targeted_test_file(config)
        return _synthetic_missing_tests_diff_helper(self.project_root, target)

    def _re_scaffold_targeted_test_if_missing(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
    ) -> bool:
        return _re_scaffold_helper(self, run, config)

    def _preserve_targeted_tests_after_restore_retry(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
        failure: str,
    ) -> None:
        _preserve_targeted_tests_helper(self, run, config, failure)

    def _scaffold_missing_tests_target(self, config: RankSupervisorConfig) -> CommandResult:
        target = self._targeted_test_file(config)
        return _scaffold_missing_tests_helper(self.project_root, target, config.goal)

    def _repair_cycle(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
        failure: str,
        cycle: int,
        *,
        preserve_validated_progress: bool = False,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> bool:
        return _repair_cycle_fn(
            self,
            run,
            config,
            failure,
            cycle,
            preserve_validated_progress=preserve_validated_progress,
            stage_statuses=stage_statuses,
        )

    def run(
        self,
        config: RankSupervisorConfig,
        run: Optional[SupervisorRun] = None,
    ) -> SupervisorRun:
        """Thin orchestrator — delegates to preflight and rank-loop phases."""
        # Issue #540 — create WorkSession for this run (best-effort, never blocks)
        _work_session = None
        try:
            from igris.core.work_session import WorkSession as _WS
            _work_session = _WS.create(goal=config.goal, mission_id=None)
        except (ImportError, OSError, ValueError, TypeError):
            pass

        run, ctx = self._run_preflight_phase(run, config)
        if ctx is None:
            if _work_session is not None:
                try:
                    _work_session.remember(str(self.project_root))
                except (OSError, TypeError, ValueError):
                    pass
            return run

        result = self._run_rank_loop(run, config, **ctx)

        if _work_session is not None:
            try:
                _commands = [
                    {"action_type": e.phase, "outcome": e.status, "duration_ms": 0.0}
                    for e in result.events
                    if e.phase not in {"start", "queued"}
                ]
                _work_session.remember(str(self.project_root), commands_run=_commands)
            except (OSError, TypeError, ValueError):
                pass

        return result

    def _stage_report_fragment(
        self,
        mission_plan: Optional[MissionPlan],
        stage_statuses: Optional[Dict[str, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        if not mission_plan or not stage_statuses:
            return {}
        return {
            "mission_orchestration": {
                "mode": mission_plan.mode,
                "stages": self._stage_status_list(stage_statuses, mission_plan),
            }
        }

    @staticmethod
    def _api_escalation_report_fragment(run: SupervisorRun) -> Dict[str, Any]:
        return _api_escalation_report_fragment_helper(run)

    def _complete_rank(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
        branch: str,
        *,
        completion_mode: str = "direct",
        runtime_refresh_required: bool = False,
        mission_plan: Optional[MissionPlan] = None,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> SupervisorRun:
        cancelled = self._cancel_if_requested(run, mission_plan=mission_plan, stage_statuses=stage_statuses)
        if cancelled is not None:
            return cancelled
        restart_command = config.service_restart_command if not config.defer_service_restart else ""
        post_merge_smoke: Optional[CommandResult] = None
        manual_remaining = ""
        if stage_statuses and "pr_ci_merge" in stage_statuses:
            self._set_stage_status(run, stage_statuses, "pr_ci_merge", "running", "Executing PR/CI/merge workflow.")
        if config.dry_run:
            manual_remaining = "delivery skipped by dry_run"
            run.add("github", "dry_run", "Commit/PR/merge skipped by dry_run")
            if stage_statuses and "pr_ci_merge" in stage_statuses:
                self._set_stage_status(
                    run,
                    stage_statuses,
                    "pr_ci_merge",
                    "skipped",
                    "PR/CI/merge skipped because dry_run is enabled.",
                    no_op=True,
                )
            if stage_statuses and "post_merge_runtime" in stage_statuses:
                self._set_stage_status(
                    run,
                    stage_statuses,
                    "post_merge_runtime",
                    "skipped",
                    "Post-merge runtime checks skipped because dry_run is enabled.",
                    no_op=True,
                )
        else:
            commit = self.backend.commit(f"feat: complete supervised {config.rank_id}", ["igris", "tests"])
            run.add("commit", "success" if commit.success else "failure", _command_detail(commit))
            if not commit.success and "nothing to commit" in (commit.output or "") + (commit.error or ""):
                # Working tree unexpectedly clean — attempt patch-based recovery.
                # The diff was saved to disk before tests ran; apply it now.
                _patch_path = Path(self.project_root) / ".igris" / "rank_pending.patch"
                if _patch_path.exists():
                    run.add("commit_patch_recovery", "running", "Applying saved diff patch to recover working tree")
                    apply = self.backend.git_apply_patch(
                        str(_patch_path),
                        timeout=30,
                    )
                    run.add(
                        "commit_patch_recovery",
                        "success" if apply.success else "failure",
                        _command_detail(apply),
                    )
                    if apply.success:
                        commit = self.backend.commit(
                            f"feat: complete supervised {config.rank_id}", None
                        )
                        run.add(
                            "commit",
                            "success" if commit.success else "failure",
                            _command_detail(commit),
                        )
                    try:
                        _patch_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            elif commit.success:
                try:
                    (Path(self.project_root) / ".igris" / "rank_pending.patch").unlink(missing_ok=True)
                except OSError:
                    pass
            if not commit.success:
                return self._blocked(
                    run,
                    "infrastructure_bug",
                    "Commit failed",
                    mission_plan=mission_plan,
                    stage_statuses=stage_statuses,
                )
            if config.allow_github_pr:
                push = self.backend.push_branch(branch)
                run.add("push", "success" if push.success else "failure", _command_detail(push))
                pr = self.backend.open_pr(branch, f"feat: supervised {config.rank_id}", self._pr_body(run))
                run.add("pr", "success" if pr.success else "failure", _command_detail(pr))
                ci = self.backend.wait_ci()
                run.add("ci", "success" if ci.success else "failure", _command_detail(ci))
                if stage_statuses and "pr_ci_merge" in stage_statuses:
                    self._set_stage_status(
                        run,
                        stage_statuses,
                        "pr_ci_merge",
                        "success" if ci.success else "failure",
                        "PR workflow green." if ci.success else "PR workflow failed or CI not green.",
                    )
                if config.allow_merge_if_green and ci.success:
                    merge = self.backend.merge_pr()
                    run.add("merge", "success" if merge.success else "failure", _command_detail(merge))
                    pull = self.backend.pull_main()
                    run.add("pull_main", "success" if pull.success else "failure", _command_detail(pull))
                    if config.defer_service_restart and runtime_refresh_required:
                        run.add(
                            "post_merge_smoke",
                            "deferred",
                            "Post-merge smoke deferred until the runtime is restarted and refreshed.",
                            runtime_refresh_required=True,
                        )
                        if stage_statuses and "post_merge_runtime" in stage_statuses:
                            self._set_stage_status(
                                run,
                                stage_statuses,
                                "post_merge_runtime",
                                "skipped",
                                "Post-merge runtime smoke deferred until runtime refresh.",
                                no_op=True,
                            )
                    else:
                        post_merge_smoke = self.backend.smoke(
                            config.required_smoke_endpoints,
                            restart_command,
                        )
                        run.add(
                            "post_merge_smoke",
                            "success" if post_merge_smoke.success else "failure",
                            _command_detail(post_merge_smoke),
                        )
                        if stage_statuses and "post_merge_runtime" in stage_statuses:
                            self._set_stage_status(
                                run,
                                stage_statuses,
                                "post_merge_runtime",
                                "success" if post_merge_smoke.success else "failure",
                                "Post-merge runtime smoke passed."
                                if post_merge_smoke.success
                                else "Post-merge runtime smoke failed.",
                            )
                        if not post_merge_smoke.success:
                            self._transition_run_status(run, "blocked", "post-merge smoke failed")
                            run.outcome = "Blocked"
                            run.failure_class = "infrastructure_bug"
                            _deg, _deg_reason = self._compute_degraded_completion(
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
                            run.report.update(self._api_escalation_report_fragment(run))
                            run.report.update(self._stage_report_fragment(mission_plan, stage_statuses))
                            run.touch()
                            return run
                elif config.allow_merge_if_green and not ci.success:
                    manual_remaining = "merge skipped because CI is not green"
                    if stage_statuses and "post_merge_runtime" in stage_statuses:
                        self._set_stage_status(
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
                        self._set_stage_status(
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
                    self._set_stage_status(
                        run,
                        stage_statuses,
                        "pr_ci_merge",
                        "skipped",
                        "PR workflow disabled by config.",
                        no_op=True,
                    )
                if stage_statuses and "post_merge_runtime" in stage_statuses:
                    self._set_stage_status(
                        run,
                        stage_statuses,
                        "post_merge_runtime",
                        "skipped",
                        "Post-merge runtime checks skipped because PR workflow is disabled.",
                        no_op=True,
                    )
        final_report_ok = True
        if stage_statuses and "final_report" in stage_statuses:
            if self._required_stages_green(stage_statuses):
                self._set_stage_status(run, stage_statuses, "final_report", "success", "All required mission stages are green.")
            else:
                self._set_stage_status(run, stage_statuses, "final_report", "failure", "Required mission stage is missing or failed.")
                final_report_ok = False
        if final_report_ok:
            self._transition_run_status(run, "completed", "rank completion reached")
            run.outcome = "Completed"
        else:
            self._transition_run_status(run, "blocked", "final_report required stage failure")
            run.outcome = "Blocked"
            run.failure_class = "infrastructure_bug"
        post_smoke_success = False if post_merge_smoke is None else post_merge_smoke.success
        # post_merge_smoke is only non-None when a merge was actually executed
        smoke_applicable = post_merge_smoke is not None
        degraded, degraded_reason = self._compute_degraded_completion(
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
        run.report.update(self._api_escalation_report_fragment(run))
        run.report.update(self._stage_report_fragment(mission_plan, stage_statuses))
        run.touch()
        return run

    def _complete_noop(
        self,
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
        return _complete_noop_helper(
            self,
            run,
            completion_mode=completion_mode,
            runtime_refresh_required=runtime_refresh_required,
            detail=detail,
            post_merge_smoke=post_merge_smoke,
            mission_plan=mission_plan,
            stage_statuses=stage_statuses,
            exclude_stage_ids=exclude_stage_ids,
        )

    def _cleanup_blocked_workspace(self, run: SupervisorRun) -> None:
        _cleanup_blocked_workspace_helper(run, self.backend)

    def _cleanup_cancelled_workspace(self, run: SupervisorRun) -> None:
        _cleanup_cancelled_workspace_helper(run, self.backend)

    def _cancelled(
        self,
        run: SupervisorRun,
        reason: str,
        *,
        mission_plan: Optional[MissionPlan] = None,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
        cleanup_workspace: bool = True,
    ) -> SupervisorRun:
        return _cancelled_helper(
            self,
            run,
            reason,
            mission_plan=mission_plan,
            stage_statuses=stage_statuses,
            cleanup_workspace=cleanup_workspace,
        )

    # ------------------------------------------------------------------
    # Capability-limit detection and mission decomposition
    # ------------------------------------------------------------------

    @staticmethod
    def _record_capability_signal(run: SupervisorRun, signal: str) -> None:
        _record_capability_signal_helper(run, signal)

    @staticmethod
    def _detect_capability_limit(run: SupervisorRun) -> Optional[str]:
        """Return the triggering signal if capability limit reached, or None.

        Fires when any single signal reaches CAPABILITY_LIMIT_THRESHOLD, or when
        the combined total of all distinct signals reaches the threshold (mixed-failure
        capability wall — e.g. one reasoning_timeout + one no_diff_repair).
        """
        return _detect_capability_limit_helper(run)

    @staticmethod
    def _is_structural_ceiling(run: SupervisorRun, triggering_signal: str) -> bool:
        """Return True when the capability limit is structural, not transient.

        Only `max_steps_ceiling` (strong_execution profile exhausted its step budget)
        qualifies as a true structural ceiling.  Pure `reasoning_timeout` or
        `no_diff_repair` signals indicate transient failures where decomposition may
        still help — these go through the normal decompose path.
        """
        return _is_structural_ceiling_helper(run, triggering_signal)

    @staticmethod
    def _should_fast_track_capability_limit(
        run: SupervisorRun,
        failure: str,
    ) -> Optional[str]:
        """Return capability signal when we should decompose immediately."""
        return _should_fast_track_capability_limit_helper(run, failure)

    def _handle_capability_limit(
        self,
        run: SupervisorRun,
        triggering_signal: str,
        config: "RankSupervisorConfig",
        mission_plan: Optional["MissionPlan"],
        stage_statuses: Optional[Dict[str, Dict[str, Any]]],
        *,
        cleanup_workspace: bool = True,
    ) -> SupervisorRun:
        """Block with `capability_ceiling_reached` or `decomposition_required`.

        When the ceiling is structural (strong model already exhausted), skip the
        expensive decompose LLM call and emit `capability_ceiling_reached` so the
        watchdog can skip the issue immediately after the first failure.
        """
        if self._is_structural_ceiling(run, triggering_signal):
            run.add(
                "capability_ceiling",
                "detected",
                f"Structural capability ceiling confirmed ({triggering_signal} × "
                f"{run.capability_signals.get(triggering_signal, 0)}); "
                "no stronger model available — skipping decomposition call.",
                triggering_signal=triggering_signal,
                capability_signals=dict(run.capability_signals),
            )
            return self._blocked(
                run,
                "capability_ceiling_reached",
                (
                    f"Capability ceiling reached ({triggering_signal} × "
                    f"{run.capability_signals.get(triggering_signal, 0)}); "
                    "model cannot make further progress on this mission."
                ),
                mission_plan=mission_plan,
                stage_statuses=stage_statuses,
                cleanup_workspace=cleanup_workspace,
            )
        decomposition = self._ask_igris_decompose(run, config)
        return self._blocked_decomposition_required(
            run,
            triggering_signal,
            (
                f"Capability limit detected ({triggering_signal} × "
                f"{run.capability_signals[triggering_signal]}); "
                "mission requires decomposition."
            ),
            decomposition,
            config=config,
            mission_plan=mission_plan,
            stage_statuses=stage_statuses,
            cleanup_workspace=cleanup_workspace,
        )

    def _plan_mission(
        self, run: SupervisorRun, config: RankSupervisorConfig
    ) -> Dict[str, Any]:
        """Pre-flight read-only reasoning pass: estimate scope and flag if
        decomposition is needed BEFORE any code is written.

        Returns a MissionScope dict (may be empty on planning failure — the run
        proceeds normally in that case so planning never blocks a mission).
        """
        return _plan_mission_fn(self, run, config)

    def _ask_igris_decompose(
        self, run: SupervisorRun, config: RankSupervisorConfig
    ) -> Dict[str, Any]:
        """Ask IGRIS to decompose a too-large mission into sub-missions.

        Uses a fallback chain:
          1. Local reasoning short-prompt (max_steps=15)
          2. API helper (if configured and budget allows)
          3. Deterministic fallback (always succeeds)
        """
        return _ask_igris_decompose_fn(self, run, config)

    def _api_helper_decompose(
        self,
        run: "SupervisorRun",
        config: "RankSupervisorConfig",
        signals: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        """Try to obtain a decomposition from the API helper.

        Returns a decomposition dict with generated_by='api_helper' on success,
        or None if the helper is not available, budget is exhausted, or the
        response is invalid.
        """
        return _api_helper_decompose_fn(self, run, config, signals)

    @staticmethod
    def _deterministic_decompose_fallback(
        goal: str,
        signals: Dict[str, int],
    ) -> Dict[str, Any]:
        """Always produce a syntactically complete decomposition from the goal text."""
        return _deterministic_decompose_fallback_fn(goal, signals)

    _DESTRUCTIVE_KEYWORDS = frozenset({
        "drop", "delete", "destroy", "wipe", "format", "truncate",
        "rm -rf", "reset --hard", "force push", "force-push",
        "sudo", "kubectl apply", "terraform apply", "deploy production",
        "database migration", "data migration",
    })

    # Maximum nesting level for auto-chained sub-missions.
    # At this depth the policy must NOT create GitHub issues — doing so would
    # produce orphaned issues that can never be auto-run.
    _MAX_AUTOCHAIN_DEPTH: int = 2

    @staticmethod
    def _goal_needs_preflight_decomposition(goal: str) -> bool:
        return _goal_needs_preflight_decomposition_helper(goal)

    @staticmethod
    def _decomposition_policy(
        decomposition: Dict[str, Any],
        config: "RankSupervisorConfig",
    ) -> str:
        """Decide how to handle a valid decomposition.

        Returns one of:
          "auto_create_subissues"       — safe, GitHub enabled, create issues automatically
          "request_human_approval"      — unsafe or GitHub disabled
          "block_unsafe_decomposition"  — secret/destructive content detected
        """
        # Require valid structure
        fields_missing = decomposition.get("_fields_missing", [])
        sub_missions = decomposition.get("sub_missions") or []
        if fields_missing or not sub_missions:
            return "request_human_approval"

        # Require explicit opt-in to autonomous sub-issue creation
        if not config.allow_auto_subissues or config.dry_run:
            return "request_human_approval"

        # Do not block safe sub-issue creation at max autochain depth.
        # Depth limits are enforced by _autorun_guards for child execution, so
        # decomposition can still progress without requiring a manual approval
        # deadlock on large missions.

        # Check for destructive/secret/dangerous content
        all_text = " ".join([
            str(decomposition.get("why_too_large", "")),
            str(decomposition.get("first_sub_mission", "")),
            *[
                " ".join([
                    str(s.get("title", "")),
                    str(s.get("goal", "")),
                    *[str(c) for c in (s.get("acceptance_criteria") or [])],
                ])
                for s in sub_missions
            ],
        ]).lower()

        # Check for secret patterns (raw or already-redacted by _safe_redact).
        # _safe_redact uses "<REDACTED>" (canonical marker); older code used "***redacted***".
        # Both must be caught here because _ask_igris_decompose redacts final_summary
        # before passing the parsed decomposition to this policy (#1337).
        from igris.core.redaction import SECRET_RE as _secret_re_canonical, _PREFIX_RE as _prefix_re_canonical
        if (
            _secret_re_canonical.search(all_text)
            or _prefix_re_canonical.search(all_text)
            or "<redacted>" in all_text
            or "***redacted***" in all_text
        ):
            return "block_unsafe_decomposition"

        # Check for destructive keywords
        if any(kw in all_text for kw in SelfRepairSupervisor._DESTRUCTIVE_KEYWORDS):
            return "request_human_approval"

        return "auto_create_subissues"

    def _auto_create_subissues(
        self,
        run: SupervisorRun,
        config: RankSupervisorConfig,
        decomposition: Dict[str, Any],
        triggering_signal: str,
    ) -> List[str]:
        """Create one GitHub issue per sub_mission and return list of created URLs.

        Each issue body includes parent run context, generated_by, risk, scopes.
        After creating all issues, posts a summary comment on the parent issue (if
        a parent URL can be inferred from config.goal or run.report).
        """
        sub_missions = decomposition.get("sub_missions") or []
        generated_by = decomposition.get("generated_by", "unknown")
        why_too_large = _safe_redact(str(decomposition.get("why_too_large", "")))
        first_sub = decomposition.get("first_sub_mission", "")

        # Collect parent issue labels to propagate to sub-issues (roadmap, P*, phase-*).
        # This ensures the watchdog can discover sub-issues the same way it finds parent
        # roadmap issues.  Best-effort: if we can't read the parent labels, we proceed
        # without them rather than blocking sub-issue creation.
        _parent_inherit_labels: List[str] = []
        try:
            import re as _re, subprocess as _subp2
            _parent_num_m = _re.search(r"#(\d+)", config.goal or "")
            if _parent_num_m:
                _parent_num = int(_parent_num_m.group(1))
                _pl = _subp2.run(
                    ["gh", "issue", "view", str(_parent_num), "--json", "labels"],
                    capture_output=True, text=True, cwd=self.project_root, timeout=15,
                )
                if _pl.returncode == 0:
                    import json as _json2
                    _raw_labels = _json2.loads(_pl.stdout or "{}").get("labels", [])
                    for _lbl in _raw_labels:
                        _n = (_lbl.get("name") or "").lower()
                        if _n in ("roadmap", "created-by:igris") or _n.startswith("p") and len(_n) == 2 and _n[1].isdigit() or _n.startswith("phase-"):
                            _parent_inherit_labels.append(_lbl.get("name", _n))
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            pass  # Label propagation is best-effort

        # Epic #1075 — Dependency-order scheduling: build execution waves and log
        # the wave structure so the autochain can respect creation order.
        try:
            from igris.core.parallel_task_runner import ParallelTask, build_dependency_order
            _dep_tasks = [
                ParallelTask(
                    task_id=str(sub.get("title", f"sub_{j}")),
                    goal=str(sub.get("goal", "")),
                    depends_on=list(sub.get("dependencies") or []),
                    initial_context={"file_scopes": sub.get("allowed_file_scopes") or []},
                )
                for j, sub in enumerate(sub_missions)
            ]
            _waves = build_dependency_order(_dep_tasks)
            _wave_summary = [
                {"wave": w, "tasks": [t.task_id for t in wave]}
                for w, wave in enumerate(_waves)
            ]
            run.add(
                "subissue_dependency_order",
                "computed",
                f"Dependency waves: {len(_waves)} wave(s) for {len(sub_missions)} sub-mission(s)",
                wave_count=len(_waves),
                waves=_wave_summary,
            )
        except (ImportError, TypeError, ValueError, KeyError, AttributeError) as _dep_exc:
            run.add(
                "subissue_dependency_order",
                "skipped",
                f"build_dependency_order unavailable: {_dep_exc}",
            )

        created_urls: List[str] = []
        run.add(
            "subissue_creation",
            "running",
            f"Creating {len(sub_missions)} sub-issue(s) from decomposition.",
            count=len(sub_missions),
            generated_by=generated_by,
        )

        # Build a set of existing open issue titles to deduplicate sub-missions.
        # Fixes #613: IGRIS was creating identical sub-missions on every decomposition.
        existing_open_titles: set = set()
        try:
            import subprocess as _subp
            _existing = _subp.run(
                ["gh", "issue", "list", "--state", "open", "--limit", "50",
                 "--json", "number,title"],
                capture_output=True, text=True, cwd=self.project_root, timeout=20,
            )
            if _existing.returncode == 0:
                import json as _json
                for _issue in _json.loads(_existing.stdout or "[]"):
                    existing_open_titles.add((_issue.get("title") or "").lower().strip())
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError, TypeError, ValueError):
            pass  # Dedup is best-effort; if it fails, allow creation to proceed

        # Epic #1078 — Enforce max sub-issue count to prevent noisy decompositions.
        _MAX_SUBISSUES = int(os.getenv("IGRIS_MAX_SUBISSUES_PER_DECOMPOSITION", "12"))
        if len(sub_missions) > _MAX_SUBISSUES:
            run.add(
                "subissue_creation",
                "capped",
                f"Decomposition produced {len(sub_missions)} sub-missions; capping at {_MAX_SUBISSUES}.",
                original_count=len(sub_missions),
                cap=_MAX_SUBISSUES,
            )
            sub_missions = sub_missions[:_MAX_SUBISSUES]

        # Epic #1078 — File scope overlap detection.
        # Build ParallelTask-like dicts from sub_missions so we can detect which
        # files would be touched by multiple concurrent sub-issues, and log
        # conflicts so the operator can add explicit serialisation (depends_on).
        try:
            from igris.core.parallel_task_runner import ParallelTask, detect_file_conflicts
            _ptasks = [
                ParallelTask(
                    task_id=str(sub.get("title", f"sub_{j}")),
                    goal=str(sub.get("goal", "")),
                    initial_context={"file_scopes": sub.get("allowed_file_scopes") or []},
                    depends_on=list(sub.get("dependencies") or []),
                )
                for j, sub in enumerate(sub_missions)
            ]
            _scope_conflicts = detect_file_conflicts(_ptasks)
            if _scope_conflicts:
                run.add(
                    "subissue_scope_conflict",
                    "warning",
                    f"File scope overlap detected across {len(_scope_conflicts)} file(s): "
                    + "; ".join(
                        f"{f} → {ids}" for f, ids in list(_scope_conflicts.items())[:5]
                    ),
                    conflicts=_scope_conflicts,
                )
        except (ImportError, TypeError, ValueError, KeyError, AttributeError) as _sc_exc:
            run.add(
                "subissue_scope_conflict",
                "skipped",
                f"Scope conflict detection unavailable: {_sc_exc}",
            )

        for i, sub in enumerate(sub_missions):
            title = _safe_redact(str(sub.get("title", f"Sub-task {i+1}")))
            goal_text = _safe_redact(str(sub.get("goal", "")))
            risk = str(sub.get("risk_level", "medium"))
            scopes = sub.get("allowed_file_scopes") or []
            tests = sub.get("tests") or []
            criteria = sub.get("acceptance_criteria") or []
            deps = sub.get("dependencies") or []

            # Epic #1078 — Title hygiene: reject vague or auto-generated titles.
            # Normalized format: <Area>: <concrete action> for <scope>
            _title_lower = title.lower().strip()
            _title_is_vague = (
                not _title_lower
                or len(_title_lower) < 5
                or _title_lower.startswith("implement github issue #")
                or "igris/**" in _title_lower
                or _title_lower.startswith("sub-task ")
                or _title_lower.startswith("sub_task ")
                or _title_lower == f"sub-task {i+1}"
            )
            if _title_is_vague:
                # Build a meaningful title from goal text rather than a generic placeholder
                _goal_short = goal_text.strip()[:60].rstrip(".").rstrip(",")
                _area = (scopes[0].split("/")[0] if scopes else config.rank_id).strip("/")
                _clean_title = f"{_area}: {_goal_short}" if _goal_short else f"{config.rank_id}: sub-task {i+1}"
                run.add(
                    "subissue_title_hygiene",
                    "normalized",
                    f"Vague title normalized: {title!r} → {_clean_title!r}",
                    index=i + 1,
                    original_title=title,
                    normalized_title=_clean_title,
                )
                title = _clean_title

            # Epic #1078 — AC validation: generate minimal ACs when missing or vague.
            _VAGUE_AC_MARKERS = {"_not specified_", "not specified", "tbd", "todo", "n/a", ""}
            _valid_criteria = [
                c for c in criteria
                if str(c).strip().lower() not in _VAGUE_AC_MARKERS and len(str(c).strip()) > 10
            ]
            if len(_valid_criteria) < 3:
                # Generate deterministic acceptance criteria from goal and tests
                _generated_acs = []
                if goal_text:
                    _generated_acs.append(f"Implementation matches goal: {goal_text[:120]}")
                if tests:
                    _generated_acs.append(f"All test targets pass: {', '.join(str(t) for t in tests[:3])}")
                else:
                    _generated_acs.append("pytest passes with no regressions on the full test suite")
                _generated_acs.append("No new lint errors introduced; changed files are importable")
                _generated_acs.append("PR diff is minimal and scoped to the stated file targets")
                _generated_acs += list(_valid_criteria)  # keep any valid ones the model produced
                criteria = _generated_acs
                run.add(
                    "subissue_ac_generated",
                    "auto_generated",
                    f"Sub-mission {i+1}: generated {len(_generated_acs)} ACs (had {len(_valid_criteria)} valid).",
                    index=i + 1,
                    title=title,
                    ac_count=len(_generated_acs),
                )

            # Epic #1078 — Goal-hash dedup: also check normalized goal text, not just title.
            import hashlib as _hashlib
            _goal_hash = _hashlib.md5(goal_text.lower().strip().encode()).hexdigest()[:8]
            _goal_hash_key = f"__goal_hash:{_goal_hash}"
            if _goal_hash_key in existing_open_titles:
                run.add(
                    "subissue_dedup",
                    "skipped",
                    f"Sub-mission {i+1} has duplicate goal hash ({_goal_hash}): {title}",
                    index=i + 1,
                    title=title,
                    reason="dedup:goal_hash_match",
                )
                continue
            existing_open_titles.add(_goal_hash_key)

            # Dedup: skip sub-mission if an open issue with same title already exists
            if title.lower().strip() in existing_open_titles:
                # Find existing URL to include in created_urls so autochain works
                try:
                    _found = _subp.run(
                        ["gh", "issue", "list", "--state", "open", "--search", title,
                         "--json", "number,title", "--limit", "5"],
                        capture_output=True, text=True, cwd=self.project_root, timeout=20,
                    )
                    if _found.returncode == 0:
                        for _fi in _json.loads(_found.stdout or "[]"):
                            if (_fi.get("title") or "").lower().strip() == title.lower().strip():
                                _repo_url = "https://github.com/Solarfox88/IGRIS_GPT"
                                _existing_url = f"{_repo_url}/issues/{_fi['number']}"
                                created_urls.append(_existing_url)
                                run.add(
                                    "subissue_dedup",
                                    "skipped",
                                    f"Sub-mission {i+1} already exists: {title}",
                                    index=i + 1,
                                    title=title,
                                    url=_existing_url,
                                    reason="dedup:title_match",
                                )
                                break
                except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
                    pass
                continue
            out_of_scope = sub.get("out_of_scope") or []
            success_signal = str(sub.get("success_signal", "")).strip()
            failure_fallback = str(sub.get("failure_fallback", "")).strip()

            scopes_md = "\n".join(f"- `{s}`" for s in scopes) if scopes else "_not specified_"
            tests_md = "\n".join(f"- `{t}`" for t in tests) if tests else "_not specified_"
            criteria_md = "\n".join(f"- {c}" for c in criteria) if criteria else "_not specified_"
            deps_md = ", ".join(deps) if deps else "none"
            oos_md = "\n".join(f"- {o}" for o in out_of_scope) if out_of_scope else "_not specified_"
            success_md = success_signal or "All acceptance criteria verified by the supervisor"
            fallback_md = failure_fallback or "Escalate to human review; reopen parent issue"

            body = (
                f"## Sub-mission {i+1} of {len(sub_missions)}\n\n"
                f"**Goal:** {goal_text}\n\n"
                f"**Risk level:** {risk}\n"
                f"**Dependencies:** {deps_md}\n\n"
                f"### Acceptance criteria\n{criteria_md}\n\n"
                f"### File scopes\n{scopes_md}\n\n"
                f"### Test targets\n{tests_md}\n\n"
                f"### Out of scope\n{oos_md}\n\n"
                f"### Success signal\n{success_md}\n\n"
                f"### Failure fallback\n{fallback_md}\n\n"
                f"---\n"
                f"**Parent run:** `{run.run_id}` (rank `{run.rank_id}`)\n"
                f"**Decomposition source:** `{generated_by}`\n"
                f"**Trigger signal:** `{triggering_signal}`\n"
                f"**Why original mission was too large:** {why_too_large}\n"
                f"**Original goal:** {_safe_redact(config.goal)}\n"
            )

            result = self.backend.create_issue(title, body)
            if result.success:
                url = result.output.strip()
                created_urls.append(url)
                run.add(
                    "subissue_created",
                    "success",
                    f"Created sub-issue: {title}",
                    index=i + 1,
                    title=title,
                    url=url,
                    risk=risk,
                )
                # Propagate parent roadmap/priority/phase labels so the watchdog
                # can discover and schedule sub-issues automatically.
                # Always add "no-decompose" so the watchdog knows this is a leaf
                # sub-issue that must be implemented directly, not decomposed again.
                _sub_labels = list(_parent_inherit_labels)
                if "no-decompose" not in _sub_labels:
                    _sub_labels.append("no-decompose")
                # Also add depends-on-NNN labels for dependencies between sub-issues
                for _dep in deps:
                    # deps may be issue URLs or "Sub-task N" style references
                    import re as _re2
                    _dep_num = _re2.search(r"#?(\d+)", str(_dep))
                    if _dep_num:
                        _sub_labels.append(f"depends-on-{_dep_num.group(1)}")
                try:
                    import subprocess as _subp3
                    _subp3.run(
                        ["gh", "issue", "edit", url, "--add-label",
                         ",".join(_sub_labels)],
                        capture_output=True, text=True,
                        cwd=self.project_root, timeout=20,
                    )
                except (subprocess.SubprocessError, OSError):
                    pass  # Label application is best-effort
            else:
                run.add(
                    "subissue_created",
                    "failure",
                    f"Failed to create sub-issue: {title}",
                    index=i + 1,
                    title=title,
                    error=_safe_redact(result.error),
                )

        # Post summary comment on parent issue if we can infer the URL.
        parent_url = self._infer_parent_issue_url(config.goal)
        if parent_url and created_urls:
            sub_list = "\n".join(
                f"- {url} — {sub.get('title','?')}"
                for url, sub in zip(created_urls, sub_missions)
            )
            comment = (
                f"## Decomposition sub-issues created\n\n"
                f"Run `{run.run_id}` produced {len(created_urls)} sub-issue(s) "
                f"via `{generated_by}`:\n\n{sub_list}\n\n"
                f"First sub-mission to run: **{_safe_redact(first_sub)}**"
            )
            comment_result = self.backend.update_issue(parent_url, comment)
            run.add(
                "parent_issue_updated",
                "success" if comment_result.success else "failure",
                "Posted sub-issue summary to parent issue.",
                parent_url=parent_url,
                sub_count=len(created_urls),
            )

        run.add(
            "subissue_creation",
            "success" if created_urls else "failure",
            f"Sub-issue creation complete. Created {len(created_urls)}/{len(sub_missions)}.",
            created_count=len(created_urls),
            total=len(sub_missions),
            urls=created_urls,
        )
        return created_urls

    @staticmethod
    def _infer_parent_issue_url(goal: str) -> Optional[str]:
        """Extract a GitHub issue URL from the goal string if present."""
        return _infer_parent_issue_url_helper(goal)

    @staticmethod
    def _autorun_guards(
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
        if config.autochain_depth >= SelfRepairSupervisor._MAX_AUTOCHAIN_DEPTH:
            return False, f"max_autochain_depth: depth={config.autochain_depth}>={SelfRepairSupervisor._MAX_AUTOCHAIN_DEPTH}"
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
        max_cost_per_run = SelfRepairSupervisor._get_max_cost_per_run()
        if max_cost_per_run > 0 and run.execution_budget_used_usd >= max_cost_per_run:
            return False, f"budget_exceeded: {run.execution_budget_used_usd:.4f}>={max_cost_per_run:.4f}"

        return True, ""

    def _autorun_first_subissue(
        self,
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
        import re as _re

        ok, skip_reason = self._autorun_guards(run, config, decomposition, created_urls)
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
        fetch_result = self.backend.fetch_issue(first_url)
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
            child_run = _self_mod.start_supervised_rank_async(child_data, project_root=str(self.project_root))
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


    def _run_decomposed_parallel(
        self,
        sub_goals: List[str],
        base_max_steps: int = 20,
        preferred_profile: Optional[str] = None,
        depends_on_map: Optional[Dict[str, List[str]]] = None,
    ) -> List[dict]:
        """Run decomposed sub-goals in parallel, respecting dependency order (Epic #1075)."""
        return _run_decomposed_parallel_fn(
            self, sub_goals, base_max_steps, preferred_profile, depends_on_map
        )

    def run_parallel_submissions(
        self,
        sub_missions: List[Dict[str, Any]],
        max_steps: int = 20,
        preferred_profile: Optional[str] = None,
        max_concurrent: int = 3,
    ) -> Dict[str, Any]:
        """Public API: run sub-missions as parallel AgentReasoningLoop tasks (Epic #1075).

        Sub-missions are executed in dependency order (waves). Conflicts are
        detected and logged before execution. Results are merged into a summary.

        Args:
            sub_missions: list of dicts with 'title', 'goal', 'dependencies',
                          'allowed_file_scopes' keys (same format as decomposition output)
            max_steps: max reasoning steps per task
            preferred_profile: LLM profile override
            max_concurrent: max tasks running simultaneously

        Returns:
            merge_results() summary dict with total, succeeded, failed, skipped,
            merged_files, all_success + waves structure.
        """
        from igris.core.parallel_task_runner import (
            ParallelTask, ParallelTaskRunner,
            build_dependency_order, detect_file_conflicts, merge_results,
        )

        tasks = [
            ParallelTask(
                task_id=str(sub.get("title", f"sub_{i}")),
                goal=str(sub.get("goal", "")),
                max_steps=max_steps,
                preferred_profile=preferred_profile,
                depends_on=list(sub.get("dependencies") or []),
                initial_context={
                    "file_scopes": sub.get("allowed_file_scopes") or [],
                    "acceptance_criteria": sub.get("acceptance_criteria") or [],
                    "risk_level": sub.get("risk_level", "medium"),
                },
            )
            for i, sub in enumerate(sub_missions)
        ]

        # Pre-run checks
        conflicts = detect_file_conflicts(tasks)
        waves = build_dependency_order(tasks)

        _logger = logging.getLogger("igris.supervisor.parallel")
        _logger.info(
            "run_parallel_submissions: %d tasks in %d wave(s), %d file conflict(s)",
            len(tasks), len(waves), len(conflicts),
        )

        if conflicts:
            _logger.warning(
                "run_parallel_submissions: conflicts on %s — "
                "consider adding depends_on to serialise",
                list(conflicts.keys())[:5],
            )

        runner = ParallelTaskRunner(self.project_root, max_concurrent=max_concurrent)
        parallel_results = runner.run_sync(tasks)

        summary = merge_results(parallel_results)
        summary["waves"] = [
            {"wave": w, "tasks": [t.task_id for t in wave]}
            for w, wave in enumerate(waves)
        ]
        summary["conflicts"] = conflicts
        return summary

    def _blocked_decomposition_required(
        self,
        run: SupervisorRun,
        triggering_signal: str,
        detail: str,
        decomposition: Dict[str, Any],
        *,
        config: Optional[RankSupervisorConfig] = None,
        mission_plan: Optional[MissionPlan] = None,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
        cleanup_workspace: bool = False,
    ) -> SupervisorRun:
        """Block the run with failure_class='decomposition_required' and attach the
        IGRIS-generated decomposition to the run report and durable storage."""
        return _blocked_decomposition_required_fn(
            self, run, triggering_signal, detail, decomposition,
            config=config, mission_plan=mission_plan,
            stage_statuses=stage_statuses, cleanup_workspace=cleanup_workspace,
        )

    # ------------------------------------------------------------------

    def _blocked(
        self,
        run: SupervisorRun,
        failure: str,
        detail: str,
        *,
        mission_plan: Optional[MissionPlan] = None,
        stage_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
        cleanup_workspace: bool = False,
    ) -> SupervisorRun:
        self._transition_run_status(run, "blocked", detail)
        run.outcome = "Blocked"
        run.failure_class = failure
        run.completion_mode = f"blocked/{failure}"  # (#147)
        run.add("blocked", "blocked", detail)
        if cleanup_workspace:
            self._cleanup_blocked_workspace(run)
        if stage_statuses and "final_report" in stage_statuses:
            self._set_stage_status(run, stage_statuses, "final_report", "failure", f"Run blocked: {failure}.")
        run.report = {"autonomous": False, "blocked_reason": detail}
        if run.acceptance_evidence is not None:
            run.report["acceptance_evidence"] = run.acceptance_evidence
        run.report.update(self._api_escalation_report_fragment(run))
        run.report.update(self._stage_report_fragment(mission_plan, stage_statuses))
        run.touch()
        # Issue #733 — ensure rank_pending.patch is cleaned up on any blocked/failure path
        try:
            _stale_patch = Path(self.project_root) / ".igris" / "rank_pending.patch"
            if _stale_patch.exists():
                _stale_patch.unlink(missing_ok=True)
                run.add("patch_cleanup", "success", "rank_pending.patch removed on blocked run")
        except (OSError, PermissionError):
            pass
        # Record capability-related failures so future runs can learn from history.
        # Skip infrastructure/baseline failures — they're environment issues, not
        # capability limits, and would pollute similarity matching.
        _SKIP_MEMORY_CLASSES = frozenset({"pytest_failure", "workspace_dirty", "infrastructure_bug", "test_runner_timeout"})
        if failure not in _SKIP_MEMORY_CLASSES and hasattr(self, "_failure_memory"):
            try:
                self._failure_memory.record(
                    goal=getattr(run, "goal", "") or "",
                    failure_class=failure,
                    capability_signals=dict(run.capability_signals),
                    repair_cycles=run.repair_cycles_used,
                )
            except Exception:  # noqa: BLE001
                pass
        # Issue #914 — MissionBrain Advisory diagnostic (monitoring-only).
        # Computes a recovery recommendation for failed/blocked runs without
        # surfacing it in reports (should_emit=False, is_gate=False).
        # Wrapped in bare except so it can NEVER block or modify run outcome.
        if _selected_advisory_available:
            try:
                _goal_status = "partial" if run.repair_cycles_used > 0 else "failed"
                _adv_cycle = {
                    "cycle_id": getattr(run, "run_id", "unknown"),
                    "current_loop_decision": "blocked",
                    "mission_brain_decision": _goal_status,
                    "report_type": "diagnostic",
                    "failure_class": failure,
                    "capability_signals": dict(run.capability_signals),
                }
                _adv_cfg = _make_selected_monitoring_config(include_blocked=True)
                _adv_result = _enrich_cycle_selected(_adv_cycle, config=_adv_cfg)
                run.add(
                    "advisory_diagnostic",
                    "computed",
                    "MissionBrain Advisory diagnostic computed (monitoring-only, not surfaced)",
                    combined_status=_adv_result.get(
                        "bridge_diagnostics", {}
                    ).get("combined_status", "unknown"),
                    template_used=_adv_result.get("_advisory_template_used", "none"),
                    advisory_surfaced=False,
                )
            except Exception:  # noqa: BLE001
                pass  # advisory monitoring must never block or alter run outcome
        return run

    def _persist_blocked_outcome(
        self,
        run: "SupervisorRun",
        assignment_decision: Any,
    ) -> None:
        _persist_assignment_outcome_helper(run, self.project_root, assignment_decision)

    @staticmethod
    def _persist_assignment_outcome(
        run: "SupervisorRun",
        project_root: Any,
        assignment_decision: Any,
    ) -> None:
        """Append assignment outcome record for historical learning. No-op if unavailable."""
        _persist_assignment_outcome_helper(run, project_root, assignment_decision)

    def _pr_body(self, run: SupervisorRun) -> str:
        return _pr_body_helper(run)


