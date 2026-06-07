"""Tests for Core Auth Models — #1272 PR 1.

Target: production-complete-progressive-interlocutor-auth-core-pr1
"""
from __future__ import annotations

import json
import time
import unittest.mock as mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cred_store(tmp_path, subdir="auth"):
    from igris.core.interlocutor_auth import AuthCredentialStore
    storage = tmp_path / subdir / "credentials.json"
    return AuthCredentialStore(project_root=tmp_path, storage_path=storage)


def _session_mgr(tmp_path, subdir="auth", ttl=28800, sliding=True):
    from igris.core.interlocutor_auth import AuthSessionManager
    storage = tmp_path / subdir / "sessions.json"
    return AuthSessionManager(
        project_root=tmp_path, storage_path=storage,
        ttl_seconds=ttl, sliding_window=sliding,
    )


# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_password_returns_salt_hash_iterations():
    from igris.core.interlocutor_auth import hash_password, PASSWORD_KDF, PASSWORD_ITERATIONS
    result = hash_password("SecurePass1")
    assert "password_hash" in result
    assert "password_salt" in result
    assert "password_kdf" in result
    assert "password_iterations" in result
    assert result["password_kdf"] == PASSWORD_KDF
    assert result["password_iterations"] == PASSWORD_ITERATIONS
    assert len(result["password_salt"]) > 0
    assert len(result["password_hash"]) > 0


def test_verify_password_ok():
    from igris.core.interlocutor_auth import hash_password, verify_password
    ph = hash_password("MyPassword1")
    assert verify_password("MyPassword1", ph["password_salt"], ph["password_hash"], ph["password_iterations"])


def test_verify_password_wrong_fails():
    from igris.core.interlocutor_auth import hash_password, verify_password
    ph = hash_password("MyPassword1")
    assert not verify_password("WrongPassword1", ph["password_salt"], ph["password_hash"], ph["password_iterations"])


def test_verify_password_constant_time_compare_used():
    """Verify that hmac.compare_digest is used (not == comparison)."""
    import igris.core.interlocutor_auth as auth_mod
    import hmac as hmac_mod
    called_with = []
    original = hmac_mod.compare_digest

    def _spy(a, b):
        called_with.append((a, b))
        return original(a, b)

    with mock.patch("igris.core.interlocutor_auth.hmac.compare_digest", side_effect=_spy):
        ph = auth_mod.hash_password("TestPass9")
        auth_mod.verify_password("TestPass9", ph["password_salt"], ph["password_hash"], ph["password_iterations"])

    assert len(called_with) >= 1


def test_password_raw_not_in_hash_result():
    from igris.core.interlocutor_auth import hash_password
    FAKE = "FAKE_PASSWORD_AUTH_1234567890"
    result = hash_password(FAKE)
    output = json.dumps(result)
    assert FAKE not in output


def test_weak_password_too_short_rejected(tmp_path):
    store = _cred_store(tmp_path)
    r = store.create_credential("u1", "e@e.com", "+391234567890", "Ab1")
    assert r.ok is False
    assert any("too_short" in e for e in r.errors)


def test_weak_password_no_digit_rejected(tmp_path):
    store = _cred_store(tmp_path)
    r = store.create_credential("u1", "e@e.com", "+391234567890", "NoDigitsHere")
    assert r.ok is False
    assert any("digit" in e for e in r.errors)


def test_weak_password_no_letter_rejected(tmp_path):
    store = _cred_store(tmp_path)
    r = store.create_credential("u1", "e@e.com", "+391234567890", "12345678")
    assert r.ok is False
    assert any("letter" in e for e in r.errors)


# ── AuthCredential ────────────────────────────────────────────────────────────

def test_auth_credential_to_dict_redacts_sensitive():
    from igris.core.interlocutor_auth import AuthCredential
    cred = AuthCredential(
        profile_id="mario",
        email="mario@example.com",
        mobile_phone="+393331234567",
        password_hash="fakehex",
        password_salt="fakesalt",
    )
    d = cred.to_dict(include_sensitive=False)
    assert "password_hash" not in d
    assert "password_salt" not in d
    assert "mario@example.com" not in d.get("email", "")
    assert "+393331234567" not in d.get("mobile_phone", "")


