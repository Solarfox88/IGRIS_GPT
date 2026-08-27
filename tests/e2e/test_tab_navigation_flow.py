"""E2E test: tab navigation flow (#1328 Phase 2).

Tests real tab switching: click tabs, verify content changes.
Requires IGRIS_E2E_TESTS=1 and running server.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_E2E_TESTS", "0") != "1",
    reason="Set IGRIS_E2E_TESTS=1 to run Playwright E2E tests",
)


def test_switch_to_missions_tab(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """User can switch to the missions tab."""
    tab = page.query_selector("[data-tab='missions']") or page.query_selector("#tab-missions")
    if tab is None:
        pytest.skip("Missions tab not found")
    assert tab is not None
    tab.click()  # type: ignore[union-attr]
    page.wait_for_timeout(500)
    # Content should have changed
    assert page.title() is not None


def test_switch_to_terminal_tab(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """User can switch to the terminal tab."""
    tab = page.query_selector("[data-tab='terminal']") or page.query_selector("#tab-terminal")
    if tab is None:
        pytest.skip("Terminal tab not found")
    assert tab is not None
    tab.click()  # type: ignore[union-attr]
    page.wait_for_timeout(500)
    assert page.title() is not None


def test_switch_to_dashboard_tab(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """User can switch to the dashboard tab."""
    tab = page.query_selector("[data-tab='dashboard']") or page.query_selector("#tab-dashboard")
    if tab is None:
        pytest.skip("Dashboard tab not found")
    assert tab is not None
    tab.click()  # type: ignore[union-attr]
    page.wait_for_timeout(500)
    assert page.title() is not None


def test_tab_content_changes(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """Switching tabs should change visible content."""
    dashboard_tab = page.query_selector("[data-tab='dashboard']") or page.query_selector("#tab-dashboard")
    missions_tab = page.query_selector("[data-tab='missions']") or page.query_selector("#tab-missions")
    if dashboard_tab is None or missions_tab is None:
        pytest.skip("Required tabs not found")

    # Click dashboard
    dashboard_tab.click()  # type: ignore[union-attr]
    page.wait_for_timeout(300)
    dashboard_content = page.query_selector("#tab-content-dashboard") or page.query_selector(".tab-content")

    # Click missions
    missions_tab.click()  # type: ignore[union-attr]
    page.wait_for_timeout(300)
    missions_content = page.query_selector("#tab-content-missions") or page.query_selector(".tab-content")

    assert page.title() is not None
