"""Audit/persistence helpers extracted from SelfRepairSupervisor.

These methods were originally instance methods on ``SelfRepairSupervisor``
that dealt with loading/persisting the audit index, runs index, run
snapshots, and resolving per-event audit metadata.  They have been
extracted to this module to reduce the size of the monolith.  The
original class retains thin delegation wrappers for backward
compatibility.

The functions accept the originating supervisor instance as their first
parameter (``supervisor``) so they can access the same instance
attributes (``_audit_path``, ``_runs_path``, ``_runs_index``,
``_audit_index``, ``_runs_lock``, etc.) without changing runtime
semantics.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from igris.core.supervisor_models import (
    AUDIT_STATUSES,
    SupervisorRun,
    _safe_redact,
)
import logging



_log = logging.getLogger(__name__)

def load_audit_index(supervisor: Any) -> Dict[str, Dict[str, Any]]:
    try:
        if not supervisor._audit_path.exists():
            return {}
        payload = json.loads(supervisor._audit_path.read_text(encoding="utf-8"))
        records = payload.get("records", {}) if isinstance(payload, dict) else {}
        if not isinstance(records, dict):
            return {}
        return {str(k): dict(v) for k, v in records.items() if isinstance(k, str) and isinstance(v, dict)}
    except (OSError, json.JSONDecodeError):
        return {}


def persist_audit_index(supervisor: Any) -> None:
    try:
        supervisor._audit_path.parent.mkdir(parents=True, exist_ok=True)
        supervisor._audit_path.write_text(json.dumps({"records": supervisor._audit_index}, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def load_runs_index(supervisor: Any) -> Dict[str, Dict[str, Any]]:
    try:
        if not supervisor._runs_path.exists():
            return {}
        payload = json.loads(supervisor._runs_path.read_text(encoding="utf-8"))
        runs = payload.get("runs", {}) if isinstance(payload, dict) else {}
        if not isinstance(runs, dict):
            return {}
        return {
            str(k): dict(v)
            for k, v in runs.items()
            if isinstance(k, str) and isinstance(v, dict)
        }
    except (OSError, json.JSONDecodeError):
        return {}


def persist_runs_index(supervisor: Any) -> None:
    try:
        supervisor._runs_path.parent.mkdir(parents=True, exist_ok=True)
        # Issue #729 — rotate supervisor_runs.json if it exceeds size cap
        try:
            from igris.core.file_rotation import rotate_if_needed
            rotate_if_needed(supervisor._runs_path)
        except (ImportError, OSError, ValueError, TypeError) as exc:
            _log.debug("supervisor_audit: narrowed catch failed: %s", exc, exc_info=True)
        payload = {"runs": supervisor._runs_index}
        supervisor._runs_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def persist_run_snapshot(supervisor: Any, run: SupervisorRun) -> None:
    record = supervisor._persisted_run_record(run)
    with supervisor._runs_lock:
        supervisor._runs_index[str(run.run_id)] = record
        supervisor._persist_runs_index()


def resolve_event_audit(supervisor: Any, event: Any) -> None:
    scope_hash = supervisor._event_scope_hash(event)
    event.audit_scope_hash = scope_hash
    entry = supervisor._audit_index.get(scope_hash, {})
    prior = str(entry.get("audit_status", "")).strip()
    if prior in {"audit-reviewed", "audit-fixed", "audit-false-positive"}:
        event.audit_status = prior
    elif prior == "audit-deferred" and not supervisor._timestamp_is_due(str(entry.get("audit_next_review_after", ""))):
        event.audit_status = "audit-deferred"
    else:
        event.audit_status = "audit-new"
    event.audit_reviewed_by = str(entry.get("audit_reviewed_by", ""))
    event.audit_reviewed_at = str(entry.get("audit_reviewed_at", ""))
    event.audit_review_id = str(entry.get("audit_review_id", "")) or scope_hash[:12]
    event.audit_next_review_after = str(entry.get("audit_next_review_after", ""))
    event.audit_resolution_pr = str(entry.get("audit_resolution_pr", ""))
    event.audit_notes = str(entry.get("audit_notes", ""))


def record_audit_checkpoint(
    supervisor: Any,
    scope_hash: str,
    *,
    audit_status: str,
    reviewed_by: str = "supervisor",
    review_id: str = "",
    next_review_after: str = "",
    resolution_pr: str = "",
    notes: str = "",
) -> None:
    if audit_status not in AUDIT_STATUSES:
        raise ValueError(f"Unsupported audit status: {audit_status}")
    normalized_hash = str(scope_hash or "").strip()
    if not normalized_hash:
        raise ValueError("scope_hash is required")
    supervisor._audit_index[normalized_hash] = {
        "audit_status": audit_status,
        "audit_reviewed_by": str(reviewed_by or ""),
        "audit_reviewed_at": supervisor._timestamp_now_iso(),
        "audit_review_id": str(review_id or normalized_hash[:12]),
        "audit_scope_hash": normalized_hash,
        "audit_next_review_after": str(next_review_after or ""),
        "audit_resolution_pr": str(resolution_pr or ""),
        "audit_notes": _safe_redact(notes or ""),
    }
    supervisor._persist_audit_index()
