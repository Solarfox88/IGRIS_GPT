"""Tests for the teacher remediation API endpoint."""

import os
from fastapi.testclient import TestClient

from igris.models.config import CONFIG


def _make_client(tmp_path):
    os.environ["PROJECT_ROOT"] = str(tmp_path)
    CONFIG.project_root = tmp_path
    from igris.web.server import create_app
    return TestClient(create_app())


def test_teacher_remediate_returns_payload(tmp_path):
    client = _make_client(tmp_path)
    resp = client.post("/api/teacher/remediate", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert "payload" in data
    assert "proposed_task" in data
    assert "created_task_id" in data


def test_teacher_remediate_with_create(tmp_path):
    client = _make_client(tmp_path)
    # First create some tasks to give context
    client.post("/api/tasks", json={"description": "run tests"})
    client.post("/api/tasks", json={"description": "fix bug"})
    resp = client.post("/api/teacher/remediate", json={"create": True})
    assert resp.status_code == 200
    data = resp.json()
    assert "proposed_task" in data


def test_outcome_recent_endpoint(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/outcome/recent")
    assert resp.status_code == 200
    data = resp.json()
    assert "outcomes" in data
    assert isinstance(data["outcomes"], list)
