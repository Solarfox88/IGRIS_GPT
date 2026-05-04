"""Tests for A2A Task Store API endpoints."""

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
    (root / ".igris" / "a2a" / "tasks").mkdir(parents=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root)
    CONFIG.project_root = Path(str(root))
    return TestClient(create_app())


def _create_task(c, title="Test Task"):
    r = c.post("/api/a2a/store/tasks", json={"title": title})
    assert r.status_code == 200
    return r.json()


def test_create_a2a_task(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/a2a/store/tasks", json={"title": "My Task", "description": "Do it"})
    assert r.status_code == 200
    assert r.json()["title"] == "My Task"
    assert r.json()["status"] == "submitted"


def test_create_a2a_task_missing_fields(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/a2a/store/tasks", json={})
    assert r.status_code == 400


def test_list_a2a_tasks(tmp_path):
    c = _client(tmp_path)
    _create_task(c, "T1")
    _create_task(c, "T2")
    r = c.get("/api/a2a/store/tasks")
    assert r.status_code == 200
    assert len(r.json()["tasks"]) == 2


def test_get_a2a_task(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    r = c.get(f"/api/a2a/store/tasks/{task['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == task["id"]


def test_get_a2a_task_not_found(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/a2a/store/tasks/nonexistent")
    assert r.status_code == 404


def test_update_status(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    r = c.post(f"/api/a2a/store/tasks/{task['id']}/status", json={"status": "working"})
    assert r.status_code == 200
    assert r.json()["status"] == "working"


def test_update_status_invalid(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    r = c.post(f"/api/a2a/store/tasks/{task['id']}/status", json={"status": "invalid"})
    assert r.status_code == 400


def test_add_artifact(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    r = c.post(f"/api/a2a/tasks/{task['id']}/artifacts", json={
        "name": "output.txt", "content": "Result data"
    })
    assert r.status_code == 200
    assert r.json()["name"] == "output.txt"


def test_add_artifact_missing_name(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    r = c.post(f"/api/a2a/tasks/{task['id']}/artifacts", json={"content": "data"})
    assert r.status_code == 400


def test_list_artifacts(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    c.post(f"/api/a2a/tasks/{task['id']}/artifacts", json={"name": "a1.txt", "content": "c1"})
    c.post(f"/api/a2a/tasks/{task['id']}/artifacts", json={"name": "a2.txt", "content": "c2"})
    r = c.get(f"/api/a2a/tasks/{task['id']}/artifacts")
    assert r.status_code == 200
    assert len(r.json()["artifacts"]) == 2


def test_artifacts_not_found(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/a2a/tasks/nonexistent/artifacts")
    assert r.status_code == 404


def test_cancel_task(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    r = c.post(f"/api/a2a/tasks/{task['id']}/cancel", json={"reason": "No longer needed"})
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


def test_cancel_completed_task(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    c.post(f"/api/a2a/store/tasks/{task['id']}/status", json={"status": "completed"})
    r = c.post(f"/api/a2a/tasks/{task['id']}/cancel", json={})
    assert r.status_code == 404


def test_events(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    c.post(f"/api/a2a/store/tasks/{task['id']}/status", json={"status": "working"})
    c.post(f"/api/a2a/tasks/{task['id']}/artifacts", json={"name": "a.txt", "content": "c"})
    r = c.get(f"/api/a2a/tasks/{task['id']}/events")
    assert r.status_code == 200
    assert len(r.json()["events"]) >= 3


def test_events_not_found(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/a2a/tasks/nonexistent/events")
    assert r.status_code == 404


def test_secret_artifact_redacted(tmp_path):
    c = _client(tmp_path)
    task = _create_task(c)
    c.post(f"/api/a2a/tasks/{task['id']}/artifacts", json={
        "name": "config", "content": "API_KEY=sk-secrettest1234567890123456"
    })
    r = c.get(f"/api/a2a/tasks/{task['id']}/artifacts")
    assert "sk-secrettest1234567890123456" not in r.text


def test_no_secrets_in_response(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/a2a/store/tasks", json={"title": "API_KEY=sk-secrettest1234567890123456"})
    assert "sk-secrettest1234567890123456" not in r.text
