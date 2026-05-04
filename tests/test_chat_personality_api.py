"""API tests for IGRIS-aware chat personality endpoints.

Sprint 31 — v0.6: Chat capabilities and intent API.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from igris.web.server import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/chat/capabilities
# ---------------------------------------------------------------------------

class TestChatCapabilitiesEndpoint:
    """Chat capabilities endpoint returns IGRIS-aware data."""

    @pytest.mark.anyio
    async def test_capabilities_returns_200(self, client):
        resp = await client.get("/api/chat/capabilities")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_capabilities_has_identity(self, client):
        resp = await client.get("/api/chat/capabilities")
        data = resp.json()
        assert "identity" in data
        assert "IGRIS" in data["identity"]

    @pytest.mark.anyio
    async def test_capabilities_has_safety(self, client):
        resp = await client.get("/api/chat/capabilities")
        data = resp.json()
        assert "safety" in data
        assert data["safety"]["no_free_shell"] is True

    @pytest.mark.anyio
    async def test_capabilities_no_secrets(self, client):
        resp = await client.get("/api/chat/capabilities")
        text = resp.text
        assert "ghp_" not in text
        assert "sk-" not in text

    @pytest.mark.anyio
    async def test_capabilities_categories(self, client):
        resp = await client.get("/api/chat/capabilities")
        data = resp.json()
        caps = data["capabilities"]
        assert "missions" in caps
        assert "tasks" in caps
        assert "patches" in caps
        assert "git_local" in caps
        assert "github_gated" in caps


# ---------------------------------------------------------------------------
# POST /api/chat/intent
# ---------------------------------------------------------------------------

class TestChatIntentEndpoint:
    """Chat intent detection endpoint works correctly."""

    @pytest.mark.anyio
    async def test_intent_machine_info(self, client):
        resp = await client.post("/api/chat/intent", json={"message": "dammi info sulla macchina"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "machine_info"
        assert data["has_response"] is True
        assert "/api/status" in data["grounded_response"]

    @pytest.mark.anyio
    async def test_intent_github(self, client):
        resp = await client.post("/api/chat/intent", json={"message": "riesci a vedere il mio GitHub?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "github_access"
        assert "I_APPROVE_GITHUB_WRITE" in data["grounded_response"]

    @pytest.mark.anyio
    async def test_intent_capabilities(self, client):
        resp = await client.post("/api/chat/intent", json={"message": "cosa puoi fare?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "capabilities"
        assert "IGRIS_GPT" in data["grounded_response"]

    @pytest.mark.anyio
    async def test_intent_shell_denied(self, client):
        resp = await client.post("/api/chat/intent", json={"message": "esegui un comando bash"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "shell_request"
        assert "sicurezza" in data["grounded_response"].lower()

    @pytest.mark.anyio
    async def test_intent_unknown(self, client):
        resp = await client.post("/api/chat/intent", json={"message": "ciao come stai?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] is None
        assert data["has_response"] is False

    @pytest.mark.anyio
    async def test_intent_empty_message_400(self, client):
        resp = await client.post("/api/chat/intent", json={"message": ""})
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_intent_network_info(self, client):
        resp = await client.post("/api/chat/intent", json={"message": "dammi info sulla rete"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "network_info"
        assert "sicurezza" in data["grounded_response"].lower()

    @pytest.mark.anyio
    async def test_intent_no_unrestricted_claim(self, client):
        resp = await client.post("/api/chat/intent", json={"message": "what can you do?"})
        data = resp.json()
        assert "unlimited" not in data["grounded_response"].lower()
        assert "unrestricted" not in data["grounded_response"].lower()


# ---------------------------------------------------------------------------
# Chat stream with personality
# ---------------------------------------------------------------------------

class TestChatStreamPersonality:
    """Chat stream endpoint uses IGRIS personality for known intents."""

    @pytest.mark.anyio
    async def test_stream_machine_info_igris_aware(self, client):
        resp = await client.post("/api/chat/stream", json={"message": "dammi info sulla macchina"})
        assert resp.status_code == 200
        # SSE stream; check body contains IGRIS-aware content
        body = resp.text
        assert "/api/status" in body or "igris_personality" in body

    @pytest.mark.anyio
    async def test_stream_github_mentions_approval(self, client):
        resp = await client.post("/api/chat/stream", json={"message": "riesci a vedere il mio GitHub?"})
        assert resp.status_code == 200
        body = resp.text
        assert "I_APPROVE_GITHUB_WRITE" in body or "gated" in body.lower()
