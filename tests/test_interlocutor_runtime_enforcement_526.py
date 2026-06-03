"""Tests for action_guard runtime enforcement — issue #526."""
import pytest


@pytest.fixture(autouse=True)
def patch_root(tmp_path, monkeypatch):
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("igris.core.action_guard._PROJECT_ROOT", str(tmp_path))


def _setup_trusted(root, trust="trusted", scopes=None):
    from igris.core.identity_resolver import IdentityResolver
    ir = IdentityResolver(root)
    ir.create("alice", "Alice", trust_level=trust, authorized_scopes=scopes or ["deploy"])


def test_non_sensitive_always_allowed(tmp_path):
    from igris.core.action_guard import check_action
    allowed, reason = check_action("read_logs", "alice")
    assert allowed
    assert reason == "non-sensitive"


def test_unknown_interlocutor_denied(tmp_path):
    from igris.core.action_guard import check_action
    allowed, reason = check_action("deploy", "unknown_user")
    assert not allowed


def test_untrusted_denied(tmp_path):
    from igris.core.action_guard import check_action
    from igris.core.identity_resolver import IdentityResolver
    ir = IdentityResolver(str(tmp_path))
    ir.create("untrusted_bob", "Bob", trust_level="untrusted", authorized_scopes=[])
    # Untrusted profile → denied
    allowed, reason = check_action("deploy", "untrusted_bob")
    assert not allowed


def test_trusted_with_scope_allowed(tmp_path):
    _setup_trusted(str(tmp_path), trust="trusted", scopes=["deploy"])
    from igris.core.action_guard import check_action
    allowed, reason = check_action("deploy", "alice")
    assert allowed


def test_delegation_limited_scope(tmp_path):
    """A delegation key holder without direct scope still denied for other actions."""
    from igris.core.action_guard import check_action
    from igris.core.identity_resolver import IdentityResolver
    ir = IdentityResolver(str(tmp_path))
    ir.create("limited_user", "LimitedUser", trust_level="limited", authorized_scopes=["read"])
    allowed, _ = check_action("delete", "limited_user")
    assert not allowed


# ---------------------------------------------------------------------------
# New tests: runtime enforcement wiring (issue #526 production-complete)
# ---------------------------------------------------------------------------

def test_action_guard_callable_from_reasoning_loop(tmp_path):
    """ActionGuard is importable and reachable from the execution module."""
    # Verify the wiring exists: _guard_action must be present on the loop class
    from igris.core.agent_reasoning_loop import AgentReasoningLoop
    assert hasattr(AgentReasoningLoop, "_guard_action"), (
        "_guard_action must be wired into AgentReasoningLoop"
    )
    assert hasattr(AgentReasoningLoop, "_SENSITIVE_ACTION_MAP"), (
        "_SENSITIVE_ACTION_MAP must be defined on AgentReasoningLoop"
    )


def test_untrusted_blocked_on_sensitive_action(tmp_path):
    """Unknown/untrusted callers are blocked from sensitive ops."""
    from igris.core.action_guard import check_action
    allowed, reason = check_action("run_command", profile_id="unknown_external_user")
    assert not allowed
    assert "denied" in reason.lower() or "unknown" in reason.lower()


def test_authorized_profile_passes(tmp_path):
    """Built-in system profile is always allowed."""
    from igris.core.action_guard import check_action
    allowed, reason = check_action("run_command", profile_id="system")
    assert allowed, f"system profile must pass run_command, got: {reason}"


def test_denied_action_is_audited(tmp_path):
    """Denied actions are recorded in the audit log."""
    from igris.core.interlocutor_audit import InterlocutorAudit
    from igris.core.action_guard import check_action
    import os
    audit_path = tmp_path / "audit.jsonl"
    # Patch audit to write to tmp path
    import igris.core.interlocutor_audit as _audit_mod
    orig_init = _audit_mod.InterlocutorAudit.__init__

    def _patched_init(self, path=None):
        orig_init(self, path=str(audit_path))

    _audit_mod.InterlocutorAudit.__init__ = _patched_init
    try:
        allowed, _ = check_action("delete", profile_id="untrusted_user")
        assert not allowed
        import json
        entries = [json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
        event_types = {e.get("event_type") for e in entries}
        assert any("denied" in et or "unknown" in et for et in event_types), (
            f"Expected a denied audit entry, got: {event_types}"
        )
    finally:
        _audit_mod.InterlocutorAudit.__init__ = orig_init


def test_legacy_system_path_not_broken(tmp_path):
    """Internal system calls with profile_id=system must not be blocked."""
    from igris.core.action_guard import check_action
    for action in ["write_file", "edit_file", "run_command", "github_write"]:
        allowed, reason = check_action(action, profile_id="system")
        assert allowed, f"System profile must pass '{action}', got: {reason}"


def test_reasoning_loop_guard_blocks_untrusted(tmp_path, monkeypatch):
    """_guard_action on AgentReasoningLoop blocks untrusted interlocutor."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("igris.core.action_guard._PROJECT_ROOT", str(tmp_path))
    from igris.core.agent_reasoning_loop import AgentReasoningLoop
    loop = AgentReasoningLoop(project_root=str(tmp_path))
    loop.interlocutor_id = "unknown_external_user"
    allowed, reason = loop._guard_action("write_file")
    assert not allowed


def test_reasoning_loop_guard_allows_system(tmp_path, monkeypatch):
    """_guard_action falls back to system profile when no interlocutor is set."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("igris.core.action_guard._PROJECT_ROOT", str(tmp_path))
    from igris.core.agent_reasoning_loop import AgentReasoningLoop
    loop = AgentReasoningLoop(project_root=str(tmp_path))
    # No interlocutor_id set → defaults to "system" (trusted internal)
    assert not hasattr(loop, "interlocutor_id") or loop.interlocutor_id is None
    allowed, reason = loop._guard_action("write_file")
    assert allowed, f"Fallback system profile must allow write_file, got: {reason}"
