"""Smoke tests for UI (HTML/JS/CSS presence)."""
import os
from fastapi.testclient import TestClient
from igris.web.server import create_app


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    return TestClient(create_app())


def test_index_contains_tabs(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    for tab in ["mission", "terminal", "files", "git", "tests", "logs", "agent", "tasks", "safety", "cost", "a2a"]:
        assert f'data-tab="{tab}"' in html.lower() or tab in html.lower()


def test_css_present(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/css/style.css")
    assert resp.status_code == 200
    assert "tab" in resp.text.lower()


def test_js_contains_endpoint_calls(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/js/app.js")
    assert resp.status_code == 200
    js = resp.text
    for endpoint in ["/api/health", "/api/terminal/commands", "/api/files/tree", "/api/git/status", "/api/tasks"]:
        assert endpoint in js
