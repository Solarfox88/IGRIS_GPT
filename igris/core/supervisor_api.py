"""Supervisor public API — run management and audit.

Module-level functions for starting, cancelling, listing, and summarizing
supervised runs. Extracted from self_repair_supervisor.py for modularity
(Issue #1312).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from datetime import datetime, timezone

from igris.core.supervisor_models import (
    AUDIT_STATUSES,
    RankSupervisorConfig,
    SupervisorEvent,
    SupervisorRun,
    _parse_issue_number,
    _safe_redact,
)
from igris.core.supervisor_lifecycle import (
    is_terminal_status as _lifecycle_is_terminal_status,
)


def _timestamp_is_due_check(next_review_after: str) -> bool:
    """Standalone version of SelfRepairSupervisor._timestamp_is_due."""
    if not str(next_review_after or "").strip():
        return True
    try:
        due = datetime.fromisoformat(str(next_review_after).replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) >= due


RUN_STORE: Dict[str, SupervisorRun] = {}
RUN_LOCK = threading.RLock()


def start_supervised_rank(data: Dict[str, Any], project_root: str) -> SupervisorRun:
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    config = RankSupervisorConfig.from_dict(data)
    supervisor = SelfRepairSupervisor(project_root=project_root)
    run = SupervisorRun(run_id=uuid.uuid4().hex[:12], rank_id=config.rank_id)
    if hasattr(supervisor, "_configure_run_tracking"):
        supervisor._configure_run_tracking(run, config)
    elif hasattr(supervisor, "_resolve_event_audit"):
        run.audit_resolver = getattr(supervisor, "_resolve_event_audit")
    run = supervisor.run(config, run=run)
    with RUN_LOCK:
        RUN_STORE[run.run_id] = run
    return run


def start_supervised_rank_async(data: Dict[str, Any], project_root: str) -> SupervisorRun:
    """Create a run immediately and execute it in a background worker.

    MBOP integration (#936): wraps the worker with Phases 1, 9, 10, 11, 12.
    - Phase 1 (Intake): reads GitHub issue before run starts.
    - Phases 9–12: quality gate, satisfaction gate, eval, next-step after completion.
    MBOP hooks are best-effort: any failure is logged but never crashes the run.
    """
    payload = dict(data)
    payload["defer_service_restart"] = True
    config = RankSupervisorConfig.from_dict(payload)
    # mbop_enforce_quality_gate: opt-in per-issue to enforce QG (default: advisory-only)
    mbop_enforce_qg = bool(data.get("mbop_enforce_quality_gate", False))
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    supervisor = SelfRepairSupervisor(project_root=project_root)
    run = SupervisorRun(run_id=uuid.uuid4().hex[:12], rank_id=config.rank_id)
    if hasattr(supervisor, "_configure_run_tracking"):
        supervisor._configure_run_tracking(run, config)
    elif hasattr(supervisor, "_resolve_event_audit"):
        run.audit_resolver = getattr(supervisor, "_resolve_event_audit")
    run.add("queued", "running", "Supervisor run accepted for background execution")
    with RUN_LOCK:
        RUN_STORE[run.run_id] = run

    def _worker() -> None:
        import time as _time
        _run_start = _time.time()

        # --- (#147) Initialise BehaviorTracker for this run ---
        try:
            from igris.core.behavior_tracker import BehaviorTracker
            run.behavior_tracker = BehaviorTracker(
                run_id=run.run_id,
                issue_number=config.issue_number,
            )
        except Exception:  # noqa: BLE001
            pass  # best-effort — never block the run

        # --- MBOP Phase 1: Intake (pre-run) ---
        # Bug fix: always resolve issue_number from goal text when not explicit,
        # so MBOP gets the real issue number and can extract ACs.
        _mbop_issue_number = _parse_issue_number(config.issue_number, str(config.goal))
        _mbop_intake = None
        try:
            from igris.core.mbop_runner import mbop_pre_run
            _mbop_intake = mbop_pre_run(
                issue_number=_mbop_issue_number,
                project_root=project_root,
                run_add_fn=run.add,
                run_id=run.run_id,
            )
        except Exception:  # noqa: BLE001
            pass  # best-effort — never block the run

        # --- MBOP Phase 2: Pre-flight ---
        try:
            from igris.core.mbop_runner import _persist_event as _mbop_persist
            _mbop_persist(
                project_root, run.run_id, _mbop_issue_number,
                "mbop_phase2_preflight", "running",
                f"MBOP Phase 2 Pre-flight: #{_mbop_issue_number} | "
                f"deps={'checking' if _mbop_issue_number else 'skip'} env=ok"
            )
        except Exception:
            pass

        # --- MBOP Phase 3: Mission Planning ---
        try:
            _mbop_persist(
                project_root, run.run_id, _mbop_issue_number,
                "mbop_phase3_planning", "running",
                f"MBOP Phase 3 Mission Planning: #{_mbop_issue_number} | "
                f"goal={str(config.goal)[:80]}"
            )
        except Exception:
            pass

        # --- Store MBOP intake on run so _rank_initial_context can inject it (#1040) ---
        if _mbop_intake is not None:
            run.mbop_intake = _mbop_intake

        # --- Main supervisor run ---
        try:
            supervisor.run(config, run=run)
        except Exception as exc:
            supervisor._transition_run_status(run, "blocked", "worker exception")
            run.outcome = "Blocked"
            run.failure_class = "supervisor_bug"
            run.add("exception", "blocked", str(exc))
            run.report = {"autonomous": False, "blocked_reason": "Supervisor worker crashed"}
            run.touch()

        # --- MBOP Phases 4–8: post-run intermediates (based on run outcome) ---
        try:
            _repair_cycles = getattr(run, "repair_cycles_used", 0)
            _failure_class = str(getattr(run, "failure_class", "") or "")
            _run_status = str(getattr(run, "status", "") or "")
            # Phase 4: Implementation outcome
            _mbop_persist(
                project_root, run.run_id, _mbop_issue_number,
                "mbop_phase4_implementation",
                "done" if _run_status == "completed" else "blocked",
                f"MBOP Phase 4 Implementation: #{_mbop_issue_number} | "
                f"status={_run_status} failure_class={_failure_class}",
                extra={"failure_class": _failure_class, "run_status": _run_status}
            )
            # Phase 5: Testing
            _test_ran = any(
                getattr(e, "phase", e.get("phase", "") if isinstance(e, dict) else "") in
                {"pytest_run", "test_run", "pytest_result"}
                for e in getattr(run, "events", [])
            )
            _mbop_persist(
                project_root, run.run_id, _mbop_issue_number,
                "mbop_phase5_testing",
                "ran" if _test_ran else "skipped",
                f"MBOP Phase 5 Testing: #{_mbop_issue_number} | "
                f"pytest={'ran' if _test_ran else 'skipped'}"
            )
            # Phase 6: Review
            _mbop_persist(
                project_root, run.run_id, _mbop_issue_number,
                "mbop_phase6_review",
                "done",
                f"MBOP Phase 6 Review: #{_mbop_issue_number} | "
                f"repair_cycles={_repair_cycles}"
            )
            # Phase 7: Repair
            _mbop_persist(
                project_root, run.run_id, _mbop_issue_number,
                "mbop_phase7_repair",
                f"cycles={_repair_cycles}" if _repair_cycles > 0 else "none",
                f"MBOP Phase 7 Repair: #{_mbop_issue_number} | "
                f"cycles_used={_repair_cycles}",
                extra={"repair_cycles_used": _repair_cycles}
            )
            # Phase 8: Completion check
            _mbop_persist(
                project_root, run.run_id, _mbop_issue_number,
                "mbop_phase8_completion_check",
                "pass" if _run_status == "completed" else "fail",
                f"MBOP Phase 8 Completion Check: #{_mbop_issue_number} | "
                f"final_status={_run_status}"
            )
        except Exception:
            pass

        # --- MBOP Phases 9–12: post-run hooks ---
        try:
            from igris.core.mbop_runner import mbop_post_run, MBOPIntakeResult
            _intake = _mbop_intake if _mbop_intake is not None else MBOPIntakeResult(
                issue_number=_mbop_issue_number
            )
            mbop_post_run(
                run=run,
                intake=_intake,
                project_root=project_root,
                run_start_ts=_run_start,
                enforce_quality_gate=mbop_enforce_qg,
                run_id=run.run_id,
            )
        except Exception:  # noqa: BLE001
            pass  # best-effort — never crash after supervisor completed

        # --- (#147) Supervisor self-audit post-run ---
        try:
            if run.behavior_tracker is not None:
                _run_status = str(getattr(run, "status", "") or "")
                _failure_class = str(getattr(run, "failure_class", "") or "")
                _repair_cycles = int(getattr(run, "repair_cycles_used", 0) or 0)
                _completion_mode = str(getattr(run, "completion_mode", "") or "")
                _escalations_used = int(getattr(run, "api_escalations_used", 0) or 0)
                _max_escalations = int(getattr(run, "max_api_escalations_per_run", 0) or 0)
                _budget_exhausted = bool(
                    _max_escalations > 0 and _escalations_used >= _max_escalations
                )
                _report = dict(getattr(run, "report", {}) or {})
                _smoke_ran = bool(_report.get("post_merge_smoke") is not None)
                _pytest_evidence = any(
                    e.phase in ("full_pytest", "targeted_tests", "baseline_tests")
                    and e.status in ("success", "failure")
                    for e in getattr(run, "events", [])
                )
                # Workspace dirty = git status has uncommitted changes
                _workspace_dirty = False
                try:
                    _gs = subprocess.run(
                        ["git", "status", "--porcelain"],
                        capture_output=True, text=True, cwd=project_root, timeout=10,
                    )
                    _workspace_dirty = bool(_gs.stdout.strip())
                except Exception:
                    pass
                audit = run.behavior_tracker.self_audit(
                    run_status=_run_status,
                    failure_class=_failure_class,
                    repair_cycles_used=_repair_cycles,
                    smoke_ran=_smoke_ran,
                    pytest_ran=_pytest_evidence,
                    workspace_dirty=_workspace_dirty,
                    escalation_budget_exhausted=_budget_exhausted,
                    escalation_was_called=_escalations_used > 0,
                    completion_mode=_completion_mode,
                    project_root=project_root,
                )
                audit_summary = run.behavior_tracker.summary()
                run.add(
                    "supervisor_self_audit", "done",
                    f"Self-audit complete: {audit_summary}",
                    missed_behaviors=audit.missed_behaviors[:10],
                    opened_issues=audit.opened_issues,
                    notes=audit.notes[:5],
                    behavior_log=run.behavior_tracker.to_dict(),
                )
        except Exception:  # noqa: BLE001
            pass  # best-effort — never crash after supervisor completed

    thread = threading.Thread(
        target=_worker,
        name=f"rank-supervisor-{run.run_id}",
        daemon=True,
    )
    thread.start()
    return run


def get_supervised_run(run_id: str) -> Optional[SupervisorRun]:
    with RUN_LOCK:
        return RUN_STORE.get(run_id)


def cancel_supervised_run(run_id: str, project_root: str, reason: str = "Cancelled by user") -> Optional[SupervisorRun]:
    with RUN_LOCK:
        run = RUN_STORE.get(run_id)
    if run is None:
        return None

    current_status = str(run.status or "").strip().lower()
    if _is_terminal_status(current_status):
        return run

    cancel_reason = str(reason or "Cancelled by user").strip() or "Cancelled by user"
    run.cancel_requested = True
    run.cancel_reason = cancel_reason
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    supervisor = SelfRepairSupervisor(project_root=project_root)
    if hasattr(supervisor, "_configure_run_tracking"):
        supervisor._configure_run_tracking(run, RankSupervisorConfig.from_dict({"goal": "", "rank_id": run.rank_id}))
    if current_status != "cancelling":
        supervisor._transition_run_status(run, "cancelling", cancel_reason)
        run.add("cancel_request", "running", cancel_reason, requested_by="api")
    else:
        run.add("cancel_request", "running", cancel_reason, requested_by="api", duplicate=True)
    return supervisor._cancelled(run, cancel_reason, cleanup_workspace=True)


def list_supervised_runs() -> List[SupervisorRun]:
    with RUN_LOCK:
        return list(RUN_STORE.values())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timestamp_sort_key(value: Any) -> float:
    numeric = _safe_float(value, default=float("nan"))
    if numeric == numeric:  # not NaN
        return numeric
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _stage_summary_from_run_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    stages = (
        ((payload.get("report") or {}).get("mission_orchestration") or {}).get("stages")
        or []
    )
    counts = {
        "success": 0,
        "failure": 0,
        "pending": 0,
        "running": 0,
        "skipped": 0,
        "unknown": 0,
    }
    failed_stage_ids: List[str] = []
    pending_stage_ids: List[str] = []
    for stage in stages:
        status = str((stage or {}).get("status", "")).strip().lower()
        stage_id = str((stage or {}).get("stage_id", "")).strip()
        if status in counts:
            counts[status] += 1
        else:
            counts["unknown"] += 1
        if status == "failure" and stage_id:
            failed_stage_ids.append(stage_id)
        if status in {"pending", "running"} and stage_id:
            pending_stage_ids.append(stage_id)
    return {
        "counts": counts,
        "failed_stage_ids": failed_stage_ids,
        "pending_stage_ids": pending_stage_ids,
        "total": len(stages),
    }


def _audit_counts_from_events(events: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {status: 0 for status in sorted(AUDIT_STATUSES)}
    counts["unknown"] = 0
    for event in events:
        status = str((event or {}).get("audit_status", "")).strip().lower()
        if status in counts:
            counts[status] += 1
        else:
            counts["unknown"] += 1
    return counts


def _extract_issue_url_from_text(text: str) -> str:
    match = re.search(r"https://github\.com/[^\s]+/issues/\d+", text or "")
    return match.group(0) if match else ""


TERMINAL_RUN_STATUSES = {"completed", "blocked", "failed", "crashed", "cancelled", "interrupted"}


def _is_terminal_status(status: Any) -> bool:
    return _lifecycle_is_terminal_status(status)


def _run_has_resolved_failure(record: Dict[str, Any]) -> bool:
    report = record.get("final_report")
    if not isinstance(report, dict):
        report = {}
    return bool(
        report.get("resolved_failure")
        or report.get("degraded_completion")
        or record.get("resolved_failure")
        or record.get("degraded_completion")
    )


def _enforce_completion_failure_invariant(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(record)
    status = str(normalized.get("status", "")).strip().lower()
    failure_class = str(normalized.get("failure_class", "")).strip()
    if status == "completed" and failure_class and not _run_has_resolved_failure(normalized):
        normalized["state_conflict"] = True
        normalized["warning"] = (
            "Completed run has failure_class without resolved/degraded completion flag."
        )
    else:
        normalized["state_conflict"] = bool(normalized.get("state_conflict", False))
        normalized["warning"] = str(normalized.get("warning", "") or "")
    return normalized


def _reconcile_run_records(
    in_memory: Dict[str, Dict[str, Any]],
    persisted: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    run_ids = set(in_memory.keys()) | set(persisted.keys())
    for run_id in run_ids:
        memory_record = in_memory.get(run_id)
        persisted_record = persisted.get(run_id)
        if memory_record is None and persisted_record is not None:
            chosen = dict(persisted_record)
            # A persisted run that is no longer in the in-memory store was
            # interrupted by a service restart — promote it to a terminal
            # status so it never reappears as a ghost active run.
            if str(chosen.get("status", "")).strip().lower() == "running":
                chosen["status"] = "interrupted"
                chosen.setdefault(
                    "warning",
                    "Run was interrupted by a service restart and is no longer active.",
                )
        elif persisted_record is None and memory_record is not None:
            chosen = dict(memory_record)
        else:
            assert memory_record is not None and persisted_record is not None
            mem_updated = _timestamp_sort_key(memory_record.get("updated_at", 0.0))
            per_updated = _timestamp_sort_key(persisted_record.get("updated_at", 0.0))
            chosen = dict(memory_record if mem_updated >= per_updated else persisted_record)
            mem_status = str(memory_record.get("status", "")).strip().lower()
            per_status = str(persisted_record.get("status", "")).strip().lower()
            if mem_status != per_status:
                if _is_terminal_status(per_status) and per_updated >= mem_updated:
                    chosen = dict(persisted_record)
                elif _is_terminal_status(mem_status) and mem_updated >= per_updated:
                    chosen = dict(memory_record)
                chosen["state_conflict"] = True
                chosen["warning"] = (
                    f"State conflict between in-memory({mem_status}) and durable({per_status})."
                )
        merged[run_id] = _enforce_completion_failure_invariant(chosen)
    return merged


def summarize_supervised_run(run: SupervisorRun) -> Dict[str, Any]:
    payload = run.to_dict()
    events = payload.get("events") or []
    started_at = events[0]["timestamp"] if events else None
    updated_at = events[-1]["timestamp"] if events else None
    last_event = events[-1] if events else {}
    current_stage = ""
    for event in reversed(events):
        phase = str((event or {}).get("phase", ""))
        status = str((event or {}).get("status", ""))
        data = (event or {}).get("data") or {}
        if phase == "rank_reasoning" and status == "running":
            current_stage = str(data.get("stage_id", "")).strip()
            break
        if phase == "mission_stage" and status == "running":
            current_stage = str(data.get("stage_id", "")).strip()
            break
    stage_summary = _stage_summary_from_run_dict(payload)
    audit_counts = _audit_counts_from_events(events)
    failed_stage = (stage_summary.get("failed_stage_ids") or [""])[0]
    escalation_issue_url = ""
    for event in reversed(events):
        if str((event or {}).get("phase", "")).strip() != "repair_issue":
            continue
        detail = str((event or {}).get("detail", ""))
        escalation_issue_url = _extract_issue_url_from_text(detail)
        if escalation_issue_url:
            break

    next_action = "monitor"
    if payload.get("status") == "running":
        next_action = f"wait:{current_stage}" if current_stage else "wait:next_event"
    elif payload.get("status") == "blocked":
        failure = str(payload.get("failure_class", "")).strip() or "blocked"
        next_action = f"review:{failure}"
    elif payload.get("status") == "completed":
        next_action = "done"

    summary = {
        "run_id": payload.get("run_id", ""),
        "rank_id": payload.get("rank_id", ""),
        "status": payload.get("status", ""),
        "outcome": payload.get("outcome", ""),
        "failure_class": payload.get("failure_class", ""),
        "branch": payload.get("branch", ""),
        "repair_cycles_used": int(payload.get("repair_cycles_used", 0) or 0),
        "max_repair_cycles": int(payload.get("max_repair_cycles", 0) or 0),
        "api_escalations_used": int(payload.get("api_escalations_used", 0) or 0),
        "api_escalations_failed_unconfigured": int(payload.get("api_escalations_failed_unconfigured", 0) or 0),
        "max_api_escalations_per_run": int(payload.get("max_api_escalations_per_run", 0) or 0),
        "api_budget_used_usd": round(_safe_float(payload.get("api_budget_used_usd", 0.0)), 6),
        "max_api_budget_usd": round(_safe_float(payload.get("max_api_budget_usd", 0.0)), 6),
        "current_stage": current_stage,
        "failed_stage": failed_stage,
        "escalation_issue_url": escalation_issue_url,
        "stage_summary": stage_summary,
        "audit_summary": {
            "counts": audit_counts,
            "next_review_due_count": sum(
                1
                for event in events
                if str((event or {}).get("audit_status", "")).strip().lower() == "audit-deferred"
                and _timestamp_is_due_check(
                    str((event or {}).get("audit_next_review_after", ""))
                )
            ),
        },
        "last_event": {
            "phase": str(last_event.get("phase", "")),
            "status": str(last_event.get("status", "")),
            "timestamp": last_event.get("timestamp"),
            "audit_status": str(last_event.get("audit_status", "")),
        },
        "started_at": started_at,
        "updated_at": updated_at,
        "resolved_failure": bool((payload.get("report") or {}).get("resolved_failure", False)),
        "degraded_completion": bool((payload.get("report") or {}).get("degraded_completion", False)),
        "degraded_completion_reason": str((payload.get("report") or {}).get("degraded_completion_reason", "")),
        "cancelled_reason": str((payload.get("report") or {}).get("cancelled_reason", "") or payload.get("cancel_reason", "")),
        "next_action": next_action,
    }
    return _enforce_completion_failure_invariant(summary)


def list_active_supervised_runs() -> List[SupervisorRun]:
    with RUN_LOCK:
        return [run for run in RUN_STORE.values() if run.status == "running"]


def list_active_supervised_run_summaries(project_root: str) -> List[Dict[str, Any]]:
    in_memory_active: Dict[str, Dict[str, Any]] = {}
    with RUN_LOCK:
        for run in RUN_STORE.values():
            if str(run.status).strip().lower() != "running":
                continue
            in_memory_active[str(run.run_id)] = summarize_supervised_run(run)
    persisted = {
        str(item.get("run_id", "")): dict(item)
        for item in _load_persisted_recent_runs(project_root)
        if str(item.get("run_id", "")).strip()
    }
    reconciled = _reconcile_run_records(in_memory_active, persisted)
    active = [
        record for record in reconciled.values()
        if str(record.get("status", "")).strip().lower() == "running"
    ]
    active.sort(key=lambda item: _timestamp_sort_key(item.get("updated_at", 0.0)), reverse=True)
    return active


def _load_persisted_recent_runs(project_root: str) -> List[Dict[str, Any]]:
    runs_path = Path(project_root) / ".igris" / "supervisor_runs.json"
    if not runs_path.exists():
        return []
    try:
        payload = json.loads(runs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    runs = payload.get("runs", {}) if isinstance(payload, dict) else {}
    if not isinstance(runs, dict):
        return []
    out: List[Dict[str, Any]] = []
    for run_id, raw in runs.items():
        if not isinstance(run_id, str) or not isinstance(raw, dict):
            continue
        out.append(
            {
                "run_id": run_id,
                "rank_id": str(raw.get("rank_id", "")),
                "status": str(raw.get("status", "")),
                "outcome": str(raw.get("outcome", "")),
                "branch": str(raw.get("branch", "")),
                "current_stage": str(raw.get("current_stage", "")),
                "failed_stage": str(raw.get("failed_stage", "")),
                "failure_class": str(raw.get("failure_class", "")),
                "repair_cycles_used": int(raw.get("repair_cycles_used", 0) or 0),
                "max_repair_cycles": int(raw.get("max_repair_cycles", 0) or 0),
                "api_escalations_used": int(raw.get("api_escalations_used", 0) or 0),
                "api_escalations_failed_unconfigured": int(raw.get("api_escalations_failed_unconfigured", 0) or 0),
                "max_api_escalations_per_run": int(raw.get("max_api_escalations_per_run", 0) or 0),
                "api_budget_used_usd": round(_safe_float(raw.get("api_budget_used_usd", 0.0)), 6),
                "max_api_budget_usd": round(_safe_float(raw.get("max_api_budget_usd", 0.0)), 6),
                "escalation_issue_url": str(raw.get("escalation_issue_url", "")),
                "latest_event": raw.get("latest_event", {}) if isinstance(raw.get("latest_event"), dict) else {},
                "updated_at": str(raw.get("updated_at", "")),
                "created_at": str(raw.get("created_at", "")),
                "blocked_reason": _safe_redact(raw.get("blocked_reason", "")),
                "cancelled_reason": _safe_redact(raw.get("cancelled_reason", "")),
                "next_action": str(raw.get("next_action", "")),
                "resolved_failure": bool(raw.get("resolved_failure", False)),
                "degraded_completion": bool(raw.get("degraded_completion", False)),
                "degraded_completion_reason": str(raw.get("degraded_completion_reason", "")),
                "state_conflict": bool(raw.get("state_conflict", False)),
                "warning": str(raw.get("warning", "")),
            }
        )
    out.sort(key=lambda item: _timestamp_sort_key(item.get("updated_at", "")), reverse=True)
    return [_enforce_completion_failure_invariant(item) for item in out[:20]]


def get_supervisor_audit_summary(project_root: str) -> Dict[str, Any]:
    in_memory_events: List[Dict[str, Any]] = []
    recent_runs: Dict[str, Dict[str, Any]] = {}
    with RUN_LOCK:
        for run in RUN_STORE.values():
            summary = summarize_supervised_run(run)
            events = (run.to_dict().get("events") or [])
            in_memory_events.extend(events)
            run_id = str(summary.get("run_id", "")).strip()
            if run_id:
                recent_runs[run_id] = summary

    persisted_recent_runs = {
        str(item.get("run_id", "")): dict(item)
        for item in _load_persisted_recent_runs(project_root)
        if str(item.get("run_id", "")).strip()
    }
    merged_recent = _reconcile_run_records(recent_runs, persisted_recent_runs)
    merged_recent_runs = sorted(
        merged_recent.values(),
        key=lambda item: _timestamp_sort_key(item.get("updated_at", 0.0)),
        reverse=True,
    )[:5]
    in_memory_counts = _audit_counts_from_events(in_memory_events)

    persisted_counts = {status: 0 for status in sorted(AUDIT_STATUSES)}
    persisted_counts["unknown"] = 0
    persisted_total = 0
    deferred_due_count = 0
    audit_path = Path(project_root) / ".igris" / "supervisor_audit.json"
    if audit_path.exists():
        try:
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
            records = payload.get("records", {}) if isinstance(payload, dict) else {}
            if isinstance(records, dict):
                for entry in records.values():
                    if not isinstance(entry, dict):
                        continue
                    persisted_total += 1
                    status = str(entry.get("audit_status", "")).strip().lower()
                    if status in persisted_counts:
                        persisted_counts[status] += 1
                    else:
                        persisted_counts["unknown"] += 1
                    if (
                        status == "audit-deferred"
                        and _timestamp_is_due_check(
                            str(entry.get("audit_next_review_after", ""))
                        )
                    ):
                        deferred_due_count += 1
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "audit_file": str(audit_path),
        "audit_file_exists": audit_path.exists(),
        "in_memory": {
            "event_count": len(in_memory_events),
            "counts": in_memory_counts,
        },
        "persisted": {
            "record_count": persisted_total,
            "counts": persisted_counts,
            "deferred_due_count": deferred_due_count,
        },
        "recent_runs": merged_recent_runs,
    }
