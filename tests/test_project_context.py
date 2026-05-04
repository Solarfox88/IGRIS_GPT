"""Tests for project context endpoint."""
import os
from fastapi.testclient import TestClient
from igris.web.server import create_app


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    return TestClient(create_app())


def test_project_context_returns_json(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/project/context")
    assert resp.status_code == 200
    data = resp.json()
    assert "root" in data
    assert "tasks" in data
    assert "git" in data