def test_auth_credential_storage_dict_includes_hash_not_raw_password():
    from igris.core.interlocutor_auth import AuthCredential
    cred = AuthCredential(
        profile_id="mario",
        email="mario@example.com",
        mobile_phone="+393331234567",
        password_hash="fakehex",
        password_salt="fakesalt",
    )
    d = cred.to_dict(include_sensitive=True)
    assert "password_hash" in d
    assert "password_salt" in d
    # raw password is never in any dict regardless
    FAKE = "FAKE_PASSWORD_AUTH_1234567890"
    output = json.dumps(d)
    assert FAKE not in output


def test_auth_credential_from_dict_roundtrip():
    from igris.core.interlocutor_auth import AuthCredential
    original = AuthCredential(
        profile_id="test_user",
        email="test@domain.it",
        mobile_phone="+391234567890",
        password_hash="abc123",
        password_salt="salt456",
        failed_login_count=2,
        locked=False,
    )
    d = original.to_dict(include_sensitive=True)
    restored = AuthCredential.from_dict(d)
    assert restored.profile_id == original.profile_id
    assert restored.password_hash == original.password_hash
    assert restored.password_salt == original.password_salt
    assert restored.failed_login_count == original.failed_login_count


def test_email_redaction():
    from igris.core.interlocutor_auth import redact_email
    assert "mario@example.com" not in redact_email("mario@example.com")
    assert "@example.com" in redact_email("mario@example.com")
    assert redact_email("m@x.it") == "m***@x.it"
    assert redact_email("") == "<REDACTED>"
    assert redact_email("invalid") == "<REDACTED>"


def test_phone_redaction():
    from igris.core.interlocutor_auth import redact_phone
    result = redact_phone("+393331234567")
    assert "+393331234567" not in result
    assert "4567" in result  # last 4 digits visible


# ── AuthCredentialStore ───────────────────────────────────────────────────────

def test_credential_store_initializes_missing_file(tmp_path):
    store = _cred_store(tmp_path)
    assert store is not None
    assert store.get_credential("anyone") is None


def test_create_credential_persists_to_disk(tmp_path):
    store = _cred_store(tmp_path)
    r = store.create_credential("mario", "mario@example.com", "+391234567890", "SecurePass1")
    assert r.ok is True, r.errors
    assert store.storage_path.exists()
    data = json.loads(store.storage_path.read_text())
    assert "mario" in data["credentials"]


def test_duplicate_credential_fails(tmp_path):
    store = _cred_store(tmp_path)
    store.create_credential("dup", "a@b.com", "+391234567890", "SecurePass1")
    r = store.create_credential("dup", "a@b.com", "+391234567890", "SecurePass1")
    assert r.ok is False
    assert any("already_exists" in e for e in r.errors)


def test_reload_restores_credentials(tmp_path):
    store1 = _cred_store(tmp_path)
    store1.create_credential("user1", "u@e.com", "+391234567890", "ValidPass1")

    from igris.core.interlocutor_auth import AuthCredentialStore
    store2 = AuthCredentialStore(project_root=tmp_path, storage_path=store1.storage_path)
    assert store2.get_credential("user1") is not None


def test_verify_login_success(tmp_path):
    store = _cred_store(tmp_path)
    store.create_credential("alice", "alice@example.com", "+391234567890", "AlicePass1")
    r = store.verify_login("alice", "AlicePass1")
    assert r.ok is True, r.errors


def test_verify_login_wrong_password_fails(tmp_path):
    store = _cred_store(tmp_path)
    store.create_credential("bob", "bob@example.com", "+391234567890", "BobPass1")
    r = store.verify_login("bob", "WrongPass1")
    assert r.ok is False
    assert any("invalid_credentials" in e for e in r.errors)


