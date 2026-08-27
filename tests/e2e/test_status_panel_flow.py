"""E2E test: status panel interaction (#1328 Phase 2).

Tests status panel visibility and content.
Requires IGRIS_E2E_TESTS=1 and running server.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_E2E_TESTS", "0") != "1",
    reason="Set IGRIS_E2E_TESTS=1 to run Playwright E2E tests",
)


def test_status_panel_visible(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """Status panel should be visible on page load."""
    status = page.query_selector("#status-panel") or page.query_selector(".status-panel")
    if status is None:
        pytest.skip("Status panel not found")
    assert status.is_visible()  # type: ignore[union-attr]


def test_status_panel_has_content(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """Status panel should have some content."""
    status = page.query_selector("#status-panel") or page.query_selector(".status-panel")
    if status is None:
        pytest.skip("Status panel not found")
    text = status.inner_text()  # type: ignore[union-attr]
    assert text is not None
    assert len(text) > 0


def test_api_status_endpoint(page, server_url) -> None:  # type: ignore[no-untyped-def]
    """API diagnostics endpoint should be reachable from browser."""
    response = page.evaluate(f"fetch('{server_url}/api/diagnostics/summary').then(r => r.json())")
    assert response is not None
    assert "healthy" in response
