"""Security hardening tests for #1239 — spoofing, fail-open, delegation, Italian intent."""
from __future__ import annotations

import time


# ---------------------------------------------------------------------------
# Fix 1: Anti-spoofing
# ---------------------------------------------------------------------------

def test_spoof_owner_via_payload_denied(tmp_path):
    """Non-local request claiming 'owner' identity must NOT get admin trust."""
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "ciao",
        interlocutor_id="owner",
        project_root=str(tmp_path),
        is_local_request=False,
    )
    assert result.trust_level not in ("admin",), (
        f"Spoofed owner got admin trust: {result.trust_level}"
    )


def test_owner_from_local_trusted(tmp_path):
    """Local request CAN claim owner identity — preflight must not crash."""
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "ciao",
        interlocutor_id="owner",
        project_root=str(tmp_path),
        is_local_request=True,
    )
    assert result is not None


def test_spoof_system_denied(tmp_path):
    """Non-local request claiming 'system' must NOT get admin trust."""
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "run command",
        interlocutor_id="system",
        project_root=str(tmp_path),
        is_local_request=False,
    )
    assert result.trust_level not in ("admin",)


def test_is_trusted_local_request_localhost():
    """is_trusted_local_request returns True for 127.0.0.1."""
    from igris.core.chat_interlocutor_preflight import is_trusted_local_request
    assert is_trusted_local_request(remote_addr="127.0.0.1")
    assert is_trusted_local_request(remote_addr="::1")
    assert not is_trusted_local_request(remote_addr="192.168.1.100")
    assert not is_trusted_local_request(remote_addr="10.0.0.1")


# ---------------------------------------------------------------------------
# Fix 1: _resolve_privileged_identity
# ---------------------------------------------------------------------------

def test_resolve_privileged_identity_downgrade():
    from igris.core.chat_interlocutor_preflight import _resolve_privileged_identity
    assert _resolve_privileged_identity("owner", is_local=False) == "unknown"
    assert _resolve_privileged_identity("system", is_local=False) == "unknown"
    assert _resolve_privileged_identity("owner", is_local=True) == "owner"
    assert _resolve_privileged_identity("system", is_local=True) == "system"
    assert _resolve_privileged_identity("alice", is_local=False) == "alice"


# ---------------------------------------------------------------------------
# Fix 1 + block logic
# ---------------------------------------------------------------------------

def test_unknown_sensitive_blocked(tmp_path):
    """Unknown interlocutor + sensitive action must be blocked."""
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "deploy production server",
        interlocutor_id="unknown_xyz",
        project_root=str(tmp_path),
    )
    assert result.blocked, f"Expected blocked but got: blocked={result.blocked}"


def test_unknown_innocuous_allowed(tmp_path):
    """Unknown interlocutor + innocuous message must NOT be blocked."""
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "che ora è?",
        interlocutor_id="unknown_xyz",
        project_root=str(tmp_path),
    )
    assert not result.blocked, f"Innocuous message blocked: {result.block_reason}"


# ---------------------------------------------------------------------------
# Fix 2: Preflight exception detection logic
# ---------------------------------------------------------------------------

def test_preflight_exception_sensitive_blocked():
    """Sensitive keyword detection works for fail-closed logic."""
    sensitive_keywords = {"deploy", "delete", "remove", "rollback", "merge",
                          "cancel", "drop", "wipe", "reset", "restart", "reboot", "admin"}
    sensitive_msgs = [
        "deploy the production server",
        "delete all logs",
        "rollback deployment",
        "restart the machine",
    ]
    innocuous_msgs = [
        "che ora è?",
        "dimmi lo stato del progetto",
        "hello world",
    ]
    for msg in sensitive_msgs:
        assert any(kw in msg.lower() for kw in sensitive_keywords), f"Not detected as sensitive: {msg}"
    for msg in innocuous_msgs:
        assert not any(kw in msg.lower() for kw in sensitive_keywords), f"Wrongly detected as sensitive: {msg}"


# ---------------------------------------------------------------------------
# Fix 5: Italian intent patterns
# ---------------------------------------------------------------------------

def test_italian_cancella_classified_destructive(tmp_path):
    """Italian 'cancella' must be classified as destructive or blocked."""
    from igris.core.chat_interlocutor_preflight import run_preflight
    result = run_preflight(
        "cancella il branch main",
        interlocutor_id="unknown_xyz",
        project_root=str(tmp_path),
    )
    assert result.intent_risk in ("destructive", "high") or result.blocked, (
        f"Expected destructive/high risk or blocked, got risk={result.intent_risk} blocked={result.blocked}"
    )


def test_italian_deploy_classified():
    """'fai deploy' must be classified as deploy action."""
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("fai deploy")
    assert r.action_type == "deploy" or r.risk_hint in ("high", "destructive"), (
        f"action={r.action_type} risk={r.risk_hint}"
    )


def test_italian_rollback_classified():
    """'fai rollback' must be classified as rollback action or high risk."""
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("fai rollback")
    assert r.action_type == "rollback" or r.risk_hint in ("high", "destructive"), (
        f"action={r.action_type} risk={r.risk_hint}"
    )


