"""API tests for Benchmark /api/ping endpoints — Epic #64."""

import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from igris.core.model_orchestrator import OrchestratorResult

from igris.web.server import create_app


def _fast_finish(*a, **k):
    """Mock LLM that returns finish immediately — avoids 30s Ollama timeout."""
    return OrchestratorResult(
        success=True,
        text=json.dumps({"action_type": "finish", "reason": "mocked", "mode": "coder"}),
        provider="mock",
        model="mock",
    )


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestPingAPI:
    """Test GET /api/ping — the benchmark target."""

    def test_ping(self, client):
        resp = client.get("/api/ping")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pong"] is True


class TestBenchmarkRunAPI:
    """Test POST /api/benchmark/run."""

    def test_deterministic(self, client):
        with patch("igris.core.model_orchestrator.ModelOrchestrator.complete",
                   side_effect=_fast_finish):
            resp = client.post("/api/benchmark/run", json={
                "mode": "deterministic",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "benchmark_id" in data
        assert "status" in data
        assert "phases_completed" in data
        assert "final_report" in data
        assert data["mode"] == "deterministic"
        assert data["total_phases"] == 8

    def test_integration_degraded(self, client):
        with patch("igris.core.model_orchestrator.ModelOrchestrator.complete",
                   side_effect=_fast_finish):
            resp = client.post("/api/benchmark/run", json={
                "mode": "integration",
                "max_steps": 2,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "integration"


class TestBenchmarkPhasesAPI:
    """Test GET /api/benchmark/phases."""

    def test_phases(self, client):
        resp = client.get("/api/benchmark/phases")
        assert resp.status_code == 200
        data = resp.json()
        assert "phases" in data
        assert "goal" in data
        assert len(data["phases"]) == 8
        assert "code_navigation" in data["phases"]
        assert "ping" in data["goal"]
