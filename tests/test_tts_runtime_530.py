"""
API-level tests for TTS routes — issue #530 runtime wiring.

Verifies:
- GET /api/tts/status returns 200 with {"available": bool}
- POST /api/tts/synthesize with valid text returns {"success": bool}
- POST /api/tts/synthesize with empty text returns error (no crash)
- Degraded mode: TTSEngine raises → still returns {"success": False, "degraded": True}
- TTS router registered in OPTIONAL_API_ROUTERS
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from igris.web.server import create_app
from igris.web.router_registry import OPTIONAL_API_ROUTERS


@pytest.fixture
def client(tmp_path):
    from igris.models.config import CONFIG
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    for d in [".igris/tasks", ".igris/timeline", ".igris/memory"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["IGRIS_PROJECT_ROOT"] = str(root)
    CONFIG.project_root = Path(str(root))
    return TestClient(create_app())


class TestTTSRegistration:
    def test_tts_in_optional_api_routers(self):
        """TTS module must be registered in OPTIONAL_API_ROUTERS."""
        modules = [m for m, _ in OPTIONAL_API_ROUTERS]
        assert "igris.api.routes.tts" in modules, (
            "igris.api.routes.tts missing from OPTIONAL_API_ROUTERS"
        )

    def test_tts_router_attr(self):
        """Router attribute must be 'router'."""
        for module, attr in OPTIONAL_API_ROUTERS:
            if module == "igris.api.routes.tts":
                assert attr == "router"
                break


class TestTTSStatusEndpoint:
    def test_status_returns_200(self, client):
        r = client.get("/api/tts/status")
        assert r.status_code == 200

    def test_status_has_available_field(self, client):
        r = client.get("/api/tts/status")
        data = r.json()
        assert "available" in data
        assert isinstance(data["available"], bool)

    def test_status_no_crash_on_engine_error(self, client):
        with patch("igris.api.routes.tts._engine", side_effect=RuntimeError("engine unavailable")):
            r = client.get("/api/tts/status")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is False
        assert "error" in data


class TestTTSSynthesizeEndpoint:
    def test_synthesize_valid_text(self, client):
        r = client.post("/api/tts/synthesize", json={"text": "Hello IGRIS"})
        assert r.status_code == 200
        data = r.json()
        assert "success" in data
        assert isinstance(data["success"], bool)

    def test_synthesize_empty_text_returns_error(self, client):
        r = client.post("/api/tts/synthesize", json={"text": ""})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert "error" in data

    def test_synthesize_whitespace_text_returns_error(self, client):
        r = client.post("/api/tts/synthesize", json={"text": "   "})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False

    def test_synthesize_returns_audio_on_success(self, client):
        """When engine succeeds, audio_base64 and format fields present."""
        mock_engine = MagicMock()
        mock_engine.synthesize.return_value = b"RIFF\x00\x00\x00\x00WAVEfmt "  # minimal wav-like bytes
        with patch("igris.api.routes.tts._engine", return_value=mock_engine):
            r = client.post("/api/tts/synthesize", json={"text": "Hello world"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "audio_base64" in data
        assert data["format"] == "wav"

    def test_synthesize_degraded_on_engine_raise(self, client):
        """If TTSEngine.synthesize raises, response must be degraded-safe."""
        mock_engine = MagicMock()
        mock_engine.synthesize.side_effect = RuntimeError("model OOM")
        with patch("igris.api.routes.tts._engine", return_value=mock_engine):
            r = client.post("/api/tts/synthesize", json={"text": "Hello"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert data.get("degraded") is True

    def test_synthesize_degraded_on_engine_unavailable(self, client):
        """If _engine() itself raises, response must be degraded-safe."""
        with patch("igris.api.routes.tts._engine", side_effect=ImportError("no transformers")):
            r = client.post("/api/tts/synthesize", json={"text": "Hello"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert data.get("degraded") is True

    def test_synthesize_includes_text_length(self, client):
        mock_engine = MagicMock()
        mock_engine.synthesize.return_value = b"\x00" * 100
        with patch("igris.api.routes.tts._engine", return_value=mock_engine):
            r = client.post("/api/tts/synthesize", json={"text": "Hi there"})
        data = r.json()
        if data["success"]:
            assert data["text_length"] == len("Hi there")
