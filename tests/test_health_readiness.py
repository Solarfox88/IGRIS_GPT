"""Tests for health and readiness endpoints."""
import os
from fastapi.testclient import TestClient
from igris.web.server import create_app


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    return TestClient(create_app())


def test_health_returns_200(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_readiness_returns_json(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert "templates" in data
    assert "static" in data


def test_health_no_secrets(tmp_path):
    client = _client(tmp_path)
    raw = client.get("/api/health").text
    for secret in ["OPENAI_API_KEY", "VASTAI_API_KEY", "sk-"]:
        assert secret not in raw


def test_readiness_no_secrets(tmp_path):
    client = _client(tmp_path)
    raw = client.get("/api/readiness").text
    for secret in ["OPENAI_API_KEY", "VASTAI_API_KEY", "sk-"]:
        assert secret not in raw
