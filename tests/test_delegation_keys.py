"""Tests for igris/core/delegation_keys.py (issue #526)."""
from __future__ import annotations

import time

import pytest

from igris.core.delegation_keys import (
    DelegationKey,
    create_key,
    list_keys,
    load_keys,
    revoke_key,
    verify_key,
)


class TestDelegationKeyDataclass:
    def test_is_expired_no_expiry(self):
        k = DelegationKey(
            key_id="k1", passphrase_hash="h", granted_by="christian",
            granted_to=None, authorized_scopes=["server_1"],
            expires_at=None, created_at=time.time(),
        )
        assert k.is_expired() is False

    def test_is_expired_past(self):
        k = DelegationKey(
            key_id="k1", passphrase_hash="h", granted_by="christian",
            granted_to=None, authorized_scopes=["server_1"],
            expires_at=time.time() - 1, created_at=time.time() - 10,
        )
        assert k.is_expired() is True

    def test_is_valid_single_use_consumed(self):
        k = DelegationKey(
            key_id="k1", passphrase_hash="h", granted_by="christian",
            granted_to=None, authorized_scopes=["server_1"],
            expires_at=None, created_at=time.time(),
            single_use=True, used=True,
        )
        assert k.is_valid() is False

    def test_is_valid_not_consumed(self):
        k = DelegationKey(
            key_id="k1", passphrase_hash="h", granted_by="christian",
            granted_to=None, authorized_scopes=["server_1"],
            expires_at=None, created_at=time.time(),
            single_use=True, used=False,
        )
        assert k.is_valid() is True

    def test_verify_passphrase_correct(self, tmp_path):
        key = create_key(
            str(tmp_path), "christian", ["server_1"], ["server_1"], "mysecret"
        )
        assert key.verify_passphrase("mysecret") is True

    def test_verify_passphrase_wrong(self, tmp_path):
        key = create_key(
            str(tmp_path), "christian", ["server_1"], ["server_1"], "mysecret"
        )
        assert key.verify_passphrase("wrongpassword") is False


class TestCreateKey:
    def test_creates_and_saves_key(self, tmp_path):
        key = create_key(str(tmp_path), "christian", ["server_1"], ["server_1"], "secret")
        loaded = load_keys(str(tmp_path))
        assert key.key_id in loaded

    def test_scope_inheritance_violation_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Scope inheritance violation"):
            create_key(
                str(tmp_path), "christian", ["server_1"],
                ["server_1", "server_2"],
                "secret",
            )

    def test_with_expiry(self, tmp_path):
        key = create_key(
            str(tmp_path), "christian", ["server_1"], ["server_1"], "secret",
            expires_in_seconds=3600,
        )
        assert key.expires_at is not None
        assert key.expires_at > time.time()

    def test_single_use_flag(self, tmp_path):
        key = create_key(
            str(tmp_path), "christian", ["server_1"], ["server_1"], "secret",
            single_use=True,
        )
        assert key.single_use is True
        assert key.used is False


class TestVerifyKey:
    def test_valid_key_accepted(self, tmp_path):
        key = create_key(str(tmp_path), "christian", ["server_1"], ["server_1"], "secret")
        ok, reason = verify_key(str(tmp_path), key.key_id, "secret", ["server_1"])
        assert ok is True
        assert reason == "ok"

    def test_wrong_passphrase_rejected(self, tmp_path):
        key = create_key(str(tmp_path), "christian", ["server_1"], ["server_1"], "secret")
        ok, reason = verify_key(str(tmp_path), key.key_id, "WRONG", ["server_1"])
        assert ok is False
        assert "passphrase" in reason

    def test_unknown_key_rejected(self, tmp_path):
        ok, reason = verify_key(str(tmp_path), "nonexistent", "secret", ["server_1"])
        assert ok is False
        assert "not_found" in reason

    def test_expired_key_rejected(self, tmp_path):
        key = create_key(
            str(tmp_path), "christian", ["server_1"], ["server_1"], "secret",
            expires_in_seconds=-10,
        )
        ok, reason = verify_key(str(tmp_path), key.key_id, "secret", ["server_1"])
        assert ok is False
        assert "expired" in reason

    def test_scope_not_covered_rejected(self, tmp_path):
        key = create_key(str(tmp_path), "christian", ["server_1"], ["server_1"], "secret")
        ok, reason = verify_key(str(tmp_path), key.key_id, "secret", ["server_2"])
        assert ok is False
        assert "scope_not_covered" in reason

    def test_single_use_key_consumed_on_verify(self, tmp_path):
        key = create_key(
            str(tmp_path), "christian", ["server_1"], ["server_1"], "secret",
            single_use=True,
        )
        ok1, _ = verify_key(str(tmp_path), key.key_id, "secret", ["server_1"])
        ok2, reason = verify_key(str(tmp_path), key.key_id, "secret", ["server_1"])
        assert ok1 is True
        assert ok2 is False
        assert "consumed" in reason

    def test_bearer_mismatch_rejected(self, tmp_path):
        key = create_key(
            str(tmp_path), "christian", ["server_1"], ["server_1"], "secret",
            granted_to="moglie",
        )
        ok, reason = verify_key(
            str(tmp_path), key.key_id, "secret", ["server_1"], bearer="other_user"
        )
        assert ok is False
        assert "bearer" in reason


class TestRevokeKey:
    def test_revoke_existing_key(self, tmp_path):
        key = create_key(str(tmp_path), "christian", ["server_1"], ["server_1"], "secret")
        assert revoke_key(str(tmp_path), key.key_id) is True
        keys = load_keys(str(tmp_path))
        assert key.key_id not in keys

    def test_revoke_nonexistent_returns_false(self, tmp_path):
        assert revoke_key(str(tmp_path), "nonexistent") is False


class TestListKeys:
    def test_list_all(self, tmp_path):
        k1 = create_key(str(tmp_path), "christian", ["s1"], ["s1"], "p1")
        k2 = create_key(str(tmp_path), "christian", ["s1"], ["s1"], "p2")
        keys = list_keys(str(tmp_path))
        ids = [k.key_id for k in keys]
        assert k1.key_id in ids
        assert k2.key_id in ids

    def test_list_by_grantor(self, tmp_path):
        create_key(str(tmp_path), "christian", ["s1"], ["s1"], "p1")
        keys = list_keys(str(tmp_path), granted_by="christian")
        assert all(k.granted_by == "christian" for k in keys)
