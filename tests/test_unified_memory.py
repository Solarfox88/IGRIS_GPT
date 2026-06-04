"""Tests for UnifiedMemory facade (#1242)."""
from __future__ import annotations

import json
import pytest


# ── Initialization ─────────────────────────────────────────────────────────

def test_unified_memory_initializes_with_tmp_project_root(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    assert mem.project_root == tmp_path


def test_unified_memory_healthcheck_reports_backends(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    h = mem.healthcheck()
    assert "backends" in h
    assert "long_term_memory" in h["backends"]
    assert "memory_graph" in h["backends"]


def test_unified_memory_healthcheck_ok_field(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    h = mem.healthcheck()
    assert isinstance(h["ok"], bool)


def test_unified_memory_degraded_ltm_does_not_crash(tmp_path, monkeypatch):
    import igris.core.long_term_memory as ltm_mod
    original_init = ltm_mod.LongTermMemory.__init__
    def bad_init(self, *a, **kw):
        raise RuntimeError("db unavail")
    monkeypatch.setattr(ltm_mod.LongTermMemory, "__init__", bad_init)
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)  # must not raise
    h = mem.healthcheck()
    assert h["backends"]["long_term_memory"] == "degraded"


# ── Store preference ───────────────────────────────────────────────────────

def test_store_preference_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_preference("owner", "admin", "Preferisco risposte brevi")
    assert r.ok
    assert r.kind == "preference"
    assert r.id


def test_store_preference_to_dict(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_preference("owner", "admin", "test pref")
    d = r.to_dict()
    assert d["ok"] is True
    assert d["kind"] == "preference"


# ── Store decision ─────────────────────────────────────────────────────────

def test_store_decision_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_decision("Use async APIs", project="test_proj", confidence=0.9)
    assert r.ok
    assert r.kind == "decision"


# ── Store lesson ───────────────────────────────────────────────────────────

def test_store_lesson_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_lesson("Always validate input", project="test_proj")
    assert r.ok
    assert r.kind == "lesson"


# ── Store correction ───────────────────────────────────────────────────────

def test_store_correction_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_correction("Wrong answer", interlocutor_id="owner", trust_level="admin")
    assert r.ok
    assert r.kind == "correction"


# ── Store run event ────────────────────────────────────────────────────────

def test_store_run_event_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_run_event("m1", "deploy", "success", outcome="done", project="myproj")
    assert r.ok
    assert r.kind == "run_event"


# ── Store fact ─────────────────────────────────────────────────────────────

def test_store_fact_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_fact("IGRIS uses Python 3.11", fact_type="project_fact", project="main")
    assert r.ok


# ── Retrieve for chat ──────────────────────────────────────────────────────

def test_retrieve_for_chat_admin_returns_retrieval_result(tmp_path):
    from igris.core.unified_memory import UnifiedMemory, RetrievalResult
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "Preferisco risposte brevi")
    result = mem.retrieve_for_chat("risposte", "owner", "admin")
    assert isinstance(result, RetrievalResult)
    assert isinstance(result.context, str)


def test_retrieve_for_chat_untrusted_no_sensitive_items(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "Preferisco risposte brevi")
    result = mem.retrieve_for_chat("query", "unknown_xyz", "untrusted")
    for item in result.items:
        # untrusted must not receive sensitive trust_required items
        assert not (item.trust_required == "trusted" and item.safe_for_context), (
            f"Sensitive item leaked to untrusted: {item}"
        )


def test_unified_memory_does_not_auto_elevate_owner(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "Preferisco risposte brevi")
    # owner with untrusted trust_level must NOT get sensitive items
    result = mem.retrieve_for_chat("query", "owner", "untrusted")
    sensitive_items = [i for i in result.items if i.trust_required == "trusted"]
    assert len(sensitive_items) == 0, (
        f"Owner with untrusted trust_level got sensitive items: {sensitive_items}"
    )


# ── Secret redaction ───────────────────────────────────────────────────────

def test_no_raw_secret_in_store_preference_output(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    FAKE_SECRET = "FAKE_TOKEN_ABCDEFGHIJ123456_NOTREAL"
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", f"usa token={FAKE_SECRET} per auth")
    result = mem.retrieve_for_chat("token", "owner", "admin")
    output = json.dumps(result.to_dict())
    assert FAKE_SECRET not in output, f"Raw fake secret in output: {output[:500]}"


def test_no_raw_secret_in_lesson_influence_report(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    FAKE = "FAKE_SECRET_LESSON_TOREDICT_XYZ999"
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_lesson(f"usa token={FAKE} nel deploy", project="testproj")
    result = mem.retrieve_for_mission("deploy", project="testproj")
    report = mem.memory_influence_report(result)
    assert FAKE not in report, f"Secret in influence report: {report}"


# ── Feedback / lifecycle ───────────────────────────────────────────────────

def test_record_feedback_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.record_feedback("mem-123", used=True, helpful=True, outcome="success")
    assert r.ok
    assert r.kind == "feedback"


def test_mark_superseded_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.mark_superseded("old-id", "new-id", reason="updated")
    assert r.ok
    assert r.kind == "superseded"


def test_forget_returns_ok(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.forget("mem-999", reason="user_request")
    assert r.ok
    assert r.kind == "forgotten"


# ── Influence report ───────────────────────────────────────────────────────

def test_memory_influence_report_empty(tmp_path):
    from igris.core.unified_memory import UnifiedMemory, RetrievalResult
    mem = UnifiedMemory(project_root=tmp_path)
    empty = RetrievalResult(context="", items=[], influence_report="")
    report = mem.memory_influence_report(empty)
    assert "No memory context" in report


def test_memory_influence_report_with_items(tmp_path):
    from igris.core.unified_memory import UnifiedMemory, MemoryItem, RetrievalResult
    mem = UnifiedMemory(project_root=tmp_path)
    items = [MemoryItem(id="1", source="ltm_lesson", kind="lesson",
                        text="Always validate", score=0.9, confidence=0.85)]
    result = RetrievalResult(context="ctx", items=items, influence_report="x")
    report = mem.memory_influence_report(result)
    assert "lesson" in report


# ── Retrieve for mission ───────────────────────────────────────────────────

def test_retrieve_for_mission_returns_result(tmp_path):
    from igris.core.unified_memory import UnifiedMemory, RetrievalResult
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_lesson("Deploy to staging first", project="myproj")
    result = mem.retrieve_for_mission("deploy", project="myproj")
    assert isinstance(result, RetrievalResult)


def test_retrieve_for_mission_untrusted_no_sensitive(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_preference("owner", "admin", "some pref")
    result = mem.retrieve_for_mission("deploy", interlocutor_id="owner", trust_level="untrusted")
    for item in result.items:
        assert not (item.trust_required == "trusted" and item.safe_for_context)


# ── Fix 7: store_* real persistence tests ─────────────────────────────────

def test_store_preference_persists_to_ltm(tmp_path):
    """store_preference with working LTM must actually write — verifiable via new LTM instance."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.long_term_memory import LongTermMemory

    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_preference("owner", "admin", "Preferisco risposte brevi")

    if mem._ltm is not None:
        assert r.ok, f"store_preference failed when LTM available: {r.warnings}"
        assert r.id, "store_preference returned empty id when LTM available"
        # Verify persistence on disk via a fresh LTM instance
        ltm_path = tmp_path / ".igris" / "memory" / "long_term"
        ltm2 = LongTermMemory(storage_dir=str(ltm_path))
        found = ltm2.search("Preferisco", domains=[f"synaptic:owner"], limit=5)
        assert found, "preference not found in LTM after store_preference"
    else:
        assert r.ok is False, "ok must be False when LTM unavailable"


def test_store_decision_persists_to_ltm(tmp_path):
    """store_decision with working LTM must actually write."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.long_term_memory import LongTermMemory

    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_decision("Use async APIs", project="test_proj", confidence=0.9)

    if mem._ltm is not None:
        assert r.ok, f"store_decision failed when LTM available: {r.warnings}"
        ltm_path = tmp_path / ".igris" / "memory" / "long_term"
        ltm2 = LongTermMemory(storage_dir=str(ltm_path))
        found = ltm2.search("async", domains=["decision:test_proj"], limit=5)
        assert found, "decision not found in LTM after store_decision"
    else:
        assert r.ok is False


def test_store_lesson_persists_to_ltm(tmp_path):
    """store_lesson with working LTM must actually write."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.long_term_memory import LongTermMemory

    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_lesson("Always validate input", project="test_proj")

    if mem._ltm is not None:
        assert r.ok, f"store_lesson failed when LTM available: {r.warnings}"
        ltm_path = tmp_path / ".igris" / "memory" / "long_term"
        ltm2 = LongTermMemory(storage_dir=str(ltm_path))
        found = ltm2.search("validate", domains=["lesson:test_proj"], limit=5)
        assert found, "lesson not found in LTM after store_lesson"
    else:
        assert r.ok is False


def test_store_fact_persists_to_ltm(tmp_path):
    """store_fact with working LTM must actually write."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.long_term_memory import LongTermMemory

    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.store_fact("IGRIS uses Python 3.11", fact_type="project_fact", project="main")

    if mem._ltm is not None:
        assert r.ok, f"store_fact failed when LTM available: {r.warnings}"
        ltm_path = tmp_path / ".igris" / "memory" / "long_term"
        ltm2 = LongTermMemory(storage_dir=str(ltm_path))
        found = ltm2.search("Python 3.11", domains=["fact:main"], limit=5)
        assert found, "fact not found in LTM after store_fact"
    else:
        assert r.ok is False


# ── Fix 8: run_event / feedback secret tests ───────────────────────────────

def test_store_run_event_redacts_secrets(tmp_path):
    """store_run_event must not persist raw secrets to disk."""
    from igris.core.unified_memory import UnifiedMemory
    from pathlib import Path

    FAKE = "FAKE_SECRET_RUNEVENT_NOTREAL_9988"
    mem = UnifiedMemory(project_root=tmp_path)
    mem.store_run_event(
        mission_id="m1",
        action=f"deploy token={FAKE}",
        status="ok",
        outcome=f"used key={FAKE}",
        project="test",
    )
    # Check all JSON files under .igris
    storage = tmp_path / ".igris"
    all_text = ""
    for f in storage.rglob("*.json"):
        all_text += f.read_text()
    assert FAKE not in all_text, f"Raw secret in storage after store_run_event: found in files"


def test_record_feedback_redacts_secrets(tmp_path):
    """record_feedback must not persist raw secrets (query/notes) to disk."""
    from igris.core.unified_memory import UnifiedMemory
    from pathlib import Path

    FAKE = "FAKE_SECRET_FEEDBACK_NOTREAL_7766"
    mem = UnifiedMemory(project_root=tmp_path)
    mem.record_feedback(
        memory_id="m1",
        used=True,
        query=f"token={FAKE}",
        notes=f"passphrase={FAKE}",
    )
    storage = tmp_path / ".igris"
    all_text = ""
    for f in storage.rglob("*.json"):
        all_text += f.read_text()
    assert FAKE not in all_text, f"Raw secret in storage after record_feedback"


# ── Fix 9: healthcheck primary backend degraded => ok=False ───────────────

def test_healthcheck_primary_backend_degraded_ok_false(tmp_path, monkeypatch):
    """healthcheck must return ok=False when a primary backend (LTM) is degraded."""
    import igris.core.long_term_memory as ltm_mod

    original_init = ltm_mod.LongTermMemory.__init__

    def broken_init(self, *args, **kwargs):
        raise RuntimeError("forced degraded for test")

    monkeypatch.setattr(ltm_mod.LongTermMemory, "__init__", broken_init)

    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    h = mem.healthcheck()
    assert h["ok"] is False, (
        "healthcheck should return ok=False when primary backend (LTM) is degraded"
    )
    assert h["backends"]["long_term_memory"] == "degraded"


# ── Fix 10: retrieve_for_chat documents default project scope ──────────────

def test_retrieve_for_chat_uses_default_project(tmp_path):
    """retrieve_for_chat uses 'default' project scope when no project specified."""
    from igris.core.unified_memory import UnifiedMemory

    mem = UnifiedMemory(project_root=tmp_path)
    result = mem.retrieve_for_chat("query", "owner", "admin")
    # Must work without project param — uses default
    assert isinstance(result.context, str)
    assert isinstance(result.items, list)


# ─── store_episode strict tests ───────────────────────────────────────────────

def test_store_episode_ok_true_when_conv_store_persists(tmp_path):
    """ok=True only when ConversationMemoryStore.persist() returns True."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.conversation_memory import ConversationEpisode

    mem = UnifiedMemory(project_root=tmp_path)
    ep = ConversationEpisode(
        session_id="s_strict", interlocutor_id="owner", trust_level="admin",
        user_message="test", assistant_response="ok"
    )
    r = mem.store_episode(ep)

    if mem._conv_store is not None:
        if r.ok:
            assert r.id, "ok=True but id is empty"
            assert r.backends.get("conversation_store") == "ok"
        else:
            assert not r.id, "ok=False but id is non-empty"
            assert r.backends.get("conversation_store") in ("degraded", "unavailable")
    else:
        assert r.ok is False
        assert r.backends.get("conversation_store") == "unavailable"


def test_store_episode_ok_false_when_conv_store_unavailable(tmp_path):
    """ok=False when ConversationMemoryStore is not available."""
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem._conv_store = None  # Force unavailable

    from igris.core.conversation_memory import ConversationEpisode
    ep = ConversationEpisode(session_id="s1", interlocutor_id="owner")
    r = mem.store_episode(ep)

    assert r.ok is False, f"Expected ok=False when conv_store unavailable, got {r.ok}"
    assert r.id == "", f"Expected empty id when ok=False, got {r.id!r}"
    assert r.backends.get("conversation_store") == "unavailable"


def test_store_episode_ok_false_when_persist_returns_false(tmp_path, monkeypatch):
    """ok=False when ConversationMemoryStore.persist() returns False."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.conversation_memory import ConversationMemoryStore

    monkeypatch.setattr(ConversationMemoryStore, "persist", lambda self, ep: False)

    mem = UnifiedMemory(project_root=tmp_path)
    from igris.core.conversation_memory import ConversationEpisode
    ep = ConversationEpisode(session_id="s1", interlocutor_id="owner")
    r = mem.store_episode(ep)

    assert r.ok is False, "Expected ok=False when persist() returns False"
    assert r.id == ""
    assert r.backends.get("conversation_store") == "degraded"
    assert len(r.warnings) > 0


def test_store_episode_ok_false_when_persist_raises(tmp_path, monkeypatch):
    """ok=False when ConversationMemoryStore.persist() raises."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.conversation_memory import ConversationMemoryStore

    def broken_persist(self, ep):
        raise RuntimeError("disk full")
    monkeypatch.setattr(ConversationMemoryStore, "persist", broken_persist)

    mem = UnifiedMemory(project_root=tmp_path)
    from igris.core.conversation_memory import ConversationEpisode
    ep = ConversationEpisode(session_id="s1", interlocutor_id="owner")
    r = mem.store_episode(ep)

    assert r.ok is False, "Expected ok=False when persist() raises"
    assert r.id == ""
    assert r.backends.get("conversation_store") == "degraded"
    assert any("disk full" in w or "conv_store" in w for w in r.warnings)


# ─── record_feedback strict tests ────────────────────────────────────────────

def test_record_feedback_ok_true_when_ltm_writes(tmp_path):
    """ok=True when LTM writes successfully."""
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.record_feedback("m1", used=True, helpful=True, outcome="success")

    if mem._ltm is not None:
        assert r.ok is True, f"Expected ok=True when LTM available, got ok={r.ok}, warnings={r.warnings}"
        assert r.id, "ok=True but id is empty"
        assert r.backends.get("ltm") == "ok"
    else:
        assert r.ok is False
        assert r.backends.get("ltm") == "unavailable"


def test_record_feedback_ok_false_when_ltm_unavailable(tmp_path):
    """ok=False when LTM is not available."""
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem._ltm = None
    r = mem.record_feedback("m1", used=True)

    assert r.ok is False
    assert r.id == ""
    assert r.backends.get("ltm") == "unavailable"


def test_record_feedback_ok_false_when_ltm_write_fails(tmp_path, monkeypatch):
    """ok=False when LTM.add_entry() raises."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.long_term_memory import LongTermMemory

    def broken_add_entry(self, *a, **kw):
        raise RuntimeError("write fail")
    monkeypatch.setattr(LongTermMemory, "add_entry", broken_add_entry)

    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.record_feedback("m1", used=False)

    assert r.ok is False
    assert r.id == ""
    assert r.backends.get("ltm") == "degraded"
    assert len(r.warnings) > 0


def test_record_feedback_redacts_secrets(tmp_path):
    """Feedback must not store raw secrets in query or notes."""
    FAKE = "FAKE_SECRET_FEEDBACK_STRICT_NOTREAL"
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem.record_feedback("m1", used=True, query=f"token={FAKE}", notes=f"key={FAKE}")

    storage = tmp_path / ".igris"
    all_text = ""
    for f in storage.rglob("*.json"):
        try:
            all_text += f.read_text()
        except Exception:
            pass
    assert FAKE not in all_text, f"Raw secret '{FAKE}' found in storage after record_feedback"


# ─── mark_superseded strict tests ────────────────────────────────────────────

def test_mark_superseded_ok_true_when_ltm_writes(tmp_path):
    """ok=True when LTM writes successfully."""
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.mark_superseded("old_id", "new_id", reason="updated")

    if mem._ltm is not None:
        assert r.ok is True, f"Expected ok=True when LTM available, got {r.ok}"
        assert r.id
        assert r.backends.get("ltm") == "ok"
    else:
        assert r.ok is False


def test_mark_superseded_ok_false_when_ltm_unavailable(tmp_path):
    """ok=False when LTM is not available."""
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem._ltm = None
    r = mem.mark_superseded("old_id", "new_id")

    assert r.ok is False
    assert r.id == ""
    assert r.backends.get("ltm") == "unavailable"


def test_mark_superseded_ok_false_when_ltm_write_fails(tmp_path, monkeypatch):
    """ok=False when LTM.add_entry() raises."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.long_term_memory import LongTermMemory

    def broken_add_entry(self, *a, **kw):
        raise RuntimeError("ltm fail")
    monkeypatch.setattr(LongTermMemory, "add_entry", broken_add_entry)

    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.mark_superseded("old_id", "new_id")

    assert r.ok is False
    assert r.id == ""
    assert r.backends.get("ltm") == "degraded"
    assert len(r.warnings) > 0


# ─── forget strict tests ──────────────────────────────────────────────────────

def test_forget_ok_true_when_ltm_writes(tmp_path):
    """ok=True when LTM writes successfully."""
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.forget("some_memory_id")

    if mem._ltm is not None:
        assert r.ok is True, f"Expected ok=True when LTM available, got {r.ok}"
        assert r.id
        assert r.backends.get("ltm") == "ok"
    else:
        assert r.ok is False


def test_forget_ok_false_when_ltm_unavailable(tmp_path):
    """ok=False when LTM is not available."""
    from igris.core.unified_memory import UnifiedMemory
    mem = UnifiedMemory(project_root=tmp_path)
    mem._ltm = None
    r = mem.forget("some_memory_id")

    assert r.ok is False
    assert r.id == ""
    assert r.backends.get("ltm") == "unavailable"


def test_forget_ok_false_when_ltm_write_fails(tmp_path, monkeypatch):
    """ok=False when LTM.add_entry() raises."""
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.long_term_memory import LongTermMemory

    def broken_add_entry(self, *a, **kw):
        raise RuntimeError("write fail")
    monkeypatch.setattr(LongTermMemory, "add_entry", broken_add_entry)

    mem = UnifiedMemory(project_root=tmp_path)
    r = mem.forget("some_memory_id")

    assert r.ok is False
    assert r.id == ""
    assert r.backends.get("ltm") == "degraded"
    assert len(r.warnings) > 0
