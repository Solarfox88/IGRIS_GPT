"""Tests for AuthorizationGate — issue #526."""
import pytest
from igris.core.authorization_gate import AuthorizationGate
from igris.core.identity_resolver import InterlocutorProfile


def _profile(trust="untrusted", scopes=None):
    return InterlocutorProfile(
        profile_id="test_user", display_name="Test", trust_level=trust,
        authorized_scopes=scopes or []
    )


@pytest.fixture()
def gate(tmp_path):
    return AuthorizationGate(str(tmp_path))


def test_untrusted_denied(gate):
    r = gate.check(_profile("untrusted"), "deploy", "server")
    assert not r.allowed
    assert r.reason == "scope_denied"


def test_admin_bypass(gate):
    r = gate.check(_profile("admin"), "delete_branch", "main")
    assert r.allowed
    assert r.reason == "admin_bypass"


def test_scope_match_allowed(gate):
    r = gate.check(_profile("trusted", ["deploy"]), "deploy", "deploy")
    assert r.allowed
    assert r.reason == "scope_match"


def test_wildcard_scope(gate):
    r = gate.check(_profile("trusted", ["*"]), "any_action", "any_resource")
    assert r.allowed


def test_scope_denied_no_key(gate):
    r = gate.check(_profile("trusted", ["read"]), "write", "main")
    assert not r.allowed
    assert r.requires_delegation_key


def test_delegation_key_flow(tmp_path):
    from igris.core.delegation_keys import create_key
    gate = AuthorizationGate(str(tmp_path))
    key = create_key(
        project_root=str(tmp_path),
        granted_by="admin",
        grantor_scopes=["deploy"],
        authorized_scopes=["deploy"],
        raw_passphrase="secret123",
        granted_to="user1",
    )
    profile = InterlocutorProfile("user1", "User1", trust_level="limited", authorized_scopes=[])
    r = gate.check(profile, "deploy", "deploy",
                   delegation_key_id=key.key_id, delegation_key_passphrase="secret123")
    assert r.allowed
    assert r.reason == "delegation_key_accepted"


def test_delegation_key_wrong_passphrase(tmp_path):
    from igris.core.delegation_keys import create_key
    gate = AuthorizationGate(str(tmp_path))
    key = create_key(str(tmp_path), "admin", ["deploy"], ["deploy"], "correct", granted_to="u1")
    profile = InterlocutorProfile("u1", "U1", trust_level="limited", authorized_scopes=[])
    r = gate.check(profile, "deploy", "deploy",
                   delegation_key_id=key.key_id, delegation_key_passphrase="wrong")
    assert not r.allowed