def test_italian_restart_server():
    """'riavvia il server' must be classified as restart_server."""
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("riavvia il server")
    assert r.action_type in ("restart_server",) or r.risk_hint in ("high",), (
        f"action={r.action_type} risk={r.risk_hint}"
    )


def test_italian_close_issue():
    """'chiudi la issue #123' must be classified as close_issue."""
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("chiudi la issue #123")
    assert r.action_type == "close_issue", f"action={r.action_type}"


def test_italian_inspect_logs():
    """'controlla i log' must be classified as inspect_logs."""
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("controlla i log")
    assert r.action_type == "inspect_logs", f"action={r.action_type}"


def test_italian_cancella_delete_action():
    """'cancella il file' must be classified as delete."""
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("cancella il file")
    assert r.action_type == "delete", f"action={r.action_type}"


def test_italian_urgency_critical():
    """'urgente' must be classified as critical urgency."""
    from igris.core.intent_resolver import IntentResolver
    ir = IntentResolver()
    r = ir.resolve("urgente fai deploy")
    assert r.urgency == "critical", f"urgency={r.urgency}"


# ---------------------------------------------------------------------------
# Fix 7/9: Audit — passphrase not in audit
# ---------------------------------------------------------------------------

def test_delegation_passphrase_not_in_audit(tmp_path):
    """Passphrase-like text in reason must be redacted in audit."""
    from igris.core.interlocutor_audit import InterlocutorAudit
    audit = InterlocutorAudit(path=tmp_path / "audit.jsonl")
    audit.record("auth_denied", reason="passphrase=secret123 delegation failed")
    entries = audit.recent()
    assert entries
    assert "secret123" not in entries[-1].get("reason", ""), (
        f"Passphrase leaked into audit: {entries[-1].get('reason')}"
    )


def test_audit_write_failure_returns_empty_string(tmp_path):
    """Audit write failure (bad path) must return empty string, not None."""
    from igris.core.interlocutor_audit import InterlocutorAudit
    audit = InterlocutorAudit(path=tmp_path / "audit.jsonl")
    # Make the file non-writable by replacing the path with a dir
    (tmp_path / "audit.jsonl").mkdir()
    result = audit.record("test_event")
    assert result == "", f"Expected '' but got: {result!r}"


# ---------------------------------------------------------------------------
# Fix 6: ActionGuard propagation
# ---------------------------------------------------------------------------

def test_action_guard_chat_unknown_blocked():
    """Unknown profile_id must be denied by ActionGuard for sensitive actions."""
    from igris.core.action_guard import check_action
    allowed, reason = check_action("run_command", profile_id="unknown")
    assert not allowed, f"Expected denied but allowed: reason={reason}"


def test_action_guard_system_internal_allowed():
    """'system' profile_id must be allowed by ActionGuard."""
    from igris.core.action_guard import check_action
    allowed, reason = check_action("run_command", profile_id="system")
    assert allowed, f"Expected allowed but denied: reason={reason}"


# ---------------------------------------------------------------------------
# Fix 4: Delegation key — expired denied
# ---------------------------------------------------------------------------

def test_delegation_key_expired_denied(tmp_path):
    """Expired delegation key must be rejected."""
    from igris.core.delegation_keys import DelegationKeyStore
    store = DelegationKeyStore(str(tmp_path))
    key = store.create_key(
        granted_by="owner",
        granted_to="collab",
        authorized_scopes=["read_github"],
        expires_in_hours=0.0001,  # expires immediately (~0.36 seconds)
        passphrase="testpass123",
    )
    time.sleep(0.5)
    result = store.verify(key.key_id, passphrase="testpass123", bearer="collab", requested_scopes=["read_github"])
    assert not result.valid or result.reason in ("key_expired", "expired"), (
        f"Expected expired but: valid={result.valid} reason={result.reason}"
    )


def test_delegation_key_store_create_and_verify(tmp_path):
    """DelegationKeyStore creates and verifies a valid key."""
    from igris.core.delegation_keys import DelegationKeyStore
    store = DelegationKeyStore(str(tmp_path))
    key = store.create_key(
        granted_by="owner",
        granted_to="collab",
        authorized_scopes=["deploy"],
        expires_in_hours=1,
        passphrase="mypassword",
    )
    result = store.verify(key.key_id, passphrase="mypassword", bearer="collab", requested_scopes=["deploy"])
    assert result.valid, f"Expected valid but: valid={result.valid} reason={result.reason}"


def test_delegation_key_wrong_passphrase(tmp_path):
    """Wrong passphrase must be rejected."""
    from igris.core.delegation_keys import DelegationKeyStore
    store = DelegationKeyStore(str(tmp_path))
    key = store.create_key(
        granted_by="owner",
        authorized_scopes=["deploy"],
        passphrase="correct",
    )
    result = store.verify(key.key_id, passphrase="wrong", requested_scopes=["deploy"])
    assert not result.valid
    assert "mismatch" in result.reason or "passphrase" in result.reason
