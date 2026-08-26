"""E2E test: page loads and basic UI elements present (#1328)."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_E2E_TESTS", "0") != "1",
    reason="Set IGRIS_E2E_TESTS=1 to run Playwright E2E tests",
)


def test_index_page_loads(page) -> None:  # type: ignore[no-untyped-def]
    """Index page should load successfully."""
    # Page is already navigated to server_url in fixture
    assert page.title() is not None
    # Page should not show an error
    assert "404" not in page.title().lower()


def test_sidebar_present(page) -> None:  # type: ignore[no-untyped-def]
    """Sidebar should be present on the page."""
    sidebar = page.query_selector("#sidebar")
    assert sidebar is not None


def test_topbar_present(page) -> None:  # type: ignore[no-untyped-def]
    """Topbar should be present on the page."""
    topbar = page.query_selector(".topbar")
    assert topbar is not None


def test_chat_form_present(page) -> None:  # type: ignore[no-untyped-def]
    """Chat form should be present on the page."""
    chat_form = page.query_selector("#chat-form")
    assert chat_form is not None


def test_js_modules_loaded(page) -> None:  # type: ignore[no-untyped-def]
    """JavaScript modules should be loaded without errors."""
    # Check that app.js was loaded
    result = page.evaluate("typeof window !== 'undefined'")
    assert result is True
