"""Tests for IdentityResolver — issue #526."""
import tempfile, os, pytest
from igris.core.identity_resolver import IdentityResolver, TRUST_LEVELS


@pytest.fixture()
def root(tmp_path):
    return str(tmp_path)


def test_resolve_unknown_returns_untrusted(root):
    ir = IdentityResolver(root)
    p = ir.resolve("ghost_user")
    assert p.trust_level == "untrusted"


def test_create_and_resolve(root):
    ir = IdentityResolver(root)
    ir.create("alice", "Alice", trust_level="trusted", authorized_scopes=["read"])
    p = ir.resolve("alice")
    assert p.display_name == "Alice"
    assert p.trust_level == "trusted"
    assert "read" in p.authorized_scopes


def test_grant_scope(root):
    ir = IdentityResolver(root)
    ir.create("bob", "Bob")
    ok = ir.grant_scope("bob", "deploy")
    assert ok
    assert "deploy" in ir.resolve("bob").authorized_scopes


def test_revoke_scope(root):
    ir = IdentityResolver(root)
    ir.create("carol", "Carol", authorized_scopes=["read", "write"])
    ir.revoke_scope("carol", "write")
    assert "write" not in ir.resolve("carol").authorized_scopes


def test_is_at_least(root):
    ir = IdentityResolver(root)
    ir.create("dave", "Dave", trust_level="trusted")
    p = ir.resolve("dave")
    assert p.is_at_least("limited")
    assert p.is_at_least("trusted")
    assert not p.is_at_least("admin")


def test_has_scope(root):
    ir = IdentityResolver(root)
    ir.create("eve", "Eve", authorized_scopes=["read_github"])
    p = ir.resolve("eve")
    assert p.has_scope("read_github")
    assert not p.has_scope("deploy")


def test_persist_to_memory_graph_nofail(root):
    ir = IdentityResolver(root)
    p = ir.create("frank", "Frank")
    ir.persist_to_memory_graph(p)  # must not raise


def test_deny_by_default_unknown(root):
    ir = IdentityResolver(root)
    p = ir.resolve("unknown_stranger")
    assert p.trust_level == "untrusted"
    assert not p.has_scope("deploy")
