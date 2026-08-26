"""E2E test: dashboard and navigation (#1328)."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_E2E_TESTS", "0") != "1",
    reason="Set IGRIS_E2E_TESTS=1 to run Playwright E2E tests",
)


def test_dashboard_tab_present(page) -> None:  # type: ignore[no-untyped-def]
    """Dashboard tab should be present."""
    dashboard = page.query_selector("[data-tab='dashboard']") or page.query_selector("#tab-dashboard")
    assert dashboard is not None


def test_missions_tab_present(page) -> None:  # type: ignore[no-untyped-def]
    """Missions tab should be present."""
    missions = page.query_selector("[data-tab='missions']") or page.query_selector("#tab-missions")
    assert missions is not None


def test_terminal_tab_present(page) -> None:  # type: ignore[no-untyped-def]
    """Terminal tab should be present."""
    terminal = page.query_selector("[data-tab='terminal']") or page.query_selector("#tab-terminal")
    assert terminal is not None


def test_status_panel_present(page) -> None:  # type: ignore[no-untyped-def]
    """Status panel should be present."""
    status = page.query_selector("#status-panel") or page.query_selector(".status-panel")
    assert status is not None
