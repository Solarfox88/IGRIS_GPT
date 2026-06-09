"""Tests for terminal API safety."""
import os
from fastapi.testclient import TestClient
from igris.web.server import create_app


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    return TestClient(create_app())


def test_terminal_commands_returns_list(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/terminal/commands")
    assert resp.status_code == 200
    assert isinstance(resp.json()["commands"], list)
    assert len(resp.json()["commands"]) > 0


def test_terminal_unknown_command_rejected(tmp_path):
    # Since #1293: auth gate fires first → 401 without token
    # (previously 403 from safety check; both are "blocked" — correct behavior)
    client = _client(tmp_path)
    resp = client.post("/api/terminal/run", json={"command_id": "rm_rf_slash"})
    assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"


def test_terminal_raw_command_rejected(tmp_path):
    # Since #1293: auth gate fires first → 401 without token
    # (previously 400 from body validation)
    client = _client(tmp_path)
    resp = client.post("/api/terminal/run", json={"command": "ls -la"})
    assert resp.status_code in (400, 401, 403), f"Expected 400/401/403, got {resp.status_code}"
    if resp.status_code == 400:
        assert "command_id" in resp.json()["detail"].lower()


def test_terminal_missing_command_id(tmp_path):
    # Since #1293: auth gate fires first → 401 without token
    client = _client(tmp_path)
    resp = client.post("/api/terminal/run", json={})
    assert resp.status_code in (400, 401, 403), f"Expected 400/401/403, got {resp.status_code}"
