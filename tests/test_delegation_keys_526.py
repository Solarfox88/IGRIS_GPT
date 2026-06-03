"""Tests for DelegationKey hardening — issue #526."""
import time
import pytest
from igris.core.delegation_keys import (
    create_key, verify_key, revoke_key, list_keys, DelegationKey
)


@pytest.fixture()
def root(tmp_path):
    return str(tmp_path)


def test_create_and_verify(root):
    key = create_key(root, "admin", ["read", "write"], ["read"], "pass1")
    ok, reason = verify_key(root, key.key_id, "pass1", ["read"])
    assert ok
    assert reason == "ok"


def test_wrong_passphrase(root):
    key = create_key(root, "admin", ["read"], ["read"], "correct")
    ok, reason = verify_key(root, key.key_id, "wrong", ["read"])
    assert not ok
    assert reason == "passphrase_mismatch"


def test_expired_key(root):
    key = create_key(root, "admin", ["read"], ["read"], "pass", expires_in_seconds=-1)
    ok, reason = verify_key(root, key.key_id, "pass", ["read"])
    assert not ok
    assert reason == "key_expired"


def test_single_use(root):
    key = create_key(root, "admin", ["read"], ["read"], "pass", single_use=True)
    ok1, _ = verify_key(root, key.key_id, "pass", ["read"])
    assert ok1
    ok2, reason = verify_key(root, key.key_id, "pass", ["read"])
    assert not ok2
    assert reason == "key_consumed"


def test_bearer_mismatch(root):
    key = create_key(root, "admin", ["read"], ["read"], "pass", granted_to="alice")
    ok, reason = verify_key(root, key.key_id, "pass", ["read"], bearer="bob")
    assert not ok
    assert reason == "bearer_mismatch"


def test_scope_inheritance_violation(root):
    with pytest.raises(ValueError, match="Scope inheritance violation"):
        create_key(root, "user", ["read"], ["deploy"], "pass")


def test_to_public_dict_no_secrets(root):
    key = create_key(root, "admin", ["read"], ["read"], "supersecret")
    pub = key.to_public_dict()
    assert "passphrase_hash" not in pub
    assert "salt" not in pub
    assert "supersecret" not in str(pub)
    assert "key_id" in pub


def test_revoke(root):
    key = create_key(root, "admin", ["read"], ["read"], "pass")
    ok = revoke_key(root, key.key_id)
    assert ok
    ok2, reason = verify_key(root, key.key_id, "pass", ["read"])
    assert not ok2
    assert reason == "key_not_found"


def test_list_keys(root):
    create_key(root, "admin", ["read"], ["read"], "p1")
    create_key(root, "bob", ["write"], ["write"], "p2")
    all_keys = list_keys(root)
    assert len(all_keys) == 2
    admin_keys = list_keys(root, granted_by="admin")
    assert len(admin_keys) == 1


def test_salted_hash_backward_compat():
    """Legacy plain SHA256 keys should still verify."""
    import hashlib
    legacy_hash = hashlib.sha256(b"oldpass").hexdigest()
    key = DelegationKey(
        key_id="legacy", passphrase_hash=legacy_hash, granted_by="admin",
        granted_to=None, authorized_scopes=["read"], expires_at=None,
        created_at=time.time(), salt=None
    )
    assert key.verify_passphrase("oldpass")
    assert not key.verify_passphrase("wrongpass")
