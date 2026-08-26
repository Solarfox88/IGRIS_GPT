"""E2E test: auth flow (#1328)."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_E2E_TESTS", "0") != "1",
    reason="Set IGRIS_E2E_TESTS=1 to run Playwright E2E tests",
)


def test_login_button_present(page) -> None:  # type: ignore[no-untyped-def]
    """Login/auth button should be present."""
    auth_btn = page.query_selector("#tb-auth-btn")
    assert auth_btn is not None


def test_enroll_button_present(page) -> None:  # type: ignore[no-untyped-def]
    """Enroll button should be present."""
    enroll_btn = page.query_selector("#tb-enroll-btn")
    assert enroll_btn is not None


def test_identity_display(page) -> None:  # type: ignore[no-untyped-def]
    """Identity display elements should be present."""
    identity = page.query_selector("#topbar-identity")
    assert identity is not None
