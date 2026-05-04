"""Tests for A2A task lifecycle endpoints."""
import os
from fastapi.testclient import TestClient
from igris.web.server import create_app


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    return TestClient(create_app())


def test_create_a2a_task(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/a2a/tasks", json={"description": "hello a2a"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "a2a"
    assert data["id"] is not None


def test_get_a2a_task(tmp_path):
    client = _client(tmp_path)
    create = client.post("/api/a2a/tasks", json={"description": "test task"}).json()
    resp = client.get(f"/api/a2a/tasks/{create['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_a2a_task_messages(tmp_path):
    client = _client(tmp_path)
    create = client.post("/api/a2a/tasks", json={"description": "msg task"}).json()
    tid = create["id"]
    resp = client.post(f"/api/a2a/tasks/{tid}/messages", json={"sender": "agent-x", "content": "hello"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_a2a_task_not_found(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/a2a/tasks/99999")
    assert resp.status_code == 404
