"""API tests for Integration Layer endpoints — Epic #62."""

import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from igris.core.model_orchestrator import OrchestratorResult

from igris.web.server import create_app


def _fast_finish_result(*a, **k):
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


class TestIntegrationRunMissionAPI:
    """Test POST /api/integration/run-mission."""

    def test_run_mission_basic(self, client):
        with patch("igris.core.model_orchestrator.ModelOrchestrator.complete",
                   side_effect=_fast_finish_result):
            resp = client.post("/api/integration/run-mission", json={
                "goal": "Test mission",
                "max_steps": 2,
                "role": "coder",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "mission_id" in data
        assert "status" in data
        assert "decisions" in data
        assert "total_steps" in data

    def test_run_mission_empty_goal(self, client):
        with patch("igris.core.model_orchestrator.ModelOrchestrator.complete",
                   side_effect=_fast_finish_result):
            resp = client.post("/api/integration/run-mission", json={"max_steps": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total_steps"], int)


class TestIntegrationPipelineStatusAPI:
    """Test GET /api/integration/pipeline-status."""

    def test_pipeline_status(self, client):
        resp = client.get("/api/integration/pipeline-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "all_components_available" in data
        assert "components" in data
        assert "mission_controller" in data["components"]
        assert "model_orchestrator" in data["components"]
        assert "agent_reasoning_loop" in data["components"]


class TestIntegrationActionFamiliesAPI:
    """Test GET /api/integration/action-families."""

    def test_action_families(self, client):
        resp = client.get("/api/integration/action-families")
        assert resp.status_code == 200
        data = resp.json()
        assert "families" in data
        assert "code_nav" in data["families"]
        assert "code_edit" in data["families"]
        assert "test" in data["families"]
        assert "git" in data["families"]
        assert "terminal" in data["families"]
