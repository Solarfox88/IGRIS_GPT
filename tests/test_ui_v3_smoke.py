"""UI v3 smoke tests — verify new structural elements are present."""
import os


def _read(path):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base, path), encoding="utf-8") as f:
        return f.read()


def test_index_html_has_topbar():
    html = _read("igris/web/templates/index.html")
    assert "topbar" in html
    assert "topbar-brand" in html


def test_index_html_has_status_panel():
    html = _read("igris/web/templates/index.html")
    assert "status-panel" in html
    assert "sp-interlocutor" in html
    assert "sp-rank" in html
    assert "sp-audit" in html
    assert "sp-ci" in html


def test_index_html_has_chat_input():
    html = _read("igris/web/templates/index.html")
    assert "chat-input" in html
    assert "chat-input-box" in html or "chat-input" in html


def test_index_html_has_hint_chips():
    html = _read("igris/web/templates/index.html")
    assert "hint-chip" in html


def test_index_html_has_sidebar_sections():
    html = _read("igris/web/templates/index.html")
    assert "sidebar-section" in html
    assert "sidebar-label" in html


def test_index_html_keeps_all_tabs():
    html = _read("igris/web/templates/index.html")
    for tab in ("tab-dashboard", "tab-code", "tab-tasks", "tab-terminal", "tab-memory", "tab-safety", "tab-advanced"):
        assert tab in html, f"Missing tab pane: {tab}"


def test_css_has_topbar():
    css = _read("igris/web/static/css/style.css")
    assert ".topbar" in css
    assert "topbar-brand" in css


def test_css_has_status_panel():
    css = _read("igris/web/static/css/style.css")
    assert ".status-panel" in css
    assert ".status-section" in css


def test_css_has_hint_chip():
    css = _read("igris/web/static/css/style.css")
    assert "hint-chip" in css


def test_css_has_advisory_style():
    css = _read("igris/web/static/css/style.css")
    assert "advisory" in css
    assert "intent-strip" in css


def test_css_has_chat_input_box():
    css = _read("igris/web/static/css/style.css")
    assert "chat-input-box" in css


def test_js_has_status_panel_loader():
    js = _read("igris/web/static/js/app.js")
    assert "loadStatusPanel" in js
    assert "sp-interlocutor-content" in js
    assert "sp-rank-content" in js


def test_js_has_hint_chips():
    js = _read("igris/web/static/js/app.js")
    assert "hint-chip" in js


def test_js_has_textarea_handler():
    js = _read("igris/web/static/js/app.js")
    assert "TEXTAREA" in js or "textarea" in js
