"""Tests for igris/core/authorization_gate.py (issue #526)."""
from __future__ import annotations

import pytest

from igris.core.authorization_gate import AuthorizationGate
from igris.core.identity_resolver import InterlocutorProfile


def _profile(**kwargs):
    defaults = dict(
        profile_id="test_user",
        display_name="Test User",
        trust_level="limited",
        authorized_scopes=[],
        expertise_level="intermediate",
        communication_style="technical",
        persistent_flags={},
    )
    defaults.update(kwargs)
    return InterlocutorProfile(**defaults)


class TestAuthorizationGate:
    def test_admin_always_allowed(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="admin")
        result = gate.check(profile, "restart_server", "server_1")
        assert result.allowed is True
        assert result.reason == "admin_bypass"

    def test_admin_destructive_warns(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="admin")
        result = gate.check(profile, "delete_branch", "branch_x")
        assert result.allowed is True
        assert result.warn_destructive is True

    def test_scope_match_allows(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="trusted", authorized_scopes=["server_1"])
        result = gate.check(profile, "restart_server", "server_1")
        assert result.allowed is True
        assert result.reason == "scope_match"

    def test_wildcard_scope_allows(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="trusted", authorized_scopes=["*"])
        result = gate.check(profile, "restart_server", "any_server")
        assert result.allowed is True

    def test_no_scope_denies(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="limited", authorized_scopes=[])
        result = gate.check(profile, "restart_server", "server_1")
        assert result.allowed is False
        assert result.reason == "scope_denied"
        assert result.requires_delegation_key is True

    def test_untrusted_no_scope_denies(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="untrusted", authorized_scopes=[])
        result = gate.check(profile, "restart_server", "server_1")
        assert result.allowed is False

    def test_delegation_key_allows(self, tmp_path):
        from igris.core.delegation_keys import create_key, load_keys
        create_key(str(tmp_path), "christian", ["server_1"], ["server_1"], "secretpass",
                   granted_to="moglie")
        keys = load_keys(str(tmp_path))
        key_id = list(keys.keys())[0]

        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(profile_id="moglie", trust_level="limited", authorized_scopes=[])
        result = gate.check(
            profile, "restart_server", "server_1",
            delegation_key_id=key_id,
            delegation_key_passphrase="secretpass",
        )
        assert result.allowed is True
        assert result.reason == "delegation_key_accepted"

    def test_delegation_key_wrong_pass_denies(self, tmp_path):
        from igris.core.delegation_keys import create_key, load_keys
        create_key(str(tmp_path), "christian", ["server_1"], ["server_1"], "correctpass")
        keys = load_keys(str(tmp_path))
        key_id = list(keys.keys())[0]

        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="limited", authorized_scopes=[])
        result = gate.check(
            profile, "restart_server", "server_1",
            delegation_key_id=key_id,
            delegation_key_passphrase="wrongpass",
        )
        assert result.allowed is False

    def test_scope_match_destructive_warns(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="trusted", authorized_scopes=["server_1"])
        result = gate.check(profile, "delete_branch", "server_1")
        assert result.allowed is True
        assert result.warn_destructive is True

    def test_check_multiple_scopes(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="trusted", authorized_scopes=["server_1", "server_2"])
        result = gate.check_multiple_scopes(profile, ["server_1", "server_2", "server_3"])
        assert result["server_1"] is True
        assert result["server_2"] is True
        assert result["server_3"] is False

    def test_action_type_as_scope(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="trusted", authorized_scopes=["restart_server"])
        result = gate.check(profile, "restart_server", "some_server")
        assert result.allowed is True

    def test_no_scope_no_key_requires_delegation(self, tmp_path):
        gate = AuthorizationGate(str(tmp_path))
        profile = _profile(trust_level="trusted", authorized_scopes=["server_2"])
        result = gate.check(profile, "restart_server", "server_1")
        assert result.allowed is False
        assert result.requires_delegation_key is True
