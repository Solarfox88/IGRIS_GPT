"""API tests for chat streaming + tier endpoints (Sprint 16)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from igris.web.server import create_app


@pytest.fixture
def client(tmp_path):
    from igris.models.config import CONFIG
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    for d in [".igris/tasks", ".igris/timeline", ".igris/memory", ".igris/reports/decisions"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root)
    CONFIG.project_root = Path(str(root))
    return TestClient(create_app())


class TestChatStreamAPI:
    def test_stream_returns_sse(self, client):
        r = client.post("/api/chat/stream", json={"message": "hello"})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

    def test_stream_has_chunks(self, client):
        r = client.post("/api/chat/stream", json={"message": "status"})
        lines = [l for l in r.text.split("\n") if l.startswith("data: ")]
        assert len(lines) >= 1
        # Last data line should be done
        last = json.loads(lines[-1][6:])
        assert last["type"] == "done"

    def test_stream_missing_message(self, client):
        r = client.post("/api/chat/stream", json={})
        assert r.status_code == 400

    def test_stream_no_secrets(self, client):
        r = client.post("/api/chat/stream", json={
            "message": "tell me about sk-abcdefghijklmnopqrstuvwxyz"
        })
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in r.text


class TestTierAPI:
    def test_get_tiers(self, client):
        r = client.get("/api/chat/tiers")
        assert r.status_code == 200
        d = r.json()
        assert "tiers" in d
        assert "auto" in d["tiers"]

    def test_set_tier(self, client):
        r = client.post("/api/chat/tiers", json={"tier": "local"})
        assert r.status_code == 200
        assert r.json()["tier"] == "local"
        # Reset
        client.post("/api/chat/tiers", json={"tier": "auto"})

    def test_set_invalid_tier(self, client):
        r = client.post("/api/chat/tiers", json={"tier": "vast"})
        assert r.status_code == 400

    def test_set_tier_missing(self, client):
        r = client.post("/api/chat/tiers", json={})
        assert r.status_code == 400

    def test_no_secrets_in_tiers(self, client):
        r = client.get("/api/chat/tiers")
        text = json.dumps(r.json())
        assert "sk-" not in text
        assert "ghp_" not in text
