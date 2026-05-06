"""API tests for Agent Action Schema endpoints — Epic #58."""

import json
import pytest
from fastapi.testclient import TestClient

from igris.web.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestAgentSchemaAPI:
    """Test /api/agent/* endpoints."""

    def test_get_schema(self, client):
        resp = client.get("/api/agent/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "schema" in data
        assert data["schema"]["type"] == "object"
        assert "action_type" in data["schema"]["properties"]

    def test_get_roles(self, client):
        resp = client.get("/api/agent/roles")
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert len(data["roles"]) == 11
        roles = {r["role"] for r in data["roles"]}
        assert "coder" in roles
        assert "devops" in roles

    def test_get_action_types(self, client):
        resp = client.get("/api/agent/action-types")
        assert resp.status_code == 200
        data = resp.json()
        assert "action_types" in data
        assert "search_code" in data["action_types"]
        assert "routing" in data
        assert "read_only" in data
        assert "write" in data
        assert "risk_gated" in data

    def test_get_examples(self, client):
        resp = client.get("/api/agent/examples")
        assert resp.status_code == 200
        data = resp.json()
        assert "examples" in data
        assert len(data["examples"]) >= 10

    def test_validate_valid_action(self, client):
        action = {
            "mode": "coder",
            "action_type": "read_file_range",
            "reason": "check code",
            "parameters": {"path": "server.py"},
        }
        resp = client.post("/api/agent/validate", json=action)
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert len(data["errors"]) == 0

    def test_validate_invalid_action(self, client):
        action = {
            "mode": "planner",
            "action_type": "write_file",
            "reason": "test",
            "parameters": {"path": "foo.py", "content": "hello"},
        }
        resp = client.post("/api/agent/validate", json=action)
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_parse_valid_output(self, client):
        raw = json.dumps({
            "mode": "coder",
            "action_type": "git_status",
            "reason": "check state",
            "parameters": {},
        })
        resp = client.post("/api/agent/parse", json={"raw_output": raw})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["parsed"]["action_type"] == "git_status"

    def test_parse_invalid_output(self, client):
        resp = client.post("/api/agent/parse", json={"raw_output": "not json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["parsed"] is None

    def test_get_prompt_contract(self, client):
        resp = client.get("/api/agent/prompt-contract?role=coder")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "coder"
        assert "IGRIS" in data["prompt"]
        assert "write_file" in data["prompt"]


class TestOrchestratorAPI:
    """Test /api/orchestrator/* endpoints."""

    def test_get_providers(self, client):
        resp = client.get("/api/orchestrator/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert len(data["providers"]) >= 3
        names = {p["name"] for p in data["providers"]}
        assert "ollama" in names
        assert "openai" in names
        assert "deepseek" in names

    def test_providers_no_secrets(self, client):
        resp = client.get("/api/orchestrator/providers")
        data = resp.json()
        for p in data["providers"]:
            # Should have api_key_env, not actual key
            for k, v in p.items():
                if isinstance(v, str):
                    assert not v.startswith("sk-"), f"Possible API key in {k}"

    def test_get_profiles(self, client):
        resp = client.get("/api/orchestrator/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "chat" in data["profiles"]
        assert data["profiles"]["safety_check"] == "deterministic"

    def test_get_cost(self, client):
        resp = client.get("/api/orchestrator/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_cost" in data
        assert "call_count" in data
