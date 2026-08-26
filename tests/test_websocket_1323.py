"""Tests for WebSocket chat streaming (#1323 Phase 1)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from igris.web.websocket_routes import router as ws_router


def _create_app() -> FastAPI:
    """Create a test app with WebSocket routes."""
    app = FastAPI()
    app.include_router(ws_router)
    return app


class TestWebSocketChat:
    """Tests for /ws/chat WebSocket endpoint."""

    def test_ws_connect_anonymous(self) -> None:
        """WebSocket should accept anonymous connections."""
        app = _create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["profile_id"] == "anonymous"
            assert data["trust_level"] == "untrusted"

    def test_ws_ping_pong(self) -> None:
        """WebSocket should respond to ping with pong."""
        app = _create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()  # consume connected message
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"
            assert "timestamp" in data

    def test_ws_invalid_json(self) -> None:
        """WebSocket should handle invalid JSON gracefully."""
        app = _create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()  # consume connected message
            ws.send_text("not json")
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Invalid JSON" in data["message"]

    def test_ws_unknown_message_type(self) -> None:
        """WebSocket should handle unknown message types."""
        app = _create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()  # consume connected message
            ws.send_json({"type": "unknown_type"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Unknown message type" in data["message"]

    def test_ws_empty_chat_message(self) -> None:
        """WebSocket should reject empty chat messages."""
        app = _create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()  # consume connected message
            ws.send_json({"type": "chat", "message": ""})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Empty message" in data["message"]


class TestWebSocketLoop:
    """Tests for /ws/loop WebSocket endpoint."""

    def test_ws_loop_untrusted_rejected(self) -> None:
        """WebSocket /ws/loop should reject untrusted users."""
        app = _create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/loop") as ws:
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Insufficient permissions" in data["message"]

    def test_ws_loop_anonymous_rejected(self) -> None:
        """WebSocket /ws/loop should reject anonymous users."""
        app = _create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/loop") as ws:
            data = ws.receive_json()
            assert data["type"] == "error"


class TestWebSocketHelpers:
    """Tests for WebSocket helper functions."""

    def test_validate_token_empty(self) -> None:
        """Empty token should return anonymous/untrusted."""
        from igris.web.websocket_routes import _validate_token
        profile_id, trust_level = _validate_token("")
        assert profile_id == "anonymous"
        assert trust_level == "untrusted"

    def test_validate_token_invalid(self) -> None:
        """Invalid token should return anonymous/untrusted."""
        from igris.web.websocket_routes import _validate_token
        profile_id, trust_level = _validate_token("invalid-token-xyz")
        assert profile_id == "anonymous"
        assert trust_level == "untrusted"
