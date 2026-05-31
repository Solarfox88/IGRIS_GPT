"""PR 11 — Supervisor hardening/resume tests.

Covers:
- RunTransitionValidator: valid/invalid transitions, terminal guard, advisory guard
- AuditEntry: immutable, frozen, append-only
- SupervisorRunStore:
  - register/get/list
  - transition with validation
  - transition raises InvalidTransitionError for blocked transitions
  - transition raises AdvisoryMutationError for advisory writes
  - audit log: append-only, persisted to JSONL, loaded on init (resume)
  - get_resumable_run_ids: survives crash detection
  - is_advisory_safe: read always safe, write blocked on terminal
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from igris.core.supervisor_run_store import (
    AuditEntry,
    AdvisoryMutationError,
    InvalidTransitionError,
    RunTransitionValidator,
    SupervisorRunStore,
    SupervisorRunStoreError,
    TERMINAL_STATUSES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeRun:
    """Minimal fake SupervisorRun for testing."""
    run_id: str
    status: str = "running"
    outcome: str = ""
    failure_class: str = ""


def _store(tmp_path: Path, strict: bool = True) -> SupervisorRunStore:
    return SupervisorRunStore(str(tmp_path), strict_transitions=strict)


# ---------------------------------------------------------------------------
# 1. RunTransitionValidator
# ---------------------------------------------------------------------------

class TestRunTransitionValidator:

    def test_running_to_blocked_allowed(self):
        allowed, msg = RunTransitionValidator.validate("running", "blocked")
        assert allowed is True

    def test_running_to_failed_allowed(self):
        allowed, _ = RunTransitionValidator.validate("running", "failed")
        assert allowed is True

    def test_running_to_completed_allowed(self):
        allowed, _ = RunTransitionValidator.validate("running", "completed")
        assert allowed is True

    def test_running_to_cancelling_allowed(self):
        allowed, _ = RunTransitionValidator.validate("running", "cancelling")
        assert allowed is True

    def test_terminal_to_any_blocked(self):
        for terminal in TERMINAL_STATUSES:
            if terminal == "running":
                continue
            allowed, msg = RunTransitionValidator.validate(terminal, "running")
            assert allowed is False, f"Should block {terminal} → running"
            assert "terminal" in msg.lower() or "cannot" in msg.lower()

    def test_noop_transition_always_allowed(self):
        for status in ("running", "blocked", "completed", "failed"):
            allowed, msg = RunTransitionValidator.validate(status, status)
            assert allowed is True, f"no-op {status} → {status} should be allowed"
            assert "no-op" in msg

    def test_advisory_only_blocks_status_change(self):
        allowed, msg = RunTransitionValidator.validate(
            "running", "blocked", advisory_only=True
        )
        assert allowed is False
        assert "advisory_only" in msg.lower() or "advisory" in msg.lower()

    def test_advisory_only_allows_noop(self):
        allowed, _ = RunTransitionValidator.validate(
            "running", "running", advisory_only=True
        )
        assert allowed is True

    def test_unknown_current_status_permissive(self):
        allowed, msg = RunTransitionValidator.validate("unknown_state", "running")
        assert allowed is True
        assert "permissive" in msg.lower()

    def test_is_terminal_true_for_all_terminal(self):
        for status in TERMINAL_STATUSES:
            assert RunTransitionValidator.is_terminal(status) is True

    def test_is_terminal_false_for_running(self):
        assert RunTransitionValidator.is_terminal("running") is False

    def test_is_terminal_case_insensitive(self):
        assert RunTransitionValidator.is_terminal("COMPLETED") is True
        assert RunTransitionValidator.is_terminal("Blocked") is True


# ---------------------------------------------------------------------------
# 2. AuditEntry — immutable
# ---------------------------------------------------------------------------

class TestAuditEntry:

    def test_audit_entry_is_frozen(self):
        entry = AuditEntry(run_id="r1", event_type="test")
        with pytest.raises((AttributeError, TypeError)):
            entry.run_id = "modified"  # type: ignore[misc]

    def test_audit_entry_to_dict_keys(self):
        entry = AuditEntry(run_id="r1", event_type="status_transition")
        d = entry.to_dict()
        for key in ("entry_id", "run_id", "event_type", "from_status",
                    "to_status", "reason", "timestamp", "advisory_only", "metadata"):
            assert key in d, f"missing key: {key}"

    def test_audit_entry_advisory_only_default_false(self):
        entry = AuditEntry(run_id="r1", event_type="x")
        assert entry.advisory_only is False

    def test_audit_entry_timestamp_set(self):
        before = time.time()
        entry = AuditEntry(run_id="r1", event_type="x")
        after = time.time()
        assert before <= entry.timestamp <= after


# ---------------------------------------------------------------------------
# 3. SupervisorRunStore — register / get / list
# ---------------------------------------------------------------------------

class TestSupervisorRunStoreRegister:

    def test_register_and_get(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1")
        store.register(run)
        assert store.get("r1") is run

    def test_get_unknown_returns_none(self, tmp_path: Path):
        store = _store(tmp_path)
        assert store.get("unknown") is None

    def test_list_all_returns_all(self, tmp_path: Path):
        store = _store(tmp_path)
        r1, r2 = _FakeRun("r1"), _FakeRun("r2")
        store.register(r1)
        store.register(r2)
        assert len(store.list_all()) == 2

    def test_list_active_excludes_terminal(self, tmp_path: Path):
        store = _store(tmp_path)
        r1 = _FakeRun("r1", status="running")
        r2 = _FakeRun("r2", status="blocked")
        store.register(r1)
        store.register(r2)
        active = store.list_active()
        assert r1 in active
        assert r2 not in active

    def test_register_creates_audit_entry(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1")
        store.register(run)
        log = store.get_audit_log("r1")
        assert len(log) >= 1
        assert log[0].event_type == "registered"


# ---------------------------------------------------------------------------
# 4. SupervisorRunStore — transitions
# ---------------------------------------------------------------------------

class TestSupervisorRunStoreTransitions:

    def test_valid_transition_changes_status(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)
        store.transition(run, "blocked", reason="tests failed")
        assert run.status == "blocked"

    def test_invalid_transition_raises_in_strict_mode(self, tmp_path: Path):
        store = _store(tmp_path, strict=True)
        run = _FakeRun("r1", status="blocked")
        store.register(run)
        with pytest.raises(InvalidTransitionError):
            store.transition(run, "running")

    def test_invalid_transition_logs_in_non_strict_mode(self, tmp_path: Path):
        store = _store(tmp_path, strict=False)
        run = _FakeRun("r1", status="blocked")
        store.register(run)
        # Should not raise in non-strict mode
        store.transition(run, "running")
        # Status should NOT have changed (soft-reject)
        assert run.status == "blocked"

    def test_advisory_transition_raises_on_status_change(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)
        with pytest.raises(AdvisoryMutationError):
            store.transition(run, "blocked", advisory_only=True)

    def test_advisory_noop_transition_allowed(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)
        # No-op (status unchanged) is always allowed even for advisory
        store.transition(run, "running", advisory_only=True)
        assert run.status == "running"

    def test_transition_creates_audit_entry(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)
        store.transition(run, "blocked", reason="tests failed")
        log = store.get_audit_log("r1")
        transition_entries = [e for e in log if e.event_type == "status_transition"]
        assert len(transition_entries) >= 1
        t = transition_entries[-1]
        assert t.from_status == "running"
        assert t.to_status == "blocked"

    def test_running_to_cancelling_allowed(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)
        store.transition(run, "cancelling", reason="user cancelled")
        assert run.status == "cancelling"

    def test_cancelling_to_cancelled_allowed(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="cancelling")
        store.register(run)
        store.transition(run, "cancelled", reason="cancel complete")
        assert run.status == "cancelled"


# ---------------------------------------------------------------------------
# 5. Audit log — append-only, persistence
# ---------------------------------------------------------------------------

class TestAuditLog:

    def test_audit_log_append_only(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1")
        store.register(run)
        initial_len = len(store.get_audit_log())
        store.append_audit(run, "custom_event", {"key": "value"})
        assert len(store.get_audit_log()) == initial_len + 1

    def test_audit_log_persisted_to_jsonl(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1")
        store.register(run)
        store.append_audit(run, "test_event", {"x": 1})

        # Read the JSONL file
        audit_path = tmp_path / ".igris" / "supervisor_audit.jsonl"
        assert audit_path.exists()
        lines = [l for l in audit_path.read_text().strip().splitlines() if l]
        assert len(lines) >= 2  # at least "registered" + "test_event"
        # Last line should be test_event
        last = json.loads(lines[-1])
        assert last["event_type"] == "test_event"

    def test_audit_log_loaded_on_init(self, tmp_path: Path):
        """Audit log from a previous session is loaded on store init (resume)."""
        # Create first store, write some entries
        store1 = _store(tmp_path)
        run = _FakeRun("r1")
        store1.register(run)
        store1.append_audit(run, "checkpoint", {"phase": "reasoning"})

        # Create second store (simulates restart)
        store2 = _store(tmp_path)
        log = store2.get_audit_log("r1")
        assert len(log) >= 2  # registered + checkpoint
        assert any(e.event_type == "checkpoint" for e in log)

    def test_audit_entries_are_immutable(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1")
        store.register(run)
        log = store.get_audit_log("r1")
        entry = log[0]
        with pytest.raises((AttributeError, TypeError)):
            entry.event_type = "mutated"  # type: ignore[misc]

    def test_get_audit_log_filtered_by_run_id(self, tmp_path: Path):
        store = _store(tmp_path)
        r1, r2 = _FakeRun("r1"), _FakeRun("r2")
        store.register(r1)
        store.register(r2)
        store.append_audit(r1, "r1_event")
        log_r1 = store.get_audit_log("r1")
        assert all(e.run_id == "r1" for e in log_r1)

    def test_advisory_audit_entry_flagged(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1")
        store.register(run)
        entry = store.append_audit(run, "advisory_proposal_generated", advisory_only=True)
        assert entry.advisory_only is True


# ---------------------------------------------------------------------------
# 6. Resume — get_resumable_run_ids
# ---------------------------------------------------------------------------

class TestResumeLogic:

    def test_run_not_in_resumable_after_terminal(self, tmp_path: Path):
        """A run that reached a terminal status is NOT resumable."""
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)
        store.transition(run, "completed", reason="done")

        store2 = _store(tmp_path)  # simulate restart
        resumable = store2.get_resumable_run_ids()
        assert "r1" not in resumable

    def test_run_in_resumable_if_never_terminated(self, tmp_path: Path):
        """A run that was registered but never terminated is resumable."""
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)
        # No terminal transition → in-progress when store2 starts

        store2 = _store(tmp_path)  # simulate restart
        resumable = store2.get_resumable_run_ids()
        assert "r1" in resumable

    def test_multiple_runs_resumable_detection(self, tmp_path: Path):
        store = _store(tmp_path)
        r1 = _FakeRun("r1", status="running")
        r2 = _FakeRun("r2", status="running")
        store.register(r1)
        store.register(r2)
        store.transition(r2, "blocked")  # r2 terminated

        store2 = _store(tmp_path)
        resumable = store2.get_resumable_run_ids()
        assert "r1" in resumable
        assert "r2" not in resumable


# ---------------------------------------------------------------------------
# 7. is_advisory_safe
# ---------------------------------------------------------------------------

class TestAdvisorySafety:

    def test_advisory_read_always_safe(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="blocked")
        safe, _ = store.is_advisory_safe(run, operation="read")
        assert safe is True

    def test_advisory_write_blocked_on_terminal(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="blocked")
        safe, reason = store.is_advisory_safe(run, operation="write")
        assert safe is False
        assert "terminal" in reason.lower()

    def test_advisory_write_safe_on_running(self, tmp_path: Path):
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        safe, _ = store.is_advisory_safe(run, operation="write")
        assert safe is True

    def test_advisory_proposal_cannot_alter_run_status(self, tmp_path: Path):
        """Advisory operations must never change run status — core invariant."""
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)

        # Simulate an advisory proposal trying to change status
        with pytest.raises(AdvisoryMutationError):
            store.transition(run, "blocked", advisory_only=True)

        # Status must be unchanged
        assert run.status == "running"

    def test_advisory_audit_does_not_change_run_state(self, tmp_path: Path):
        """append_audit with advisory_only=True must never change run fields."""
        store = _store(tmp_path)
        run = _FakeRun("r1", status="running")
        store.register(run)
        original_status = run.status
        original_outcome = run.outcome
        original_failure_class = run.failure_class

        store.append_audit(run, "advisory_proposal", {"proposal_type": "gather_context"}, advisory_only=True)

        assert run.status == original_status
        assert run.outcome == original_outcome
        assert run.failure_class == original_failure_class


# ---------------------------------------------------------------------------
# 8. Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:

    def test_concurrent_register(self, tmp_path: Path):
        """Concurrent register calls must not corrupt the store."""
        store = _store(tmp_path)
        errors = []

        def register_run(i: int) -> None:
            try:
                run = _FakeRun(f"r{i}")
                store.register(run)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register_run, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(store.list_all()) == 10

    def test_concurrent_audit_append(self, tmp_path: Path):
        """Concurrent audit appends must not corrupt the log."""
        store = _store(tmp_path)
        run = _FakeRun("r1")
        store.register(run)
        errors = []
        initial_len = len(store.get_audit_log())

        def append_entry(i: int) -> None:
            try:
                store.append_audit(run, f"event_{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=append_entry, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(store.get_audit_log()) == initial_len + 10
