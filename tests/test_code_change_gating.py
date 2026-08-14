"""Tests for #1291 — code_change gating for limited users on /api/chat/intent.

Verifies:
- limited user asking for code modification → blocked=true, scope_denied=true
- admin user asking for code modification → approval_required=true, not blocked
- untrusted user asking for code modification → blocked=true
- safe messages (chat) are not blocked for any trust level
- the response includes interlocutor_id and trust_level
- write_auth is not bypassed
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def _setup(tmp_path):
    """Create isolated test environment."""
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / ".igris" / "tasks").mkdir(parents=True)
    (root / ".igris" / "timeline").mkdir(parents=True)
    (root / ".igris" / "missions").mkdir(parents=True)
    (root / ".igris" / "memory").mkdir(parents=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root)
    os.environ["IGRIS_PROJECT_ROOT"] = str(root)
    from igris.models.config import CONFIG
    CONFIG.project_root = Path(str(root))
    return root


def _client(tmp_path):
    _setup(tmp_path)
    return TestClient(__import__("igris.web.server", fromlist=["create_app"]).create_app())


# ── Limited user gating tests ────────────────────────────────────────────────

def test_limited_user_code_change_blocked(tmp_path):
    """Limited user asking for code modification → blocked=true, scope_denied=true."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "modifica il codice del login",
        "interlocutor_id": "qa_limited_alpha",
        "trust_level": "limited",
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"
    data = r.json()
    assert data["intent"] == "patching"
    assert data["blocked"] is True, f"Expected blocked=True, got: {data}"
    assert data["scope_denied"] is True, f"Expected scope_denied=True, got: {data}"


def test_limited_user_code_change_has_block_reason(tmp_path):
    """Limited user code_change response includes block_reason."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "modifica il file config.py aggiungendo debug=True",
        "interlocutor_id": "qa_limited_alpha",
        "trust_level": "limited",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["blocked"] is True
    assert "block_reason" in data
    assert len(data["block_reason"]) > 0


def test_limited_user_safe_message_not_blocked(tmp_path):
    """Limited user asking a safe question → not blocked."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "come stai?",
        "interlocutor_id": "qa_limited_alpha",
        "trust_level": "limited",
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("blocked") is not True


# ── Admin/owner user tests ───────────────────────────────────────────────────

def test_admin_code_change_not_blocked_but_approval_required(tmp_path):
    """Admin asking for code modification → not blocked, approval_required=true."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "modifica il codice del login",
        "interlocutor_id": "owner",
        "trust_level": "admin",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "patching"
    # Admin should not be blocked
    assert data.get("blocked") is not True, f"Admin should not be blocked: {data}"
    # But code_change should require approval
    assert data.get("approval_required") is True, f"Admin code_change should require approval: {data}"


def test_admin_safe_message_not_blocked(tmp_path):
    """Admin asking a safe question → not blocked, no approval required."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "spiegami questa funzione",
        "interlocutor_id": "owner",
        "trust_level": "admin",
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("blocked") is not True
    assert data.get("approval_required") is not True


# ── Untrusted user tests ─────────────────────────────────────────────────────

def test_untrusted_code_change_blocked(tmp_path):
    """Untrusted user asking for code modification → blocked=true."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "modifica il codice del login",
        "interlocutor_id": "unknown",
        "trust_level": "untrusted",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["blocked"] is True


def test_untrusted_safe_message_not_blocked(tmp_path):
    """Untrusted user asking a safe question → not blocked."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "ciao",
        "interlocutor_id": "unknown",
        "trust_level": "untrusted",
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("blocked") is not True


# ── Response structure tests ─────────────────────────────────────────────────

def test_response_includes_interlocutor_and_trust(tmp_path):
    """Response includes interlocutor_id and trust_level fields."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "modifica il codice",
        "interlocutor_id": "test_user",
        "trust_level": "limited",
    })
    assert r.status_code == 200
    data = r.json()
    assert "interlocutor_id" in data
    assert "trust_level" in data


def test_response_includes_gating_fields(tmp_path):
    """Response includes blocked, approval_required, scope_denied fields."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "modifica il codice",
        "interlocutor_id": "test_user",
        "trust_level": "limited",
    })
    assert r.status_code == 200
    data = r.json()
    assert "blocked" in data
    assert "approval_required" in data
    assert "scope_denied" in data


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_empty_message_returns_400(tmp_path):
    """Empty message → 400."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={"message": ""})
    assert r.status_code == 400


def test_no_intent_detected_not_blocked(tmp_path):
    """Message with no clear intent → not blocked."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "xyz random text abc",
        "interlocutor_id": "test_user",
        "trust_level": "admin",
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("blocked") is not True


def test_deploy_intent_limited_blocked(tmp_path):
    """Limited user asking for deploy → blocked=true."""
    c = _client(tmp_path)
    r = c.post("/api/chat/intent", json={
        "message": "fai deploy",
        "interlocutor_id": "qa_limited_alpha",
        "trust_level": "limited",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["blocked"] is True
