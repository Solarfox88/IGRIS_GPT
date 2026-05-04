"""Tests for the A2A agent card endpoint."""
import os
from fastapi.testclient import TestClient
from igris.web.server import create_app


def _client(tmp_path):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    return TestClient(create_app())


def test_agent_card_returns_200(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200


def test_agent_card_contains_name(tmp_path):
    client = _client(tmp_path)
    data = client.get("/.well-known/agent-card.json").json()
    assert data["name"] == "IGRIS_GPT"


def test_agent_card_has_skills(tmp_path):
    client = _client(tmp_path)
    data = client.get("/.well-known/agent-card.json").json()
    skills = data.get("capabilities", {}).get("skills", [])
    assert len(skills) > 0


def test_agent_card_no_secrets(tmp_path):
    client = _client(tmp_path)
    raw = client.get("/.well-known/agent-card.json").text
    for secret in ["OPENAI_API_KEY", "VASTAI_API_KEY", ".env"]:
        assert secret not in raw


def test_agent_json_alias(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    assert resp.json()["name"] == "IGRIS_GPT"


def test_api_a2a_agent_card(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/a2a/agent-card")
    assert resp.status_code == 200
    assert resp.json()["name"] == "IGRIS_GPT"
