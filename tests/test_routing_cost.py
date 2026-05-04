"""Tests for routing and cost endpoints."""
import os
from fastapi.testclient import TestClient
from igris.web.server import create_app


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    return TestClient(create_app())


def test_routing_history_after_status(tmp_path):
    client = _client(tmp_path)
    # calling /api/status triggers choose_provider
    client.get("/api/status")
    resp = client.get("/api/routing/history")
    assert resp.status_code == 200
    assert len(resp.json()["history"]) > 0


def test_cost_summary_has_fields(tmp_path):
    client = _client(tmp_path)
    client.get("/api/status")
    resp = client.get("/api/cost/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_calls" in data
    assert "providers" in data


def test_no_api_key_in_cost(tmp_path):
    client = _client(tmp_path)
    client.get("/api/status")
    raw = client.get("/api/cost/summary").text
    for secret in ["OPENAI_API_KEY", "VASTAI_API_KEY", "sk-"]:
        assert secret not in raw
