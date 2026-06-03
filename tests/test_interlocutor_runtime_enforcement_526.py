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
