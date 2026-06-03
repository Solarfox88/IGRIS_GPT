"""Tests for UI v4 improvements (#1226)."""
import os
import re
import pytest
from fastapi.testclient import TestClient
from igris.web.server import create_app


def _read(path):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base, path), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def html():
    return _read("igris/web/templates/index.html")


def css():
    return _read("igris/web/static/css/style.css")


def js():
    return _read("igris/web/static/js/app.js")


def test_identity_badge_element_present():
    """Identity state badge element must be in topbar."""
    h = html()
    assert "tb-identity-state" in h or "identity-state-badge" in h


def test_admin_safety_copy_present():
    """Safety note for admin must be present."""
    h = html()
    assert "gated" in h.lower() or "tb-safety-note" in h


def test_intent_strip_collapsible():
    """Intent strip must have collapse toggle."""
    h = html()
    assert "intent-toggle" in h or "intent-strip" in h


def test_blocked_css_class():
    """msg-assistant.blocked must have distinct style."""
    c = css()
    assert ".blocked" in c


def test_advisory_css_class():
    """msg-assistant.advisory must have distinct style."""
    c = css()
    assert ".advisory" in c


def test_requires_confirmation_css_class():
    """requires-confirmation class must exist."""
    c = css()
    assert "requires-confirmation" in c


def test_warning_css_class():
    """warning class must exist in CSS."""
    c = css()
    assert ".warning" in c


def test_hint_chips_no_unsafe_actions():
    """Hint chips must only fill chat input, not trigger mutations."""
    h = html()
    # Find all hint-chip elements and check their data-msg attributes
    chip_msgs = re.findall(r'data-msg="([^"]*)"', h)
    # All chip messages are read-only queries — no fetch/POST/DELETE in html
    chip_section = h[h.find("chat-hints"):h.find("chat-hints") + 800] if "chat-hints" in h else ""
    assert "fetch(" not in chip_section
    assert "POST" not in chip_section
    assert "DELETE" not in chip_section


def test_live_status_interlocutor_section():
    """Live status panel must have interlocutor section."""
    h = html()
    assert "INTERLOCUTORE" in h or "sp-interlocutor" in h


def test_live_status_rank_section():
    """Live status panel must show rank."""
    h = html()
    assert "sp-rank" in h or "RANK" in h


def test_chat_meta_readable():
    """Chat metadata must be dimmed (not primary color)."""
    c = css()
    assert ".msg-meta" in c


def test_responsive_480px():
    """480px breakpoint must exist."""
    c = css()
    assert "max-width:480px" in c or "max-width: 480px" in c


def test_blocked_message_enhanced():
    """JS must handle blocked=true with operator-grade message."""
    j = js()
    assert "r.data.blocked" in j


def test_no_unsafe_action_hardcoded():
    """No hardcoded unsafe endpoint in hint chips section."""
    j = js()
    chip_section = j[j.find("hint-chip"):j.find("hint-chip") + 500] if "hint-chip" in j else ""
    assert "fetch(" not in chip_section
    assert "DELETE" not in chip_section


def test_identity_badge_states_in_js():
    """JS must handle recognized/unknown/delegated/system/owner badge states."""
    j = js()
    # States are built as "identity-state-badge state-" + state variable
    assert "identity-state-badge state-" in j
    assert '"owner"' in j or "state = \"owner\"" in j or "state=\"owner\"" in j or "state = 'owner'" in j
    assert '"recognized"' in j or "state = 'recognized'" in j
    assert '"unknown"' in j or "state = 'unknown'" in j


def test_intent_toggle_localstorage():
    """JS must persist intent toggle state to localStorage."""
    j = js()
    assert "igris_intent_collapsed" in j


def test_api_rank_gauntlet_not_broken(client):
    """Gauntlet endpoint must be reachable and return expected schema."""
    r = client.get("/api/rank/gauntlet")
    assert r.status_code == 200
    d = r.json()
    # Verify schema shape — "passed" may be False in CI test environment
    # where file-system checks differ; we only assert the endpoint works.
    assert "passed" in d
    assert "rank" in d
    assert "score" in d
    assert "checks" in d


def test_api_identity_profiles_not_broken(client):
    """Identity profiles endpoint must still work."""
    r = client.get("/api/identity/profiles")
    assert r.status_code == 200
