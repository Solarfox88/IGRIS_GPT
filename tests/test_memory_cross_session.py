"""Tests for cross-session memory persistence fix (#1294).

Target: production-complete-memory-cross-session

Every test must fail if the preference is not actually written to disk or
not retrieved in a new session. No "degraded acceptable" compromises.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_unified_memory(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    return UnifiedMemory(project_root=str(tmp_path))


def _ltm_entries_for(tmp_path, interlocutor_id):
    from igris.core.long_term_memory import LongTermMemory
    ltm = LongTermMemory(base_path=tmp_path / ".igris" / "memory" / "long_term")
    domain = f"synaptic:{interlocutor_id}"
    return ltm.get_entries(domain, limit=20)


# ── 1. Disk persistence for authenticated user ────────────────────────────────

def test_memory_update_persists_to_disk_for_authenticated_user(tmp_path):
    """store_preference writes to disk and entry is found on second LTM open."""
    um = _make_unified_memory(tmp_path)
    result = um.store_preference(
        interlocutor_id="user_alice",
        trust_level="trusted",
        text="Preferisco risposte brevi e pratiche",
        tags=["memory_update"],
    )
    assert result.ok, f"store_preference failed: {result.warnings}"

    # Re-open LTM to confirm disk write (not in-memory cache)
    entries = _ltm_entries_for(tmp_path, "user_alice")
    assert entries, "No entries found after store — disk write did not happen"
    texts = [e.content.get("text", "") if isinstance(e.content, dict) else str(e.content) for e in entries]
    assert any("brevi" in t for t in texts), f"Preference text not in entries: {texts}"


# ── 2. Retrieved after logout/login (new UnifiedMemory instance) ─────────────

def test_memory_retrieved_after_logout_login_new_session(tmp_path):
    """Preference written in session 1 is retrieved in a fresh UnifiedMemory (session 2)."""
    # Session 1 — store
    um1 = _make_unified_memory(tmp_path)
    r = um1.store_preference(
        interlocutor_id="user_bob",
        trust_level="trusted",
        text="Preferisco sempre usare Python 3.12",
        tags=["memory_update"],
    )
    assert r.ok, f"Store failed: {r.warnings}"

    # Session 2 — new instance, same project_root (simulates login in new process)
    um2 = _make_unified_memory(tmp_path)
    retrieval = um2.retrieve_for_chat(
        query="Come preferisco lavorare?",
        interlocutor_id="user_bob",
        trust_level="trusted",
        limit=5,
    )
    assert retrieval.context, "retrieve_for_chat returned empty context after new session"
    assert "Python" in retrieval.context or "3.12" in retrieval.context, (
        f"Expected preference in context, got: {retrieval.context!r}"
    )


# ── 3. Retrieved with new chat session (ConversationRetriever path) ───────────

def test_memory_retrieved_after_new_chat_session(tmp_path):
    """ConversationRetriever.retrieve_for_context also finds the stored preference."""
    um = _make_unified_memory(tmp_path)
    r = um.store_preference(
        interlocutor_id="user_carol",
        trust_level="trusted",
        text="Preferisco risposte in italiano",
        tags=["memory_update"],
    )
    assert r.ok, f"Store failed: {r.warnings}"

    from igris.core.conversation_memory import ConversationRetriever
    retriever = ConversationRetriever(project_root=tmp_path)
    context = retriever.retrieve_for_context("user_carol", "trusted", limit=5)
    assert context, "ConversationRetriever returned empty context"
    assert "italiano" in context, f"Preference not in context: {context!r}"


# ── 4. Bound to profile_id, not client interlocutor_id ───────────────────────

def test_memory_bound_to_profile_id_not_client_interlocutor_id(tmp_path):
    """Preferences are stored under a specific profile_id domain."""
    um = _make_unified_memory(tmp_path)
    r = um.store_preference(
        interlocutor_id="profile_dan",
        trust_level="trusted",
        text="Preferisco output JSON strutturato",
        tags=["memory_update"],
    )
    assert r.ok

    # Same project root, different interlocutor_id — must NOT see profile_dan's preference
    entries_dan = _ltm_entries_for(tmp_path, "profile_dan")
    entries_eve = _ltm_entries_for(tmp_path, "profile_eve")

    assert entries_dan, "profile_dan should have entries"
    assert not entries_eve, f"profile_eve should have no entries, got: {entries_eve}"


# ── 5. Not visible to other user ─────────────────────────────────────────────

def test_memory_not_visible_to_other_user(tmp_path):
    """User A's preference is not returned when querying for User B."""
    um = _make_unified_memory(tmp_path)
    um.store_preference(
        interlocutor_id="user_frank",
        trust_level="trusted",
        text="Preferisco sempre code blocks con syntax highlighting",
        tags=["memory_update"],
    )

    retrieval_b = um.retrieve_for_chat(
        query="Come preferisci le risposte?",
        interlocutor_id="user_grace",
        trust_level="trusted",
        limit=5,
    )
    assert "Frank" not in (retrieval_b.context or "")
    assert "syntax highlighting" not in (retrieval_b.context or ""), (
        f"User A's preference leaked to User B: {retrieval_b.context!r}"
    )


