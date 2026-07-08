"""Tests for PR-3 of epic #1301: InterlocutorAudit explicit project_root wiring.

Verifies:
- InterlocutorAudit accepts project_root and writes to the correct .igris path
- run_preflight passes project_root to the audit (audit file lands under project_root)
- Audit log format unchanged (JSONL with required fields, no raw tokens)
- No raw token written to audit log
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── 1. InterlocutorAudit constructor: project_root parameter ─────────────────

def test_audit_writes_to_explicit_project_root(tmp_path):
    """InterlocutorAudit(project_root=...) must write to project_root/.igris/."""
    from igris.core.interlocutor_audit import InterlocutorAudit

    audit = InterlocutorAudit(project_root=str(tmp_path))
    expected = tmp_path / ".igris" / "interlocutor_audit.jsonl"
    assert audit.path == expected


def test_audit_path_param_takes_precedence_over_project_root(tmp_path):
    """Explicit path= overrides project_root when both are given."""
    from igris.core.interlocutor_audit import InterlocutorAudit

    explicit = tmp_path / "custom" / "audit.jsonl"
    audit = InterlocutorAudit(path=str(explicit), project_root=str(tmp_path / "other"))
    assert audit.path == explicit


def test_audit_falls_back_to_config_igris_dir_when_no_project_root(monkeypatch, tmp_path):
    """Without project_root, audit must fall back to CONFIG.igris_dir."""
    import igris.models.config as cfg_mod
    monkeypatch.setattr(cfg_mod.CONFIG, "project_root", tmp_path)

    from igris.core.interlocutor_audit import InterlocutorAudit
    audit = InterlocutorAudit()
    assert audit.path == tmp_path / ".igris" / "interlocutor_audit.jsonl"


def test_audit_creates_parent_directories(tmp_path):
    """InterlocutorAudit must create missing parent directories on init."""
    from igris.core.interlocutor_audit import InterlocutorAudit

    audit = InterlocutorAudit(project_root=str(tmp_path / "nonexistent"))
    assert audit.path.parent.exists()


# ── 2. Audit log format and content ──────────────────────────────────────────

def test_audit_record_writes_jsonl_entry(tmp_path):
    """record() must write a parseable JSONL line with required fields."""
    from igris.core.interlocutor_audit import InterlocutorAudit

    audit = InterlocutorAudit(project_root=str(tmp_path))
    event_id = audit.record(
        event_type="identity_resolved",
        interlocutor_id="testuser",
        display_name="Test User",
        trust_level="limited",
        action_type="chat",
        target_resource="chat",
        decision="allowed",
        reason="test",
    )
    assert event_id, "record() must return a non-empty event_id"
    lines = audit.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event_type"] == "identity_resolved"
    assert entry["interlocutor_id"] == "testuser"
    assert "ts" in entry
    assert "event_id" in entry


def test_audit_record_api_has_no_session_token_param(tmp_path):
    """InterlocutorAudit.record() must not accept a session_token parameter.

    The record() signature is the enforcement boundary: if it has no session_token
    param, raw tokens cannot leak into the audit log via normal call paths.
    """
    import inspect
    from igris.core.interlocutor_audit import InterlocutorAudit

    sig = inspect.signature(InterlocutorAudit.record)
    param_names = list(sig.parameters.keys())
    assert "session_token" not in param_names, (
        "record() must not accept session_token — raw tokens must never be persisted"
    )
    assert "token" not in param_names, (
        "record() must not accept token parameter"
    )


def test_audit_redacts_sensitive_fields_in_reason(tmp_path):
    """Sensitive keywords in reason string must be redacted."""
    from igris.core.interlocutor_audit import InterlocutorAudit

    audit = InterlocutorAudit(project_root=str(tmp_path))
    audit.record(
        event_type="auth_denied",
        interlocutor_id="user",
        display_name="User",
        trust_level="untrusted",
        action_type="chat",
        target_resource="chat",
        decision="denied",
        reason="token=secret_value_12345",
    )
    content = audit.path.read_text(encoding="utf-8")
    assert "secret_value_12345" not in content


# ── 3. run_preflight wires project_root to audit ─────────────────────────────

def test_run_preflight_audit_lands_in_project_root(monkeypatch, tmp_path):
    """run_preflight(project_root=tmp_path) must write audit to tmp_path/.igris/."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from igris.core.chat_interlocutor_preflight import run_preflight

    run_preflight(
        message="ciao",
        interlocutor_id="owner",
        project_root=str(tmp_path),
        is_local_request=True,
    )

    audit_file = tmp_path / ".igris" / "interlocutor_audit.jsonl"
    assert audit_file.exists(), (
        f"Audit file not found under project_root ({tmp_path}). "
        "run_preflight must pass project_root to InterlocutorAudit."
    )


def test_run_preflight_audit_does_not_land_in_home(monkeypatch, tmp_path):
    """run_preflight must NOT write audit to Path.home()/.igris/."""
    import os
    monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path / "project"))

    from igris.core.chat_interlocutor_preflight import run_preflight

    run_preflight(
        message="ciao",
        interlocutor_id="owner",
        project_root=str(tmp_path / "project"),
        is_local_request=True,
    )

    home_audit = tmp_path / "fake_home" / ".igris" / "interlocutor_audit.jsonl"
    assert not home_audit.exists(), (
        "Audit file written to HOME/.igris — run_preflight must use project_root, not Path.home()"
    )


def test_run_preflight_audit_format_unchanged(monkeypatch, tmp_path):
    """Audit JSONL format from run_preflight must contain expected fields."""
    monkeypatch.setenv("IGRIS_PROJECT_ROOT", str(tmp_path))

    from igris.core.chat_interlocutor_preflight import run_preflight

    run_preflight(
        message="test message",
        interlocutor_id="owner",
        project_root=str(tmp_path),
        is_local_request=True,
    )

    audit_file = tmp_path / ".igris" / "interlocutor_audit.jsonl"
    if audit_file.exists():
        for line in audit_file.read_text(encoding="utf-8").strip().splitlines():
            entry = json.loads(line)
            assert "event_type" in entry
            assert "interlocutor_id" in entry
            assert "ts" in entry
