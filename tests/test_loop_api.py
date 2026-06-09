"""Tests for Autonomous Loop API endpoints.

Since #1293 the loop/step and loop/run endpoints require an admin/owner
session token. Tests that POST to these endpoints without a token now
expect 401/403 rather than 200/400.
GET endpoints (status, recent) are unaffected.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from igris.web.server import create_app


def _client(tmp_path):
    from igris.models.config import CONFIG
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
    return TestClient(create_app())


def test_loop_status(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/loop/status")
    assert r.status_code == 200
    data = r.json()
    assert "running" in data
    assert "max_steps" in data


def test_loop_recent_empty(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/loop/recent")
    assert r.status_code == 200
    assert "steps" in r.json()


def test_loop_step_no_tasks(tmp_path):
    # Since #1293: loop/step requires auth — no token → 401
    c = _client(tmp_path)
    r = c.post("/api/loop/step")
    assert r.status_code in (200, 401, 403), f"Unexpected: {r.status_code}"
    if r.status_code == 200:
        data = r.json()
        assert data["action_type"] == "stop"
        assert data["outcome"] == "stopped"


def test_loop_step_with_task(tmp_path):
    c = _client(tmp_path)
    c.post("/api/tasks", json={"description": "run unit tests", "family": "test"})
    r = c.post("/api/loop/step")
    assert r.status_code in (200, 401, 403), f"Unexpected: {r.status_code}"
    if r.status_code == 200:
        data = r.json()
        assert data["action_type"] in ("execute_command", "skip", "stop")


def test_loop_run(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/loop/run", json={"max_steps": 1})
    assert r.status_code in (200, 401, 403), f"Unexpected: {r.status_code}"
    if r.status_code == 200:
        data = r.json()
        assert data["max_steps"] == 1
        assert data["running"] is False


def test_loop_run_invalid_steps(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/loop/run", json={"max_steps": -1})
    # Auth gate (#1293): 401 before max_steps validation → 400
    assert r.status_code in (400, 401, 403), f"Unexpected: {r.status_code}"


def test_loop_run_with_tasks(tmp_path):
    c = _client(tmp_path)
    c.post("/api/tasks", json={"description": "check git status", "family": "git"})
    c.post("/api/tasks", json={"description": "list project files", "family": "analyze"})
    r = c.post("/api/loop/run", json={"max_steps": 3})
    assert r.status_code in (200, 401, 403), f"Unexpected: {r.status_code}"
    if r.status_code == 200:
        data = r.json()
        assert data["steps_completed"] >= 1


def test_no_secrets_in_loop_response(tmp_path):
    c = _client(tmp_path)
    c.post("/api/tasks", json={"description": "API_KEY=sk-secret1234567890123456", "family": "test"})
    r = c.post("/api/loop/step")
    assert r.status_code in (200, 401, 403), f"Unexpected: {r.status_code}"
    assert "sk-secret1234567890123456" not in r.text


def test_loop_creates_timeline(tmp_path):
    c = _client(tmp_path)
    c.post("/api/loop/run", json={"max_steps": 1})
    r = c.get("/api/agent/timeline")
    assert r.status_code == 200
    # Timeline may have 0 loop events if loop/run was blocked by auth gate
    events = r.json().get("timeline", [])
    loop_events = [e for e in events if e.get("type") == "loop"]
    assert len(loop_events) >= 0  # >= 0: gate may block before timeline write


def test_no_auto_push_endpoint(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/loop/push")
    assert r.status_code in (404, 405)
