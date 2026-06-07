"""Tests for IdentityResolver extension — #1272 PR2.

Target: production-complete-progressive-interlocutor-auth-identity-pr2
Also covers backward compatibility with #526 tests.
"""
from __future__ import annotations

import json
import unittest.mock as mock
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ir(tmp_path):
    from igris.core.identity_resolver import IdentityResolver
    return IdentityResolver(str(tmp_path))


# ── InterlocutorProfile defaults ─────────────────────────────────────────────

def test_profile_defaults_are_conversational_unknown():
    from igris.core.identity_resolver import InterlocutorProfile
    p = InterlocutorProfile(profile_id="x", display_name="X")
    assert p.communication_style == "conversational"
    assert p.expertise_level == "unknown"
    assert p.trust_level == "untrusted"


def test_profile_includes_first_name_last_name():
    from igris.core.identity_resolver import InterlocutorProfile
    p = InterlocutorProfile(
        profile_id="mario", display_name="Mario Rossi",
        first_name="Mario", last_name="Rossi",
    )
    assert p.first_name == "Mario"
    assert p.last_name == "Rossi"


def test_profile_default_first_last_name_empty():
    from igris.core.identity_resolver import InterlocutorProfile
    p = InterlocutorProfile(profile_id="x", display_name="X")
    assert p.first_name == ""
    assert p.last_name == ""


def test_profile_to_dict_contains_first_last_name():
    from igris.core.identity_resolver import InterlocutorProfile
    p = InterlocutorProfile(
        profile_id="u", display_name="U",
        first_name="Luca", last_name="Bianchi",
    )
    d = p.to_dict()
    assert d["first_name"] == "Luca"
    assert d["last_name"] == "Bianchi"


# ── Constants ─────────────────────────────────────────────────────────────────

def test_comm_styles_includes_conversational():
    from igris.core.identity_resolver import COMM_STYLES
    assert "conversational" in COMM_STYLES


def test_expertise_levels_includes_unknown():
    from igris.core.identity_resolver import EXPERTISE_LEVELS
    assert "unknown" in EXPERTISE_LEVELS


def test_trust_levels_includes_limited():
    from igris.core.identity_resolver import TRUST_LEVELS
    assert "limited" in TRUST_LEVELS


# ── from_dict backward compatibility ─────────────────────────────────────────

def test_from_dict_backward_compatible_old_profile():
    """Old profile without first_name/last_name/new-defaults loads safely."""
    from igris.core.identity_resolver import InterlocutorProfile
    old = {
        "profile_id": "old_user",
        "display_name": "Old User",
        # no first_name, no last_name, no expertise_level, no communication_style
        "trust_level": "limited",
        "authorized_scopes": ["chat"],
        "persistent_flags": {},
        "delegation_keys": [],
        "interaction_count": 5,
        "first_seen_at": 1.0,
        "last_seen_at": 2.0,
    }
    p = InterlocutorProfile.from_dict(old)
    assert p.profile_id == "old_user"
    assert p.first_name == ""
    assert p.last_name == ""
    assert p.expertise_level == "unknown"    # default for missing
    assert p.communication_style == "conversational"  # default for missing
    assert p.trust_level == "limited"
    assert p.interaction_count == 5


def test_from_dict_preserves_existing_technical_intermediate():
    """Existing profiles with technical/intermediate style are preserved."""
    from igris.core.identity_resolver import InterlocutorProfile
    d = {
        "profile_id": "tech_user",
        "display_name": "Tech",
        "expertise_level": "intermediate",
        "communication_style": "technical",
        "trust_level": "trusted",
        "authorized_scopes": [],
        "persistent_flags": {},
        "delegation_keys": [],
        "interaction_count": 0,
        "first_seen_at": 1.0,
        "last_seen_at": 1.0,
    }
    p = InterlocutorProfile.from_dict(d)
    assert p.expertise_level == "intermediate"
    assert p.communication_style == "technical"


