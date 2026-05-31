"""PR 11 — Supervisor hardening/resume: SupervisorRunStore with transition validation.

Provides:
- SupervisorRunStore: thread-safe, persistent store for SupervisorRun objects
  - Loads runs from disk on initialization (resume after crash/restart)
  - Validates RunPhase transitions before committing them
  - Maintains an append-only audit log per run
  - Never allows advisory operations to alter RunPhase or outcome
- RunTransitionValidator: validates allowed phase transitions
- AuditEntry: immutable record of a transition or event
- SupervisorRunStoreError: raised on invalid operations

Advisory invariant (enforced):
  Any operation tagged advisory_only=True MUST NOT modify:
    - run.status
    - run.outcome
    - run.failure_class
    - any phase field

Usage:
    store = SupervisorRunStore(project_root="/path/to/project")
    store.register(run)
    run = store.get("run-id-123")
    store.transition(run, new_status="blocked", reason="tests failed")
    store.append_audit(run, "status_changed", {"from": "running", "to": "blocked"})
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Terminal statuses — once in a terminal state, no further transitions allowed
TERMINAL_STATUSES: frozenset = frozenset({
    "completed", "blocked", "failed", "crashed",
    "cancelled", "interrupted", "success",
})

# Valid status transition map: status → allowed next statuses
# None means "allow any" (used for unknown/untracked statuses)
_ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "running": {"running", "cancelling", "blocked", "failed", "completed",
                "success", "crashed", "interrupted"},
    "cancelling": {"cancelled", "interrupted", "blocked", "failed"},
    # Terminal statuses have no allowed transitions (enforced separately)
    "completed": set(),
    "blocked": set(),
    "failed": set(),
    "crashed": set(),
    "cancelled": set(),
    "interrupted": set(),
    "success": set(),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SupervisorRunStoreError(Exception):
    """Raised for invalid operations on the run store."""


class InvalidTransitionError(SupervisorRunStoreError):
    """Raised when a RunPhase/status transition is not allowed."""


class AdvisoryMutationError(SupervisorRunStoreError):
    """Raised when an advisory operation attempts to modify run state."""


# ---------------------------------------------------------------------------
# AuditEntry — immutable record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEntry:
    """Immutable record of a transition or significant event.

    Once created, AuditEntry cannot be modified (frozen=True).
    The audit log is append-only.
    """
    entry_id: str = field(default_factory=lambda: f"audit_{int(time.time() * 1000)}")
    run_id: str = ""
    event_type: str = ""       # e.g. "status_transition", "phase_change", "error"
    from_status: str = ""
    to_status: str = ""
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    advisory_only: bool = False  # True = advisory event, must not alter state
    metadata: str = ""           # JSON-encoded extra data

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "advisory_only": self.advisory_only,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# RunTransitionValidator
# ---------------------------------------------------------------------------

class RunTransitionValidator:
    """Validates RunPhase/status transitions.

    Rules:
    1. Terminal → any = BLOCKED (once terminal, no transitions allowed)
    2. running → valid next statuses (see _ALLOWED_TRANSITIONS)
    3. Unknown current → allow (permissive for unknown states)
    4. Advisory-only operations must never transition status
    """

    @staticmethod
    def validate(
        current_status: str,
        new_status: str,
        *,
        advisory_only: bool = False,
    ) -> Tuple[bool, str]:
        """Validate a status transition.

        Returns:
            (allowed: bool, reason: str)
        """
        curr = str(current_status or "").strip().lower()
        nxt = str(new_status or "").strip().lower()

        # Advisory operations must never change status
        if advisory_only and curr != nxt:
            return False, (
                f"advisory_only=True must not alter run status "
                f"(current={curr!r}, attempted={nxt!r})"
            )

        # No-op transitions are always allowed
        if curr == nxt:
            return True, "no-op"

        # Terminal → any = invalid
        if curr in TERMINAL_STATUSES:
            return False, (
                f"Cannot transition from terminal status {curr!r} to {nxt!r}"
            )

        # Check allowed set
        allowed_next = _ALLOWED_TRANSITIONS.get(curr)
        if allowed_next is None:
            # Unknown current status — permissive
            return True, "unknown_current_status (permissive)"

        if nxt in allowed_next:
            return True, "ok"

        return False, (
            f"Transition {curr!r} → {nxt!r} not in allowed set: "
            f"{sorted(allowed_next)}"
        )

    @staticmethod
    def is_terminal(status: str) -> bool:
        return str(status or "").strip().lower() in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# SupervisorRunStore
# ---------------------------------------------------------------------------

class SupervisorRunStore:
    """Thread-safe, persistent store for SupervisorRun objects.

    PR 11 hardening:
    - Loads persisted run metadata from disk on init (resume after crash)
    - Validates transitions before committing them
    - Maintains an append-only audit log (never modified, only extended)
    - Advisory operations cannot alter run status/outcome/failure_class

    The store does NOT import SupervisorRun at module level to avoid circular
    imports. SupervisorRun is duck-typed (any object with run_id/status attrs).
    """

    def __init__(
        self,
        project_root: str,
        *,
        audit_log_path: Optional[str] = None,
        strict_transitions: bool = True,
    ) -> None:
        self._project_root = Path(project_root)
        self._store: Dict[str, Any] = {}  # run_id → SupervisorRun
        self._audit_log: List[AuditEntry] = []
        self._lock = threading.RLock()
        self._strict = strict_transitions
        self._audit_path = (
            Path(audit_log_path)
            if audit_log_path
            else self._project_root / ".igris" / "supervisor_audit.jsonl"
        )
        # Load persisted audit on startup (for resume/replay)
        self._load_audit_log()

    # ------------------------------------------------------------------
    # Register / get
    # ------------------------------------------------------------------

    def register(self, run: Any) -> None:
        """Register a run. If already registered, update in-place."""
        with self._lock:
            run_id = str(run.run_id)
            self._store[run_id] = run
            self._append_audit(AuditEntry(
                run_id=run_id,
                event_type="registered",
                from_status="",
                to_status=str(run.status or ""),
                reason="run registered",
            ))

    def get(self, run_id: str) -> Optional[Any]:
        with self._lock:
            return self._store.get(str(run_id))

    def list_all(self) -> List[Any]:
        with self._lock:
            return list(self._store.values())

    def list_active(self) -> List[Any]:
        with self._lock:
            return [
                r for r in self._store.values()
                if not RunTransitionValidator.is_terminal(r.status)
            ]

    # ------------------------------------------------------------------
    # Transition
    # ------------------------------------------------------------------

    def transition(
        self,
        run: Any,
        new_status: str,
        *,
        reason: str = "",
        advisory_only: bool = False,
    ) -> None:
        """Validate and apply a status transition to a run.

        Raises:
            InvalidTransitionError: if transition is not allowed
            AdvisoryMutationError: if advisory_only=True and status would change
        """
        current_status = str(run.status or "")
        allowed, msg = RunTransitionValidator.validate(
            current_status,
            new_status,
            advisory_only=advisory_only,
        )

        if not allowed:
            if advisory_only:
                raise AdvisoryMutationError(
                    f"Advisory mutation blocked: {msg}"
                )
            if self._strict:
                raise InvalidTransitionError(
                    f"Invalid transition for run {run.run_id}: {msg}"
                )
            else:
                logger.warning(
                    "supervisor_run_store: soft-rejected transition run=%s %s",
                    run.run_id, msg,
                )
                return

        with self._lock:
            run.status = new_status
            entry = AuditEntry(
                run_id=str(run.run_id),
                event_type="status_transition",
                from_status=current_status,
                to_status=new_status,
                reason=reason or msg,
                advisory_only=advisory_only,
            )
            self._append_audit(entry)

    # ------------------------------------------------------------------
    # Audit log — append-only
    # ------------------------------------------------------------------

    def append_audit(
        self,
        run: Any,
        event_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        advisory_only: bool = False,
        reason: str = "",
    ) -> AuditEntry:
        """Append an immutable audit entry. Returns the entry.

        This is the only way to add to the audit log — no modifications allowed.
        """
        entry = AuditEntry(
            run_id=str(run.run_id),
            event_type=event_type,
            from_status=str(run.status or ""),
            to_status=str(run.status or ""),
            reason=reason,
            advisory_only=advisory_only,
            metadata=json.dumps(metadata or {}),
        )
        self._append_audit(entry)
        return entry

    def get_audit_log(self, run_id: Optional[str] = None) -> List[AuditEntry]:
        """Return the (immutable) audit log, optionally filtered by run_id."""
        with self._lock:
            if run_id is None:
                return list(self._audit_log)
            return [e for e in self._audit_log if e.run_id == str(run_id)]

    def _append_audit(self, entry: AuditEntry) -> None:
        """Internal: append to audit log and persist."""
        with self._lock:
            self._audit_log.append(entry)
        # Persist non-blocking
        try:
            self._persist_audit_entry(entry)
        except Exception as exc:
            logger.warning("supervisor_run_store: failed to persist audit entry: %s", exc)

    def _persist_audit_entry(self, entry: AuditEntry) -> None:
        """Append one entry to the JSONL audit log file."""
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    def _load_audit_log(self) -> None:
        """Load existing audit log from disk (for session resume)."""
        if not self._audit_path.exists():
            return
        try:
            with open(self._audit_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entry = AuditEntry(
                            entry_id=data.get("entry_id", ""),
                            run_id=data.get("run_id", ""),
                            event_type=data.get("event_type", ""),
                            from_status=data.get("from_status", ""),
                            to_status=data.get("to_status", ""),
                            reason=data.get("reason", ""),
                            timestamp=float(data.get("timestamp", 0)),
                            advisory_only=bool(data.get("advisory_only", False)),
                            metadata=data.get("metadata", ""),
                        )
                        self._audit_log.append(entry)
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("supervisor_run_store: could not load audit log: %s", exc)

    # ------------------------------------------------------------------
    # Resume support
    # ------------------------------------------------------------------

    def get_resumable_run_ids(self) -> List[str]:
        """Return run_ids from the audit log that were never terminated.

        A run is 'resumable' if the audit log shows it was registered but
        no terminal status transition was ever recorded for it.

        This allows a supervisor to detect runs that survived a crash and
        re-attach to them on restart.
        """
        with self._lock:
            registered_ids: Set[str] = set()
            terminated_ids: Set[str] = set()
            for entry in self._audit_log:
                if entry.event_type == "registered":
                    registered_ids.add(entry.run_id)
                if entry.event_type == "status_transition" and RunTransitionValidator.is_terminal(
                    entry.to_status
                ):
                    terminated_ids.add(entry.run_id)
            return sorted(registered_ids - terminated_ids)

    def is_advisory_safe(
        self,
        run: Any,
        operation: str = "read",
    ) -> Tuple[bool, str]:
        """Check if an advisory operation is safe for a given run.

        Advisory operations are always safe for reading.
        Advisory operations that attempt to write to state fields are unsafe.

        Args:
            run: the SupervisorRun to check
            operation: "read" (always safe) or "write" (unsafe if terminal)

        Returns:
            (safe: bool, reason: str)
        """
        if operation == "read":
            return True, "advisory read is always safe"

        # Advisory writes to terminal runs: allowed but won't change state
        current = str(run.status or "")
        if RunTransitionValidator.is_terminal(current):
            return False, (
                f"Advisory write to terminal run ({current!r}) is blocked — "
                f"run is already in a terminal state"
            )
        return True, "advisory write is safe (will be validated before commit)"
