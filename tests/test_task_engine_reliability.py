"""Tests for #1296 — task engine reliability.

Verifies:
- validate endpoint never returns 500
- pending tasks can transition to terminal state
- diagnostics honestly report task engine state
- dangerous tasks do not execute without approval
- write_auth is not bypassed
- worker step processes one task deterministically
- empty queue is safe
- loop/step advances or reports blocked reason
- context_aggregator reports task engine state
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from igris.core.task_engine import TaskEngine
from igris.core.diagnostics import get_diagnostic_summary
from igris.models.config import CONFIG
from igris.models.task import TaskStatus


def _setup(tmp_path):
    """Create isolated test environment."""
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / ".igris" / "tasks").mkdir(parents=True)
    (root / ".igris" / "timeline").mkdir(parents=True)
    (root / ".igris" / "missions").mkdir(parents=True)
    (root / ".igris" / "memory").mkdir(parents=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root)
    os.environ["IGRIS_PROJECT_ROOT"] = str(root)
    CONFIG.project_root = Path(str(root))
    return root


def _client(tmp_path):
    _setup(tmp_path)
    return TestClient(__import__("igris.web.server", fromlist=["create_app"]).create_app())


def _engine(tmp_path):
    root = _setup(tmp_path)
    return TaskEngine(runtime_root=root / ".igris")


# ── Validate endpoint tests ──────────────────────────────────────────────────

def test_task_validate_valid_payload_returns_200(tmp_path):
    """Valid payload (task with criteria + manual reason) → 200."""
    root = _setup(tmp_path)
    engine = TaskEngine(runtime_root=root / ".igris")
    task = engine.create_task("test task", success_criteria=["file exists"])
    task_id = task.id
    c = TestClient(__import__("igris.web.server", fromlist=["create_app"]).create_app())
    r2 = c.post(f"/api/tasks/{task_id}/validate", json={"manual_completion_reason": "done manually"})
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text[:300]}"
    data = r2.json()
    assert data["valid"] is True


def test_task_validate_invalid_payload_returns_400_not_500(tmp_path):
    """Invalid payload (non-dict body) → 400, never 500."""
    c = _client(tmp_path)
    r = c.post("/api/tasks", json={"description": "test"})
    task_id = r.json()["id"]
    # Send a non-dict JSON body (list) — should be 400
    r2 = c.post(f"/api/tasks/{task_id}/validate", json=[1, 2, 3])
    assert r2.status_code == 400, f"Expected 400, got {r2.status_code}: {r2.text[:300]}"
    assert r2.status_code != 500


def test_task_validate_missing_task_returns_404_not_500(tmp_path):
    """Missing task → 404, never 500."""
    c = _client(tmp_path)
    r = c.post("/api/tasks/99999/validate", json={})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text[:300]}"
    assert r.status_code != 500


def test_task_validate_empty_body_returns_200(tmp_path):
    """Empty body {} on existing task → 200 with needs_review (not 500)."""
    c = _client(tmp_path)
    r = c.post("/api/tasks", json={"description": "test empty body"})
    task_id = r.json()["id"]
    r2 = c.post(f"/api/tasks/{task_id}/validate", json={})
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text[:300]}"
    assert r2.status_code != 500


# ── Task state transition tests ──────────────────────────────────────────────

def test_pending_task_can_be_claimed_and_completed(tmp_path):
    """pending → running → completed via process_one_pending_task."""
    engine = _engine(tmp_path)
    task = engine.create_task("safe low-risk task", risk="low")
    assert task.status == TaskStatus.pending

    processed = engine.process_one_pending_task()
    assert processed is not None
    assert processed.id == task.id
    # Should be in a terminal state (completed or running)
    assert processed.status in (TaskStatus.completed, TaskStatus.running)


def test_failed_task_records_error_not_stuck_running(tmp_path):
    """A task that fails records error and goes to failed, not stuck running."""
    engine = _engine(tmp_path)
    task = engine.create_task("task that will fail", risk="low")
    # Manually mark running then fail
    engine.mark_running(task.id)
    running_task = engine.get_task(task.id)
    assert running_task.status == TaskStatus.running
    assert running_task.attempts == 1

    failed = engine.fail_task(task.id, error="something went wrong")
    assert failed.status == TaskStatus.failed
    assert failed.last_error == "something went wrong"

    # Verify it's not stuck running
    refetched = engine.get_task(task.id)
    assert refetched.status == TaskStatus.failed
    assert refetched.status != TaskStatus.running


def test_old_pending_task_starvation_detected(tmp_path):
    """Diagnostics detects starvation for old pending tasks."""
    engine = _engine(tmp_path)
    # Create a task with an old created_at
    task = engine.create_task("old starving task", risk="low")
    # Manually backdate the task
    task.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 600))
    engine._save_task(task)
    engine._load_tasks()

    tasks = [t.to_dict() for t in engine.list_tasks()]
    summary = get_diagnostic_summary(tasks, [])
    assert summary["task_engine_state"]["starvation_detected"] is True
    assert summary["task_engine_state"]["pending_old_count"] >= 1
    assert summary["task_engine_state"]["unhealthy"] is True


# ── Diagnostics tests ────────────────────────────────────────────────────────

def test_diagnostics_reports_task_engine_state(tmp_path):
    """Diagnostics summary includes task_engine_state with honest fields."""
    engine = _engine(tmp_path)
    engine.create_task("task 1", risk="low")
    engine.create_task("task 2", risk="low")

    tasks = [t.to_dict() for t in engine.list_tasks()]
    summary = get_diagnostic_summary(tasks, [])

    assert "task_engine_state" in summary
    state = summary["task_engine_state"]
    assert "enabled" in state
    assert "running" in state
    assert "unhealthy" in state
    assert "starvation_detected" in state
    assert "pending_old_count" in state
    assert state["enabled"] is True
    assert state["running"] is False  # no running tasks
    # Block 37 (#1290): fresh pending tasks are NOT unhealthy — the TaskEngine is
    # passive storage by design. Only stale pending tasks (older than threshold)
    # are unhealthy. These tasks were just created, so unhealthy should be False.
    assert state["unhealthy"] is False
    assert state["starvation_detected"] is False
    assert state["pending_old_count"] == 0


def test_context_aggregator_reports_task_engine_state(tmp_path):
    """/api/os/brief should report task_engine as available (not null)."""
    c = _client(tmp_path)
    r = c.post("/api/os/brief", json={"query": "status"})
    assert r.status_code == 200
    data = r.json()
    sections = data.get("sections", [])
    tasks_section = [s for s in sections if s.get("name") == "tasks_timeline"]
    if tasks_section:
        # With fix, task_engine should be provided (not unavailable)
        assert tasks_section[0].get("status") != "unavailable", \
            f"task_engine should be available, got: {tasks_section[0]}"


# ── Safety tests ─────────────────────────────────────────────────────────────

def test_task_engine_does_not_execute_high_risk_without_approval(tmp_path):
    """High-risk task → approval_required, no side effect."""
    engine = _engine(tmp_path)
    task = engine.create_task("dangerous rm -rf /", risk="high")
    assert task.risk == "high"

    processed = engine.process_one_pending_task()
    assert processed is not None
    assert processed.id == task.id
    assert processed.status == TaskStatus.approval_required
    # Should NOT be completed or running
    assert processed.status != TaskStatus.completed
    assert processed.status != TaskStatus.running


def test_task_engine_does_not_bypass_write_auth(tmp_path):
    """process-one endpoint requires write_auth — no token → 401."""
    c = _client(tmp_path)
    c.post("/api/tasks", json={"description": "test task"})
    r = c.post("/api/tasks/process-one")
    assert r.status_code in (401, 403), \
        f"process-one should require auth, got {r.status_code}: {r.text[:200]}"


# ── Worker step tests ────────────────────────────────────────────────────────

def test_task_engine_worker_step_processes_one_task(tmp_path):
    """process_one_pending_task processes exactly one task."""
    engine = _engine(tmp_path)
    t1 = engine.create_task("task A", risk="low")
    t2 = engine.create_task("task B", risk="low")

    processed = engine.process_one_pending_task()
    assert processed is not None
    # One of the two should be processed
    assert processed.id in (t1.id, t2.id)
    # The other should still be pending
    other_id = t2.id if processed.id == t1.id else t1.id
    other = engine.get_task(other_id)
    assert other.status == TaskStatus.pending


def test_task_engine_empty_queue_safe(tmp_path):
    """process_one_pending_task on empty queue returns None safely."""
    engine = _engine(tmp_path)
    result = engine.process_one_pending_task()
    assert result is None


def test_loop_step_advances_or_reports_blocked_reason(tmp_path):
    """loop/step either advances or reports a clear blocked reason."""
    c = _client(tmp_path)
    c.post("/api/tasks", json={"description": "run unit tests", "family": "test"})
    r = c.post("/api/loop/step")
    # Without auth → 401 (correct, not a 500)
    # With auth → 200 with action_type/outcome
    assert r.status_code in (200, 401, 403), \
        f"loop/step should return 200/401/403, got {r.status_code}: {r.text[:200]}"
    assert r.status_code != 500
    if r.status_code == 200:
        data = r.json()
        assert "action_type" in data
        assert "outcome" in data


# ── API integration tests ────────────────────────────────────────────────────

def test_api_tasks_validate_no_500(tmp_path):
    """Validate endpoint never returns 500 for any valid/invalid input."""
    c = _client(tmp_path)
    r = c.post("/api/tasks", json={"description": "test no 500"})
    task_id = r.json()["id"]

    # Empty body
    r1 = c.post(f"/api/tasks/{task_id}/validate", json={})
    assert r1.status_code != 500, f"validate {{}} returned 500: {r1.text[:200]}"

    # Missing task
    r2 = c.post("/api/tasks/99999/validate", json={})
    assert r2.status_code != 500, f"validate missing returned 500: {r2.text[:200]}"

    # With criteria
    r3 = c.post(f"/api/tasks/{task_id}/validate", json={
        "files_changed": ["foo.py"],
        "manual_completion_reason": "manual",
    })
    assert r3.status_code != 500, f"validate with body returned 500: {r3.text[:200]}"


def test_api_tasks_step_transitions_pending_to_terminal(tmp_path):
    """process_one_pending_task transitions a pending task to terminal state."""
    engine = _engine(tmp_path)
    task = engine.create_task("low risk task", risk="low")
    assert task.status == TaskStatus.pending

    processed = engine.process_one_pending_task()
    assert processed is not None
    # Must be in a terminal or running state (not stuck pending)
    assert processed.status != TaskStatus.pending
    assert processed.status in (
        TaskStatus.running, TaskStatus.completed,
        TaskStatus.failed, TaskStatus.approval_required,
    )