def test_failed_login_count_increments(tmp_path):
    store = _cred_store(tmp_path)
    store.create_credential("carol", "carol@example.com", "+391234567890", "CarolPass1")
    store.verify_login("carol", "WrongPass1")
    store.verify_login("carol", "WrongPass1")
    cred = store.get_credential("carol")
    assert cred.failed_login_count == 2


def test_account_locks_after_max_attempts(tmp_path):
    from igris.core.interlocutor_auth import MAX_FAILED_LOGIN_ATTEMPTS
    store = _cred_store(tmp_path)
    store.create_credential("dan", "dan@example.com", "+391234567890", "DanPass1")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        store.verify_login("dan", "WrongPass1")
    cred = store.get_credential("dan")
    assert cred.locked is True
    # Subsequent login with correct password still fails
    r = store.verify_login("dan", "DanPass1")
    assert r.ok is False
    assert any("locked" in e for e in r.errors)


def test_unlock_resets_locked_state(tmp_path):
    from igris.core.interlocutor_auth import MAX_FAILED_LOGIN_ATTEMPTS
    store = _cred_store(tmp_path)
    store.create_credential("eve", "eve@example.com", "+391234567890", "EvePass1")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        store.verify_login("eve", "WrongPass1")
    assert store.get_credential("eve").locked is True
    r = store.unlock("eve")
    assert r.ok is True
    cred = store.get_credential("eve")
    assert cred.locked is False
    assert cred.failed_login_count == 0
    # Now login succeeds
    r2 = store.verify_login("eve", "EvePass1")
    assert r2.ok is True


def test_invalid_json_reload_returns_ok_false(tmp_path):
    storage = tmp_path / "bad_creds.json"
    storage.write_text("{ not valid json", encoding="utf-8")
    from igris.core.interlocutor_auth import AuthCredentialStore
    store = AuthCredentialStore(project_root=tmp_path, storage_path=storage)
    r = store.reload()
    assert r.ok is False
    assert len(r.errors) > 0


def test_storage_write_failure_returns_ok_false(tmp_path):
    store = _cred_store(tmp_path)
    from igris.core.interlocutor_auth import AuthOperationResult

    def _bad_save():
        return AuthOperationResult(ok=False, action="save_credentials", errors=["simulated_disk_full"])

    with mock.patch.object(store, "save", side_effect=_bad_save):
        r = store.create_credential("fail_user", "f@f.com", "+391234567890", "FailPass1")
    assert r.ok is False
    assert len(r.errors) > 0


def test_no_raw_password_in_credentials_json(tmp_path):
    FAKE = "FAKE_PASSWORD_AUTH_1234567890"
    store = _cred_store(tmp_path)
    store.create_credential("sec1", "sec@example.com", "+391234567890", FAKE)
    raw = store.storage_path.read_text(encoding="utf-8")
    assert FAKE not in raw


def test_healthcheck_credentials(tmp_path):
    store = _cred_store(tmp_path)
    store.create_credential("hc1", "hc@example.com", "+391234567890", "HealthCheck1")
    h = store.healthcheck()
    assert h["ok"] is True
    assert h["count"] == 1
    assert "storage_path" in h


def test_unknown_profile_login_generic_error(tmp_path):
    """Login on unknown profile must return generic error (no user enumeration)."""
    store = _cred_store(tmp_path)
    r = store.verify_login("nonexistent", "SomePass1")
    assert r.ok is False
    assert any("invalid_credentials" in e for e in r.errors)
    # Must NOT say "user not found"
    assert not any("not_found" in e for e in r.errors)


# ── AuthSession ───────────────────────────────────────────────────────────────

def test_create_session_returns_token_once(tmp_path):
    mgr = _session_mgr(tmp_path)
    r = mgr.create_session("mario")
    assert r.ok is True
    assert r.session_token != ""
    assert len(r.session_token) > 16


def test_session_token_not_in_to_dict_by_default(tmp_path):
    mgr = _session_mgr(tmp_path)
    r = mgr.create_session("mario")
    d = r.to_dict(include_token=False)
    assert "session_token" not in d


