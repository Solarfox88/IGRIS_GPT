"""Lifecycle helpers for SelfRepairSupervisor (behavior-preserving extraction)."""

from __future__ import annotations

import logging
from typing import Any

from igris.core.supervisor_run_store import (
    RunTransitionValidator,
    SupervisorRunStore,
    SupervisorRunStoreError,
)

TERMINAL_RUN_STATUSES = {"completed", "blocked", "failed", "crashed", "cancelled", "interrupted"}


def is_terminal_status(status: Any) -> bool:
    return str(status or "").strip().lower() in TERMINAL_RUN_STATUSES


def configure_run_tracking(
    *,
    run: Any,
    config: Any,
    run_store: SupervisorRunStore,
    audit_resolver: Any,
    update_hook: Any,
) -> None:
    """Wire run store + tracking callbacks without changing runtime semantics."""
    if run_store.get(run.run_id) is None:
        run_store.register(run)
    run.audit_resolver = audit_resolver
    run.update_hook = update_hook
    run.max_repair_cycles = config.max_repair_cycles
    run.max_api_escalations_per_run = config.max_api_escalations_per_run
    run.max_api_budget_usd = round(config.max_api_budget_usd, 6)
    run.goal = config.goal


def transition_run_status(
    *,
    run: Any,
    new_status: str,
    reason: str,
    run_store: SupervisorRunStore,
    logger: logging.Logger | None = None,
) -> None:
    """Transition status through store, preserving degraded fallback behavior."""
    _log = logger or logging.getLogger("igris.supervisor.run_store")
    current = str(getattr(run, "status", "") or "")
    try:
        run_store.transition(run, new_status, reason=reason)
        return
    except SupervisorRunStoreError as exc:
        _log.warning(
            "Run store rejected transition run_id=%s %s -> %s (%s): %s",
            getattr(run, "run_id", ""),
            current,
            new_status,
            reason,
            exc,
        )
    except Exception as exc:
        _log.warning(
            "Run store transition degraded run_id=%s %s -> %s (%s): %s",
            getattr(run, "run_id", ""),
            current,
            new_status,
            reason,
            exc,
        )

    allowed, _ = RunTransitionValidator.validate(current, new_status)
    if allowed:
        run.status = new_status
    else:
        _log.warning(
            "Fallback transition blocked run_id=%s %s -> %s (%s)",
            getattr(run, "run_id", ""),
            current,
            new_status,
            reason,
        )
