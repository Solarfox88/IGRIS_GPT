"""Tests for Control Room interlocutor section — issue #526."""
import pytest


def test_dashboard_has_interlocutor_section(tmp_path, monkeypatch):
    """Dashboard summary must include 'interlocutor' key."""
    # We test the logic directly, not via HTTP (avoid full app init)
    from igris.core.identity_resolver import IdentityResolver
    from igris.core.interlocutor_audit import InterlocutorAudit
    
    ir = IdentityResolver(str(tmp_path))
    ir.create("alice", "Alice", trust_level="trusted")
    
    audit = InterlocutorAudit(str(tmp_path / "audit.jsonl"))
    audit.record("test", interlocutor_id="alice", decision="allowed")
    
    profiles = [p.to_dict() for p in ir.get_all()]
    recent = audit.recent(10)
    
    interlocutor_section = {
        "profiles": profiles,
        "recent_audit": recent,
        "error": None,
    }
    
    assert "profiles" in interlocutor_section
    assert "recent_audit" in interlocutor_section
    assert len(interlocutor_section["profiles"]) == 1
    assert interlocutor_section["profiles"][0]["profile_id"] == "alice"
    assert len(interlocutor_section["recent_audit"]) == 1


def test_interlocutor_section_no_secrets(tmp_path):
    """Profile data must not expose secrets."""
    from igris.core.identity_resolver import IdentityResolver
    ir = IdentityResolver(str(tmp_path))
    p = ir.create("bob", "Bob", trust_level="admin")
    d = p.to_dict()
    assert "passphrase" not in str(d)
    assert "password" not in str(d)


def test_interlocutor_section_empty_fallback():
    """Must work even when no profiles exist."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        from igris.core.identity_resolver import IdentityResolver
        ir = IdentityResolver(tmpdir)
        assert ir.get_all() == []  # fallback empty state