def test_invalid_expertise_normalizes_to_unknown():
    from igris.core.identity_resolver import InterlocutorProfile
    d = {
        "profile_id": "x", "display_name": "X",
        "expertise_level": "supergenius",  # invalid
        "communication_style": "technical",
        "trust_level": "untrusted",
        "authorized_scopes": [], "persistent_flags": {},
        "delegation_keys": [], "interaction_count": 0,
        "first_seen_at": 1.0, "last_seen_at": 1.0,
    }
    p = InterlocutorProfile.from_dict(d)
    assert p.expertise_level == "unknown"


def test_invalid_communication_style_normalizes_to_conversational():
    from igris.core.identity_resolver import InterlocutorProfile
    d = {
        "profile_id": "x", "display_name": "X",
        "expertise_level": "novice",
        "communication_style": "yolo",  # invalid
        "trust_level": "untrusted",
        "authorized_scopes": [], "persistent_flags": {},
        "delegation_keys": [], "interaction_count": 0,
        "first_seen_at": 1.0, "last_seen_at": 1.0,
    }
    p = InterlocutorProfile.from_dict(d)
    assert p.communication_style == "conversational"


def test_invalid_trust_normalizes_to_untrusted():
    from igris.core.identity_resolver import InterlocutorProfile
    d = {
        "profile_id": "x", "display_name": "X",
        "expertise_level": "novice",
        "communication_style": "casual",
        "trust_level": "god_mode",  # invalid
        "authorized_scopes": [], "persistent_flags": {},
        "delegation_keys": [], "interaction_count": 0,
        "first_seen_at": 1.0, "last_seen_at": 1.0,
    }
    p = InterlocutorProfile.from_dict(d)
    assert p.trust_level == "untrusted"


# ── Built-in profiles ─────────────────────────────────────────────────────────

def test_builtin_owner_has_first_last_name():
    from igris.core.identity_resolver import BUILTIN_PROFILES
    owner = BUILTIN_PROFILES["owner"]
    assert owner.first_name == "Christian"
    assert owner.last_name == "Ricci"
    assert owner.trust_level == "admin"


def test_builtin_system_has_first_last_name():
    from igris.core.identity_resolver import BUILTIN_PROFILES
    system = BUILTIN_PROFILES["system"]
    assert system.first_name == "IGRIS"
    assert system.last_name == "Internal"
    assert system.trust_level == "admin"


def test_builtin_owner_retains_technical_style():
    """Built-in owner keeps technical style — only new users get conversational."""
    from igris.core.identity_resolver import BUILTIN_PROFILES
    assert BUILTIN_PROFILES["owner"].communication_style == "technical"


# ── resolve() ─────────────────────────────────────────────────────────────────

def test_resolve_unknown_profile_uses_conversational_unknown(tmp_path):
    ir = _ir(tmp_path)
    p = ir.resolve("Mario Rossi")
    assert p.trust_level == "untrusted"
    assert p.communication_style == "conversational"
    assert p.expertise_level == "unknown"


def test_resolve_unknown_profile_not_persisted(tmp_path):
    """Unknown profile from resolve() must NOT be auto-saved to disk."""
    ir = _ir(tmp_path)
    ir.resolve("Ghost User")
    profiles_path = tmp_path / ".igris" / "interlocutor_profiles.json"
    if profiles_path.exists():
        data = json.loads(profiles_path.read_text())
        assert "ghost_user" not in data


def test_resolve_known_profile_returns_it(tmp_path):
    ir = _ir(tmp_path)
    ir.create("alice", "Alice", first_name="Alice", last_name="Rossi")
    p = ir.resolve("alice")
    assert p.display_name == "Alice"
    assert p.first_name == "Alice"


# ── create() ─────────────────────────────────────────────────────────────────

