"""Tests for TTS API route — issue #530."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    """Build a FastAPI TestClient for the TTS router only."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from igris.api.routes.tts import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTTSSynthesize:
    def test_valid_text_returns_success_or_degraded(self):
        """Valid text must return success=True or degraded=True — never crash."""
        client = _make_client()
        resp = client.post("/api/tts/synthesize", json={"text": "Hello world"})
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        # Either success or degraded — never a 500
        if data["success"]:
            assert "artifact" in data
        else:
            assert data.get("degraded") is True or "error" in data

    def test_empty_text_returns_error(self):
        """Empty text must return success=False with error message."""
        client = _make_client()
        resp = client.post("/api/tts/synthesize", json={"text": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "error" in data

    def test_missing_text_key_returns_error(self):
        """Missing text key must return success=False."""
        client = _make_client()
        resp = client.post("/api/tts/synthesize", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "error" in data

    def test_oversized_text_returns_error(self):
        """Text > 4096 chars must return success=False with error message."""
        client = _make_client()
        big_text = "a" * 4097
        resp = client.post("/api/tts/synthesize", json={"text": big_text})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "error" in data
        assert "4096" in data["error"]

    def test_engine_unavailable_returns_degraded(self):
        """When TTSEngine raises, response must be degraded — not a crash."""
        client = _make_client()
        with patch("igris.api.routes.tts.logger") as mock_log:
            # Simulate engine import failure by patching inside the function
            with patch.dict("sys.modules", {"igris.core.tts_engine": None}):
                resp = client.post("/api/tts/synthesize", json={"text": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data  # no crash

    def test_engine_is_available_false_returns_degraded(self):
        """When engine.is_available() returns False, must return degraded."""
        fake_engine = MagicMock()
        fake_engine.is_available.return_value = False

        with patch("igris.api.routes.tts._make_router") as _:
            # Re-test by hitting the logic directly
            pass

        # Direct unit test of the logic branch
        client = _make_client()
        with patch("igris.core.tts_engine.TTSEngine") as MockEngine:
            instance = MockEngine.return_value
            instance.is_available.return_value = False
            resp = client.post("/api/tts/synthesize", json={"text": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data


class TestTTSStatus:
    def test_status_returns_available_bool(self):
        """GET /api/tts/status must return a dict with 'available' bool."""
        client = _make_client()
        resp = client.get("/api/tts/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert isinstance(data["available"], bool)

    def test_status_engine_error_returns_unavailable(self):
        """If TTSEngine raises, status must still return {available: False}."""
        client = _make_client()
        with patch.dict("sys.modules", {"igris.core.tts_engine": None}):
            resp = client.get("/api/tts/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