def test_session_token_in_to_dict_when_requested(tmp_path):
    mgr = _session_mgr(tmp_path)
    r = mgr.create_session("mario")
    d = r.to_dict(include_token=True)
    assert "session_token" in d
    assert d["session_token"] == r.session_token


def test_session_storage_contains_hash_not_raw_token(tmp_path):
    mgr = _session_mgr(tmp_path)
    r = mgr.create_session("mario")
    raw_token = r.session_token
    raw_json = mgr.storage_path.read_text(encoding="utf-8")
    assert raw_token not in raw_json


def test_resolve_valid_session(tmp_path):
    mgr = _session_mgr(tmp_path)
    r = mgr.create_session("luigi")
    session, resolve_r = mgr.resolve_session(r.session_token)
    assert resolve_r.ok is True
    assert session is not None
    assert session.profile_id == "luigi"
    assert resolve_r.profile_id == "luigi"


def test_resolve_invalid_session_fails(tmp_path):
    mgr = _session_mgr(tmp_path)
    session, resolve_r = mgr.resolve_session("totally_invalid_token_xyz")
    assert resolve_r.ok is False
    assert session is None
    assert any("not_found" in e for e in resolve_r.errors)


def test_resolve_expired_session_fails(tmp_path):
    mgr = _session_mgr(tmp_path, ttl=1, sliding=False)
    r = mgr.create_session("expired_user")
    # Manually expire by patching expires_at
    token_hash = __import__("igris.core.interlocutor_auth", fromlist=["hash_session_token"]).hash_session_token(r.session_token)
    mgr._sessions[token_hash].expires_at = (
        datetime.now(tz=timezone.utc) - timedelta(seconds=10)
    ).isoformat()
    session, resolve_r = mgr.resolve_session(r.session_token)
    assert resolve_r.ok is False
    assert any("expired" in e for e in resolve_r.errors)


def test_revoke_session_blocks_resolution(tmp_path):
    mgr = _session_mgr(tmp_path)
    r = mgr.create_session("frank")
    revoke_r = mgr.revoke_session(r.session_token)
    assert revoke_r.ok is True
    session, resolve_r = mgr.resolve_session(r.session_token)
    assert resolve_r.ok is False
    assert any("revoked" in e for e in resolve_r.errors)


def test_revoke_all_for_profile(tmp_path):
    mgr = _session_mgr(tmp_path)
    r1 = mgr.create_session("grace")
    r2 = mgr.create_session("grace")
    r3 = mgr.create_session("other_user")
    revoke_r = mgr.revoke_all_for_profile("grace")
    assert revoke_r.ok is True
    assert revoke_r.metadata["revoked_count"] == 2
    _, rr1 = mgr.resolve_session(r1.session_token)
    _, rr2 = mgr.resolve_session(r2.session_token)
    assert rr1.ok is False
    assert rr2.ok is False
    # other user unaffected
    _, rr3 = mgr.resolve_session(r3.session_token)
    assert rr3.ok is True


def test_sliding_window_extends_expiry(tmp_path):
    mgr = _session_mgr(tmp_path, ttl=3600, sliding=True)
    r = mgr.create_session("slide_user")
    from igris.core.interlocutor_auth import hash_session_token, parse_iso
    token_hash = hash_session_token(r.session_token)
    # Manually set expires_at to near future
    mgr._sessions[token_hash].expires_at = (
        datetime.now(tz=timezone.utc) + timedelta(seconds=10)
    ).isoformat()
    mgr.save()
    session, rr = mgr.resolve_session(r.session_token)
    assert rr.ok is True
    new_expires = parse_iso(session.expires_at)
    # Should have been extended by ttl_seconds (~1h), not just 10s
    diff = (new_expires - datetime.now(tz=timezone.utc)).total_seconds()
    assert diff > 1800  # at least 30 min extension


def test_no_sliding_window_does_not_extend(tmp_path):
    mgr = _session_mgr(tmp_path, ttl=3600, sliding=False)
    r = mgr.create_session("noslide_user")
    from igris.core.interlocutor_auth import hash_session_token, parse_iso
    token_hash = hash_session_token(r.session_token)
    original_expires = mgr._sessions[token_hash].expires_at
    mgr.resolve_session(r.session_token)
    assert mgr._sessions[token_hash].expires_at == original_expires


