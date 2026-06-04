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