def test_create_profile_accepts_first_last_name(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create("mario", "Mario Rossi", first_name="Mario", last_name="Rossi")
    assert p.first_name == "Mario"
    assert p.last_name == "Rossi"
    # Persisted and reloadable
    ir2 = _ir(tmp_path)
    p2 = ir2.resolve("mario")
    assert p2.first_name == "Mario"
    assert p2.last_name == "Rossi"


def test_create_profile_normalizes_invalid_values(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create(
        "bad_enum", "BadEnum",
        trust_level="superadmin",       # invalid → untrusted
        expertise_level="wizard",       # invalid → unknown
        communication_style="yolo",     # invalid → conversational
    )
    assert p.trust_level == "untrusted"
    assert p.expertise_level == "unknown"
    assert p.communication_style == "conversational"


def test_create_profile_valid_scopes_persisted(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create("scoped", "Scoped", authorized_scopes=["chat", "memory_basic"])
    assert "chat" in p.authorized_scopes
    assert "memory_basic" in p.authorized_scopes


def test_create_profile_default_conversational_unknown(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create("new_user", "New User")
    assert p.communication_style == "conversational"
    assert p.expertise_level == "unknown"


# ── create_enrolled_limited_profile() ────────────────────────────────────────

def test_create_enrolled_limited_profile_defaults(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create_enrolled_limited_profile(
        profile_id="mario_rossi",
        first_name="Mario",
        last_name="Rossi",
    )
    assert p.trust_level == "limited"
    assert p.communication_style == "conversational"
    assert p.expertise_level == "unknown"
    assert "chat" in p.authorized_scopes
    assert "memory_basic" in p.authorized_scopes
    assert "read_own_profile" in p.authorized_scopes
    assert p.persistent_flags.get("enrolled") is True


def test_create_enrolled_limited_profile_no_dangerous_scopes(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create_enrolled_limited_profile("safe_user", "Safe", "User")
    dangerous = {"deploy", "delete", "merge", "github_write", "run_command",
                 "admin", "*", "restart_server"}
    for d in dangerous:
        assert d not in p.authorized_scopes, f"Dangerous scope {d!r} found"


def test_create_enrolled_limited_profile_persists(tmp_path):
    ir = _ir(tmp_path)
    ir.create_enrolled_limited_profile("luca", "Luca", "Bianchi")
    ir2 = _ir(tmp_path)
    p = ir2.resolve("luca")
    assert p.trust_level == "limited"
    assert p.first_name == "Luca"
    assert p.last_name == "Bianchi"
    assert p.persistent_flags.get("enrolled") is True


def test_create_enrolled_limited_profile_custom_display_name(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create_enrolled_limited_profile(
        "custom", "John", "Doe", display_name="JD"
    )
    assert p.display_name == "JD"


def test_create_enrolled_limited_profile_auto_display_name(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create_enrolled_limited_profile("auto_user", "Anna", "Verdi")
    assert "Anna" in p.display_name or "Verdi" in p.display_name


# ── get_all_including_builtins ────────────────────────────────────────────────

def test_get_all_including_builtins_includes_new_fields(tmp_path):
    ir = _ir(tmp_path)
    ir.create_enrolled_limited_profile("pp", "Paolo", "Pieri")
    all_profiles = ir.get_all_including_builtins()
    all_ids = {p.profile_id for p in all_profiles}
    assert "owner" in all_ids
    assert "system" in all_ids
    assert "pp" in all_ids
    # Verify fields present on enrolled profile
    pp = next(p for p in all_profiles if p.profile_id == "pp")
    assert pp.first_name == "Paolo"
    assert pp.trust_level == "limited"


# ── persist_to_memory_graph silent except removed ─────────────────────────────

def test_persist_to_memory_graph_no_silent_except(tmp_path):
    """persist_to_memory_graph must log the exception, not silently pass."""
    ir = _ir(tmp_path)
    p = ir.create("frank", "Frank")
    log_calls = []

    with mock.patch("igris.core.identity_resolver.logger") as mock_logger:
        with mock.patch(
            "igris.core.identity_resolver.MemoryGraph",
            side_effect=RuntimeError("mem_graph_unavailable"),
        ) if False else mock.patch(
            "igris.core.memory_graph.MemoryGraph.__init__",
            side_effect=RuntimeError("mem_graph_unavailable"),
        ):
            pass  # Inner mock not always reachable; use module-level patch

    # Simpler: patch importlib so MemoryGraph raises
    import unittest.mock as mock_mod
    with mock_mod.patch.dict(
        "sys.modules",
        {"igris.core.memory_graph": mock_mod.MagicMock(
            MemoryGraph=mock_mod.MagicMock(side_effect=RuntimeError("forced_failure"))
        )},
    ):
        with mock_mod.patch("igris.core.identity_resolver.logger") as mock_logger:
            ir.persist_to_memory_graph(p)
            # Must have called logger.debug or logger.warning, NOT silently pass
            called = mock_logger.debug.called or mock_logger.warning.called
            assert called, "persist_to_memory_graph must log the exception"


# ── Reload/persistence round-trip ─────────────────────────────────────────────

def test_reload_restores_first_last_name(tmp_path):
    ir = _ir(tmp_path)
    ir.create("roundtrip", "Roundtrip User", first_name="Round", last_name="Trip")
    ir2 = _ir(tmp_path)
    p = ir2.resolve("roundtrip")
    assert p.first_name == "Round"
    assert p.last_name == "Trip"


def test_reload_restores_enrolled_profile(tmp_path):
    ir = _ir(tmp_path)
    ir.create_enrolled_limited_profile("enrolled_rt", "Enr", "Olled")
    ir2 = _ir(tmp_path)
    p = ir2.resolve("enrolled_rt")
    assert p.trust_level == "limited"
    assert p.expertise_level == "unknown"
    assert p.communication_style == "conversational"
    assert p.persistent_flags.get("enrolled") is True


# ── Security invariants ───────────────────────────────────────────────────────

def test_resolve_unknown_remains_untrusted(tmp_path):
    """resolve() on unknown user must always return untrusted."""
    ir = _ir(tmp_path)
    p = ir.resolve("hacker")
    assert p.trust_level == "untrusted"
    assert "deploy" not in p.authorized_scopes
    assert "*" not in p.authorized_scopes


def test_no_password_in_profile():
    """InterlocutorProfile must never contain password fields."""
    from igris.core.identity_resolver import InterlocutorProfile
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(InterlocutorProfile)}
    for forbidden in ("password", "password_hash", "password_salt",
                      "email", "mobile_phone", "session_token"):
        assert forbidden not in field_names, f"Forbidden field {forbidden!r} in InterlocutorProfile"


def test_enrolled_limited_never_admin(tmp_path):
    ir = _ir(tmp_path)
    p = ir.create_enrolled_limited_profile("test_admin_check", "Test", "User")
    assert p.trust_level != "admin"
    assert p.trust_level != "trusted"
    assert p.trust_level == "limited"


# ── Backward compat: existing #526 tests coverage ────────────────────────────

def test_resolve_unknown_returns_untrusted_526(tmp_path):
    ir = _ir(tmp_path)
    p = ir.resolve("ghost_user")
    assert p.trust_level == "untrusted"


def test_create_and_resolve_526(tmp_path):
    ir = _ir(tmp_path)
    ir.create("alice_526", "Alice", trust_level="trusted", authorized_scopes=["read"])
    p = ir.resolve("alice_526")
    assert p.display_name == "Alice"
    assert p.trust_level == "trusted"
    assert "read" in p.authorized_scopes


def test_grant_scope_526(tmp_path):
    ir = _ir(tmp_path)
    ir.create("bob_526", "Bob")
    ok = ir.grant_scope("bob_526", "deploy")
    assert ok
    assert "deploy" in ir.resolve("bob_526").authorized_scopes


def test_revoke_scope_526(tmp_path):
    ir = _ir(tmp_path)
    ir.create("carol_526", "Carol", authorized_scopes=["read", "write"])
    ir.revoke_scope("carol_526", "write")
    assert "write" not in ir.resolve("carol_526").authorized_scopes


def test_is_at_least_526(tmp_path):
    ir = _ir(tmp_path)
    ir.create("dave_526", "Dave", trust_level="trusted")
    p = ir.resolve("dave_526")
    assert p.is_at_least("limited")
    assert p.is_at_least("trusted")
    assert not p.is_at_least("admin")


def test_has_scope_526(tmp_path):
    ir = _ir(tmp_path)
    ir.create("eve_526", "Eve", authorized_scopes=["read_github"])
    p = ir.resolve("eve_526")
    assert p.has_scope("read_github")
    assert not p.has_scope("deploy")