# ── 6. Deterministic confirmation from router ─────────────────────────────────

def test_memory_update_returns_deterministic_confirmation(tmp_path, monkeypatch):
    """JarvisRequestRouter stores preference and sets memory_store_ok=True in metadata."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))
    from igris.core.jarvis_request_router import JarvisRequestRouter
    router = JarvisRequestRouter(project_root=str(tmp_path))
    decision = router.route(
        "Ricordati che preferisco risposte brevi",
        interlocutor_id="user_helen",
        trust_level="trusted",
    )
    assert decision.memory_mode == "store", f"Expected store, got {decision.memory_mode}"
    assert decision.metadata.get("memory_store_ok") is True, (
        f"memory_store_ok not True: {decision.metadata}"
    )
    assert decision.metadata.get("memory_store_id"), "memory_store_id missing"

    # Also verify it landed on disk
    entries = _ltm_entries_for(tmp_path, "user_helen")
    assert entries, "Router stored OK but no entry found on disk"


# ── 7. Secret redacted before storage ────────────────────────────────────────

def test_memory_update_secret_redacted_before_storage(tmp_path):
    """Raw secret must not appear in the stored preference entry."""
    um = _make_unified_memory(tmp_path)
    r = um.store_preference(
        interlocutor_id="user_ivan",
        trust_level="trusted",
        text="Ricordati che il mio token è FAKE_SECRET_MEMORY_CROSS_123456",
        tags=["memory_update"],
    )
    assert r.ok

    entries = _ltm_entries_for(tmp_path, "user_ivan")
    stored_text = json.dumps([e.content for e in entries])
    assert "FAKE_SECRET_MEMORY_CROSS_123456" not in stored_text, (
        f"Raw secret found in storage: {stored_text}"
    )


# ── 8. project_root consistency ───────────────────────────────────────────────

def test_memory_retrieval_uses_same_project_root_as_auth(tmp_path):
    """Writing and reading must use the same project_root to find entries."""
    root_a = tmp_path / "project_a"
    root_a.mkdir()
    root_b = tmp_path / "project_b"
    root_b.mkdir()

    from igris.core.unified_memory import UnifiedMemory
    um_a = UnifiedMemory(project_root=str(root_a))
    um_a.store_preference("user_jack", "trusted", "Preferisco Git flow")

    # Reading from different root must NOT find it
    um_b = UnifiedMemory(project_root=str(root_b))
    ret = um_b.retrieve_for_chat("workflow", "user_jack", "trusted", limit=5)
    assert "Git flow" not in (ret.context or ""), (
        "Preference from root_a leaked into root_b read"
    )

    # Reading from same root MUST find it
    ret_a = um_a.retrieve_for_chat("workflow", "user_jack", "trusted", limit=5)
    assert "Git flow" in (ret_a.context or ""), (
        f"Preference not found in same root: {ret_a.context!r}"
    )


# ── 9. memory_update without auth blocked ────────────────────────────────────

def test_memory_update_without_auth_blocked(tmp_path, monkeypatch):
    """Router warning is emitted for untrusted memory_update; unknown iid is not stored."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))
    from igris.core.jarvis_request_router import JarvisRequestRouter
    router = JarvisRequestRouter(project_root=str(tmp_path))
    decision = router.route(
        "Ricordati che preferisco Python",
        interlocutor_id="unknown",
        trust_level="untrusted",
    )
    assert decision.memory_mode == "store"
    # With interlocutor_id="unknown", store must NOT have been called
    assert not decision.metadata.get("memory_store_ok"), (
        "Should not have stored for unknown interlocutor_id"
    )
    entries = _ltm_entries_for(tmp_path, "unknown")
    assert not entries, "Preference was written for interlocutor_id='unknown' — isolation violation"


# ── 10. Limited user allowed to store own preference ─────────────────────────

def test_memory_update_limited_user_allowed_for_own_profile(tmp_path):
    """A limited-trust user can store preferences for their own profile."""
    um = _make_unified_memory(tmp_path)
    r = um.store_preference(
        interlocutor_id="user_kate",
        trust_level="limited",
        text="Preferisco risposte senza emoji",
        tags=["memory_update"],
    )
    assert r.ok, f"Limited user store failed: {r.warnings}"
    entries = _ltm_entries_for(tmp_path, "user_kate")
    assert entries, "Limited user preference not found on disk"
