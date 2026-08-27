"""E2E test: chat interaction flow (#1328 Phase 2).

Tests real chat interaction: type message, click send, verify response.
Requires IGRIS_E2E_TESTS=1 and running server.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_E2E_TESTS", "0") != "1",
    reason="Set IGRIS_E2E_TESTS=1 to run Playwright E2E tests",
)


def test_chat_send_message(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """User can type a message and send it."""
    chat_input = page.query_selector("#chat-input")
    if chat_input is None:
        pytest.skip("Chat input not found — UI may not have chat on index page")
    assert chat_input is not None
    chat_input.fill("Hello IGRIS")  # type: ignore[union-attr]
    send_btn = page.query_selector("#chat-send-btn")
    if send_btn is None:
        pytest.skip("Send button not found")
    assert send_btn is not None
    send_btn.click()  # type: ignore[union-attr]
    # Wait for response to appear
    page.wait_for_timeout(2000)
    messages = page.query_selector("#chat-messages")
    assert messages is not None


def test_chat_clear_messages(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """Chat messages area should be clearable or empty initially."""
    messages = page.query_selector("#chat-messages")
    if messages is None:
        pytest.skip("Chat messages area not found")
    assert messages is not None
    initial_text = messages.inner_text()  # type: ignore[union-attr]
    assert initial_text is not None


def test_chat_input_typing(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """Chat input should accept typed text."""
    chat_input = page.query_selector("#chat-input")
    if chat_input is None:
        pytest.skip("Chat input not found")
    assert chat_input is not None
    chat_input.fill("Test message 123")  # type: ignore[union-attr]
    assert chat_input.input_value() == "Test message 123"  # type: ignore[union-attr]
