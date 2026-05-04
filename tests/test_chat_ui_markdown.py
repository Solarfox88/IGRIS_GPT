"""Tests for Sprint 32 — Readable Chat UI and Markdown Rendering.

Verifies:
- HTML escaping (no XSS)
- CSS classes exist for chat rendering
- No horizontal overflow regression
- Mobile CSS still works
- Provider metadata displayed compactly
- Chat panel structure correct
"""

import pytest
from httpx import AsyncClient, ASGITransport
from pathlib import Path

from igris.web.server import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# CSS Structure Tests
# ---------------------------------------------------------------------------

class TestCSSStructure:
    """Verify CSS has required chat classes."""

    @pytest.fixture(autouse=True)
    def load_css(self):
        css_path = Path(__file__).parent.parent / "igris" / "web" / "static" / "css" / "style.css"
        self.css = css_path.read_text()

    def test_chat_panel_wider(self):
        assert "width:480px" in self.css or "width: 480px" in self.css

    def test_chat_panel_max_width(self):
        assert "max-width:50vw" in self.css or "max-width: 50vw" in self.css

    def test_msg_assistant_paragraph(self):
        assert ".msg-assistant p" in self.css

    def test_msg_assistant_code(self):
        assert ".msg-assistant code" in self.css

    def test_msg_assistant_pre(self):
        assert ".msg-assistant pre" in self.css

    def test_msg_assistant_strong(self):
        assert ".msg-assistant strong" in self.css

    def test_msg_assistant_list(self):
        assert ".msg-assistant ul" in self.css or ".msg-assistant ol" in self.css

    def test_msg_meta_class(self):
        assert ".msg-meta" in self.css

    def test_meta_provider_class(self):
        assert ".meta-provider" in self.css

    def test_copy_button_class(self):
        assert ".copy-btn" in self.css

    def test_no_horizontal_overflow(self):
        assert "overflow-wrap:break-word" in self.css or "word-wrap:break-word" in self.css

    def test_mobile_responsive(self):
        assert "@media(max-width:768px)" in self.css
        assert "@media(max-width:480px)" in self.css

    def test_mobile_chat_panel(self):
        assert "height:40vh" in self.css or "height: 40vh" in self.css

    def test_scroll_behavior(self):
        assert "scroll-behavior:smooth" in self.css or "scroll-behavior: smooth" in self.css

    def test_line_height_readable(self):
        assert "line-height:1.6" in self.css or "line-height: 1.6" in self.css


# ---------------------------------------------------------------------------
# JavaScript Markdown Renderer Tests
# ---------------------------------------------------------------------------

class TestJSMarkdownRenderer:
    """Verify JS has safe markdown rendering."""

    @pytest.fixture(autouse=True)
    def load_js(self):
        js_path = Path(__file__).parent.parent / "igris" / "web" / "static" / "js" / "app.js"
        self.js = js_path.read_text()

    def test_has_render_markdown_function(self):
        assert "renderMarkdown" in self.js

    def test_escapes_html(self):
        # Must escape < and > before rendering
        assert '&amp;' in self.js and '&lt;' in self.js and '&gt;' in self.js

    def test_renders_code_blocks(self):
        assert "```" in self.js
        assert "<pre>" in self.js
        assert "<code" in self.js

    def test_renders_inline_code(self):
        assert "`" in self.js and "<code>" in self.js

    def test_renders_bold(self):
        assert "**" in self.js and "<strong>" in self.js

    def test_renders_bullet_list(self):
        assert "<ul>" in self.js and "<li>" in self.js

    def test_renders_numbered_list(self):
        assert "<ol>" in self.js

    def test_copy_button_exists(self):
        assert "igrisCopyCode" in self.js
        assert "copy-btn" in self.js

    def test_no_raw_innerhtml_from_user(self):
        # User messages should use textContent, not innerHTML
        # Check that user messages are handled safely
        assert "d.textContent = text" in self.js

    def test_auto_scroll_logic(self):
        assert "userNearBottom" in self.js
        assert "scrollHeight" in self.js

    def test_metadata_compact_display(self):
        assert "msg-meta" in self.js
        assert "meta-provider" in self.js

    def test_no_script_injection_possible(self):
        # HTML is escaped before any rendering
        lines = self.js.split('\n')
        render_section = False
        for line in lines:
            if 'renderMarkdown' in line and 'function' in line:
                render_section = True
            if render_section and 'replace(/</g' in line:
                # Found HTML escaping
                break
        else:
            if render_section:
                pytest.fail("renderMarkdown should escape HTML tags")


# ---------------------------------------------------------------------------
# HTML Template Tests
# ---------------------------------------------------------------------------

class TestHTMLTemplate:
    """Verify HTML template has proper chat structure."""

    @pytest.fixture(autouse=True)
    def load_html(self):
        html_path = Path(__file__).parent.parent / "igris" / "web" / "templates" / "index.html"
        self.html = html_path.read_text()

    def test_chat_panel_exists(self):
        assert 'class="chat-panel"' in self.html

    def test_chat_messages_container(self):
        assert 'id="chat-messages"' in self.html
        assert 'class="chat-messages"' in self.html

    def test_chat_form_exists(self):
        assert 'id="chat-form"' in self.html

    def test_chat_input_exists(self):
        assert 'id="chat-input"' in self.html

    def test_no_inline_scripts(self):
        # No onclick in template (scripts in separate file)
        assert 'onclick=' not in self.html


# ---------------------------------------------------------------------------
# API Integration Tests
# ---------------------------------------------------------------------------

class TestChatAPIWithMarkdown:
    """Chat API returns content suitable for markdown rendering."""

    @pytest.mark.anyio
    async def test_chat_response_has_newlines(self, client):
        """IGRIS personality responses contain structured text with newlines."""
        resp = await client.post("/api/chat/intent", json={"message": "cosa puoi fare?"})
        assert resp.status_code == 200
        data = resp.json()
        # Response should have newlines for proper rendering
        assert "\n" in data["grounded_response"]

    @pytest.mark.anyio
    async def test_chat_response_has_bullets(self, client):
        """Machine info response has bullet-like content."""
        resp = await client.post("/api/chat/intent", json={"message": "dammi info sulla macchina"})
        data = resp.json()
        assert "- " in data["grounded_response"]

    @pytest.mark.anyio
    async def test_chat_response_no_html_injection(self, client):
        """Responses don't contain raw HTML that could be injected."""
        resp = await client.post("/api/chat/intent", json={"message": "cosa puoi fare?"})
        data = resp.json()
        text = data["grounded_response"]
        assert "<script>" not in text
        assert "onclick=" not in text
        assert "javascript:" not in text

    @pytest.mark.anyio
    async def test_chat_capabilities_response_length(self, client):
        """All responses are bounded for readability."""
        for msg in ["dammi info sulla macchina", "cosa puoi fare?", "riesci a vedere il mio GitHub?"]:
            resp = await client.post("/api/chat/intent", json={"message": msg})
            data = resp.json()
            if data["grounded_response"]:
                assert len(data["grounded_response"]) < 1500

    @pytest.mark.anyio
    async def test_ui_loads_without_error(self, client):
        """Main page loads successfully."""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "IGRIS_GPT" in resp.text
        assert "chat-messages" in resp.text
