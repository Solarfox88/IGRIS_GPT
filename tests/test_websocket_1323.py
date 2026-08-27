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

    def test_ws_chat_streaming(self) -> None:
        """WebSocket chat should stream response in chunks (Phase 2)."""
        from unittest.mock import patch

        app = _create_app()
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()  # consume connected message

            with patch("igris.core.chat_engine.chat") as mock_chat:
                mock_chat.return_value = {
                    "text": "Hello world test",
                    "provider": "test",
                    "model": "test-model",
                }
                ws.send_json({"type": "chat", "message": "hi"})

                # Receive start message
                start = ws.receive_json()
                assert start["type"] == "start"
                assert start["message_id"].startswith("msg-")
                assert start["provider"] == "test"
                assert start["streaming_mode"] == "word_split"

                # Receive word chunks
                chunks = []
                while True:
                    data = ws.receive_json()
                    if data["type"] == "done":
                        assert data["total_chunks"] == 3
                        break
                    assert data["type"] == "chunk"
                    assert "content" in data
                    chunks.append(data["content"])

                # Reconstruct text
                streamed_text = "".join(chunks)
                assert "Hello" in streamed_text
                assert "world" in streamed_text
                assert "test" in streamed_text


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
