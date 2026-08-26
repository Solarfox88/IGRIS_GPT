"""E2E test: chat interaction (#1328)."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_E2E_TESTS", "0") != "1",
    reason="Set IGRIS_E2E_TESTS=1 to run Playwright E2E tests",
)


def test_chat_input_present(page) -> None:  # type: ignore[no-untyped-def]
    """Chat input should be present."""
    chat_input = page.query_selector("#chat-input")
    assert chat_input is not None


def test_chat_send_button_present(page) -> None:  # type: ignore[no-untyped-def]
    """Chat send button should be present."""
    send_btn = page.query_selector("#chat-send-btn")
    assert send_btn is not None


def test_chat_messages_area(page) -> None:  # type: ignore[no-untyped-def]
    """Chat messages area should be present."""
    messages = page.query_selector("#chat-messages")
    assert messages is not None
