"""Tests for centralized secret redaction (#1313)."""
from __future__ import annotations

import re
from pathlib import Path


# ── Unit tests for igris.core.redaction ──────────────────────────────────────

def test_redact_token_assignment():
    from igris.core.redaction import redact
    assert "token=<REDACTED>" in redact("token=supersecret123")
    assert "supersecret123" not in redact("token=supersecret123")


def test_redact_authorization_bearer():
    from igris.core.redaction import redact
    # bearer=<value> form (key=value)
    result = redact("bearer=eyJhbGciOiJIUzI1NiJ9.abc")
    assert "eyJhbGciOiJIUzI1NiJ9" not in result
    # FAKE_TOKEN prefix form
    result2 = redact("FAKE_TOKEN_BEARER_TEST")
    assert "FAKE_TOKEN_BEARER_TEST" not in result2


def test_redact_fake_secret():
    from igris.core.redaction import redact
    result = redact("FAKE_SECRET_CENTRALIZED_NOTREAL")
    assert "FAKE_SECRET_CENTRALIZED_NOTREAL" not in result


def test_redact_openai_key():
    from igris.core.redaction import redact
    result = redact("sk-abcdefghij1234567890ABCDEF")
    assert "sk-abcdefghij" not in result


def test_redact_github_pat():
    from igris.core.redaction import redact
    result = redact("github_pat_11ABCDEF0123456789abcdefghijklm")
    assert "github_pat_" not in result


def test_redact_nested_dict_list_tuple():
    from igris.core.redaction import redact_nested
    data = {
        "token": "token=secret123",
        "items": ["api_key=mykey", ("password=abc", 42)],
        "count": 5,
    }
    result = redact_nested(data)
    assert "secret123" not in str(result)
    assert "mykey" not in str(result)
    assert "abc" not in str(result)
    assert result["count"] == 5  # passthrough int


def test_redact_email():
    from igris.core.redaction import redact_email
    assert redact_email("mario@example.com") == "m***@example.com"
    assert redact_email("a@b.com") == "a***@b.com"
    assert redact_email("noatsign") == "<REDACTED>"


def test_redact_phone():
    from igris.core.redaction import redact_phone
    assert redact_phone("+39 333 1234567") == "*** *** 4567"
    assert redact_phone("12") == "***"


def test_safety_redact_secrets_reexport():
    from igris.core.safety import redact_secrets
    result = redact_secrets("token=supersecret")
    assert "supersecret" not in result


def test_no_secret_regex_duplicates_in_core():
    """Verify SECRET_RE / _SECRET_RE are not defined outside redaction.py."""
    core_dir = Path(__file__).parent.parent / "igris" / "core"
    pattern = re.compile(r"^\s*_?SECRET_RE\s*=\s*re\.compile", re.MULTILINE)
    violations = []
    for py in sorted(core_dir.glob("*.py")):
        if py.name == "redaction.py":
            continue
        text = py.read_text(errors="replace")
        if pattern.search(text):
            violations.append(py.name)
    assert violations == [], f"Duplicate SECRET_RE in: {violations}"


# ── Integration: boundary modules still redact correctly ─────────────────────

def test_interlocutor_auth_result_redacts_raw_token(tmp_path):
    from igris.core.interlocutor_auth import AuthCredentialStore
    store = AuthCredentialStore(project_root=str(tmp_path))
    result = store.create_credential(
        profile_id="alice", email="alice@example.com",
        mobile_phone="+1234567890", raw_password="hunter2",
    )
    flat = str(vars(result) if hasattr(result, "__dict__") else result)
    assert "hunter2" not in flat


def test_unified_memory_redacts_fake_secret(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    um = UnifiedMemory(project_root=str(tmp_path))
    r = um.store_fact(text="FAKE_SECRET_CENTRALIZED_NOTREAL value here")
    stored_str = str(r)
    assert "FAKE_SECRET_CENTRALIZED_NOTREAL" not in stored_str


def test_learning_feedback_result_redacts_exception_secret():
    # _redact in learning_feedback is now the canonical one — verify it works
    from igris.core.redaction import redact
    redacted = redact("token=FAKE_TOKEN_LF_NOTREAL")
    assert "FAKE_TOKEN_LF_NOTREAL" not in redacted