def test_gc_expired_removes_expired(tmp_path):
    mgr = _session_mgr(tmp_path, ttl=3600)
    r1 = mgr.create_session("live_user")
    r2 = mgr.create_session("dead_user")
    # Manually expire r2
    from igris.core.interlocutor_auth import hash_session_token
    h2 = hash_session_token(r2.session_token)
    mgr._sessions[h2].expires_at = (
        datetime.now(tz=timezone.utc) - timedelta(seconds=10)
    ).isoformat()
    mgr.save()
    gc_r = mgr.gc_expired()
    assert gc_r.ok is True
    assert gc_r.metadata["removed_count"] == 1
    assert gc_r.metadata["remaining_count"] == 1


def test_invalid_json_sessions_reload_ok_false(tmp_path):
    storage = tmp_path / "bad_sessions.json"
    storage.write_text("not json at all", encoding="utf-8")
    from igris.core.interlocutor_auth import AuthSessionManager
    mgr = AuthSessionManager(project_root=tmp_path, storage_path=storage)
    r = mgr.reload()
    assert r.ok is False
    assert len(r.errors) > 0


def test_healthcheck_sessions(tmp_path):
    mgr = _session_mgr(tmp_path)
    mgr.create_session("hc_user")
    h = mgr.healthcheck()
    assert h["ok"] is True
    assert h["total_sessions"] == 1
    assert h["active_sessions"] == 1
    assert "storage_path" in h


# ── Global safety ─────────────────────────────────────────────────────────────

def test_no_raw_secret_in_operation_result(tmp_path):
    FAKE_P = "FAKE_PASSWORD_AUTH_1234567890"
    FAKE_T = "FAKE_TOKEN_AUTH_1234567890"
    from igris.core.interlocutor_auth import AuthOperationResult
    r = AuthOperationResult(
        ok=False, action="test",
        errors=[f"password={FAKE_P}", f"token={FAKE_T}"],
        metadata={"note": f"api_key=FAKE_API_KEY_AUTH_1234567890"},
    )
    output = json.dumps(r.to_dict())
    assert FAKE_P not in output
    assert FAKE_T not in output
    assert "FAKE_API_KEY_AUTH_1234567890" not in output


def test_no_raw_secret_in_credential_healthcheck(tmp_path):
    FAKE = "FAKE_PASSWORD_AUTH_1234567890"
    store = _cred_store(tmp_path)
    store.create_credential(
        f"sec_user",
        f"token={FAKE}@example.com",
        "+391234567890",
        "ValidPass1",
    )
    output = json.dumps(store.healthcheck())
    assert FAKE not in output


def test_no_raw_secret_in_session_healthcheck(tmp_path):
    FAKE = "FAKE_TOKEN_AUTH_1234567890"
    mgr = _session_mgr(tmp_path)
    r = mgr.create_session("safe_user")
    # token is only in result, not in healthcheck
    output = json.dumps(mgr.healthcheck())
    assert r.session_token not in output


def test_no_silent_except_credential_store(tmp_path):
    """Save failure must return ok=False with errors, not silently pass."""
    from igris.core.interlocutor_auth import AuthOperationResult
    store = _cred_store(tmp_path)

    def _bad_save():
        return AuthOperationResult(ok=False, action="save_credentials", errors=["boom"])

    with mock.patch.object(store, "save", side_effect=_bad_save):
        r = store.create_credential("noisy", "n@n.com", "+391234567890", "NoisePass1")

    assert r.ok is False
    assert len(r.errors) > 0


def test_no_silent_except_session_manager(tmp_path):
    """Session save failure must return ok=False with errors, not silently pass."""
    from igris.core.interlocutor_auth import AuthOperationResult
    mgr = _session_mgr(tmp_path)

    def _bad_save():
        return AuthOperationResult(ok=False, action="save_sessions", errors=["disk_full"])

    with mock.patch.object(mgr, "save", side_effect=_bad_save):
        r = mgr.create_session("noisy_session")

    assert r.ok is False
    assert len(r.errors) > 0


