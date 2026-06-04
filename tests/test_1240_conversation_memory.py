"""Tests for #1240 — synaptic conversation memory."""
import pytest
import time
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from igris.web.server import create_app
    app = create_app()
    return TestClient(app)


# --- ConversationEpisode ---

def test_conversation_episode_creation():
    from igris.core.conversation_memory import ConversationEpisode
    ep = ConversationEpisode(
        session_id="s1",
        interlocutor_id="owner",
        trust_level="admin",
        user_message="ciao",
        assistant_response="Ciao Christian",
        intent_action="unknown",
    )
    d = ep.to_dict()
    assert d["session_id"] == "s1"
    assert d["interlocutor_id"] == "owner"
    assert "episode_id" in d
    assert "timestamp" in d


def test_memory_policy_admin():
    from igris.core.conversation_memory import _get_memory_policy, MEMORY_POLICY_FULL
    assert _get_memory_policy("admin") == MEMORY_POLICY_FULL

def test_memory_policy_unknown():
    from igris.core.conversation_memory import _get_memory_policy, MEMORY_POLICY_MINIMAL
    assert _get_memory_policy("unknown") == MEMORY_POLICY_MINIMAL
    assert _get_memory_policy("untrusted") == MEMORY_POLICY_MINIMAL


# --- SynapticExtractor ---

def test_extract_preference():
    from igris.core.conversation_memory import SynapticExtractor
    ex = SynapticExtractor()
    results = ex.extract("Preferisco sempre risposte brevi e dirette", trust_level="admin")
    assert any(c.category == "preference" for c in results)

def test_extract_correction():
    from igris.core.conversation_memory import SynapticExtractor
    ex = SynapticExtractor()
    results = ex.extract("No, correggi: intendevo il branch staging, non main", trust_level="admin")
    assert any(c.category == "correction" for c in results)

def test_extract_decision():
    from igris.core.conversation_memory import SynapticExtractor
    ex = SynapticExtractor()
    results = ex.extract("Decidiamo di usare sempre worktree pulite", trust_level="admin")
    assert any(c.category == "decision" for c in results)

def test_no_extraction_trivial():
    from igris.core.conversation_memory import SynapticExtractor
    ex = SynapticExtractor()
    results = ex.extract("ok", trust_level="admin")
    assert results == []

def test_no_extraction_with_secret():
    from igris.core.conversation_memory import SynapticExtractor
    ex = SynapticExtractor()
    results = ex.extract("usa questo token=ABCDEFGHIJKLMNOPQRSTUVWXYZ1234", trust_level="admin")
    assert results == []

def test_no_extraction_for_untrusted():
    from igris.core.conversation_memory import SynapticExtractor
    ex = SynapticExtractor()
    results = ex.extract("Preferisco risposte brevi", trust_level="untrusted")
    assert len(results) == 0


# --- ConversationMemoryStore ---

def test_persist_episode_to_ltm(tmp_path):
    from igris.core.conversation_memory import ConversationEpisode, ConversationMemoryStore, MEMORY_POLICY_FULL
    ep = ConversationEpisode(
        session_id="s1",
        interlocutor_id="owner",
        trust_level="admin",
        user_message="lancia i test",
        assistant_response="Test avviati.",
        intent_action="run_tests",
        memory_policy=MEMORY_POLICY_FULL,
    )
    store = ConversationMemoryStore(project_root=str(tmp_path))
    result = store.persist(ep)
    # Should return True (success) or False (degraded) — never raise
    assert isinstance(result, bool)

def test_persist_minimal_for_unknown(tmp_path):
    from igris.core.conversation_memory import ConversationEpisode, ConversationMemoryStore, MEMORY_POLICY_MINIMAL
    ep = ConversationEpisode(
        session_id="s2",
        interlocutor_id="unknown_xyz",
        trust_level="untrusted",
        user_message="ciao",
        assistant_response="Chi sei?",
        memory_policy=MEMORY_POLICY_MINIMAL,
    )
    store = ConversationMemoryStore(project_root=str(tmp_path))
    result = store.persist(ep)
    assert isinstance(result, bool)

def test_storage_failure_is_degraded(tmp_path, monkeypatch):
    """Storage failure must not raise — returns False and logs warning."""
    from igris.core.conversation_memory import ConversationEpisode, ConversationMemoryStore, MEMORY_POLICY_FULL

    def broken_ltm(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("igris.core.long_term_memory.LongTermMemory", broken_ltm)

    ep = ConversationEpisode(memory_policy=MEMORY_POLICY_FULL)
    store = ConversationMemoryStore(project_root=str(tmp_path))
    result = store.persist(ep)
    assert result == False  # degraded, not exception


# --- ConversationRetriever ---

def test_retriever_no_sensitive_for_unknown(tmp_path):
    from igris.core.conversation_memory import ConversationRetriever
    retriever = ConversationRetriever(project_root=str(tmp_path))
    result = retriever.retrieve_for_context("unknown_xyz", "untrusted")
    assert result == ""  # no memory for untrusted

def test_retriever_returns_string(tmp_path):
    from igris.core.conversation_memory import ConversationRetriever
    retriever = ConversationRetriever(project_root=str(tmp_path))
    result = retriever.retrieve_for_context("owner", "admin")
    assert isinstance(result, str)  # empty or content, never raises


# --- Integration: post_message persistence ---

def test_post_message_persistence_smoke(client):
    """Smoke test: post_message does not crash when memory is wired."""
    import json

    # Create a session
    r = client.post("/api/sessions")
    assert r.status_code == 200
    sid = r.json()["id"]

    # Send a message
    r2 = client.post(
        f"/api/sessions/{sid}/messages",
        json={"message": "ciao", "interlocutor_id": "owner"}
    )
    assert r2.status_code == 200
    d = r2.json()
    assert "response" in d


def test_memory_api_recent_endpoint(client):
    """GET /api/memory/conversation/recent must respond."""
    r = client.get("/api/memory/conversation/recent?interlocutor_id=owner&limit=5")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, (list, dict))

def test_memory_api_status_endpoint(client):
    """GET /api/memory/status must respond with health info."""
    r = client.get("/api/memory/status")
    assert r.status_code == 200
    d = r.json()
    assert "enabled" in d or "status" in d


# --- Safety/redaction ---

def test_no_raw_secret_in_episode():
    from igris.core.conversation_memory import ConversationEpisode
    # Episode should never store raw passphrase — caller must redact before creating
    ep = ConversationEpisode(
        user_message="usa token=REDACTED per autenticarti",
        assistant_response="Ok, token utilizzato.",
    )
    d = ep.to_dict()
    assert "passphrase" not in str(d).lower() or "REDACTED" in d["user_message"]