def test_no_external_calls():
    """interlocutor_auth.py must not import network libraries."""
    import igris.core.interlocutor_auth as mod
    import sys
    # Ensure no socket/requests/httpx/urllib top-level imports
    forbidden = {"socket", "requests", "httpx", "urllib.request", "smtplib", "ftplib"}
    loaded = set(sys.modules.keys())
    for lib in forbidden:
        # Only fail if the lib was loaded as a direct consequence of importing the module
        # We check module-level imports via source inspection instead
        pass
    # Source-level check
    import inspect
    src = inspect.getsource(mod)
    for lib in ("import requests", "import httpx", "import socket", "import smtplib"):
        assert lib not in src, f"Forbidden import found: {lib}"


# ── Functional smoke: end-to-end credential + session lifecycle ───────────────

def test_functional_smoke_credential_and_session(tmp_path):
    """Full smoke: create credential, login, create session, resolve, revoke."""
    from igris.core.interlocutor_auth import (
        AuthCredentialStore, AuthSessionManager, hash_session_token,
    )
    storage_creds = tmp_path / "auth" / "credentials.json"
    storage_sess = tmp_path / "auth" / "sessions.json"

    cred_store = AuthCredentialStore(project_root=tmp_path, storage_path=storage_creds)
    sess_mgr = AuthSessionManager(project_root=tmp_path, storage_path=storage_sess)

    # 1. Create credential
    r = cred_store.create_credential("mario_rossi", "mario@example.com", "+391234567890", "MarioSecure1")
    assert r.ok is True

    # 2. credentials.json exists and has hash, no raw password
    assert storage_creds.exists()
    raw_json = storage_creds.read_text()
    assert "MarioSecure1" not in raw_json
    assert "password_hash" in raw_json

    # 3. Verify login correct
    r_login = cred_store.verify_login("mario_rossi", "MarioSecure1")
    assert r_login.ok is True

    # 4. Verify login wrong increments count
    r_fail = cred_store.verify_login("mario_rossi", "WrongPass1")
    assert r_fail.ok is False
    assert cred_store.get_credential("mario_rossi").failed_login_count == 1

    # 5. Unlock
    from igris.core.interlocutor_auth import MAX_FAILED_LOGIN_ATTEMPTS
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        cred_store.verify_login("mario_rossi", "WrongPass1")
    assert cred_store.get_credential("mario_rossi").locked is True
    cred_store.unlock("mario_rossi")
    assert cred_store.get_credential("mario_rossi").locked is False

    # 6. Create session → raw token returned once
    sess_r = sess_mgr.create_session("mario_rossi")
    assert sess_r.ok is True
    raw_token = sess_r.session_token
    assert raw_token != ""

    # 7. sessions.json has token hash, not raw token
    assert storage_sess.exists()
    sess_json = storage_sess.read_text()
    assert raw_token not in sess_json
    assert hash_session_token(raw_token) in sess_json

    # 8. Resolve session
    session, rr = sess_mgr.resolve_session(raw_token)
    assert rr.ok is True
    assert session.profile_id == "mario_rossi"

    # 9. Revoke session → resolve fails
    rev_r = sess_mgr.revoke_session(raw_token)
    assert rev_r.ok is True
    session2, rr2 = sess_mgr.resolve_session(raw_token)
    assert rr2.ok is False
    assert session2 is None

    # 10. No raw fake secrets in metadata in storage
    FAKE_P = "FAKE_PASSWORD_AUTH_1234567890"
    r_sec = cred_store.create_credential("sec_user", "sec@x.com", "+391234567890", "SecUser1")
    assert r_sec.ok is True
    # Inject a secret pattern into metadata and verify it gets redacted in to_dict
    cred = cred_store.get_credential("sec_user")
    cred.metadata["note"] = f"password={FAKE_P}"
    cred_store.save()
    saved_json = storage_creds.read_text()
    assert FAKE_P not in saved_json
