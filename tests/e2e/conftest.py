"""Playwright E2E test fixtures (#1328).

Shared fixtures for E2E tests: browser launch, page navigation, server URL.
"""
from __future__ import annotations

import os
import socket
from typing import Any, Generator

import pytest

# Gate: skip all E2E tests unless IGRIS_E2E_TESTS=1
pytestmark = pytest.mark.skipif(
    os.environ.get("IGRIS_E2E_TESTS", "0") != "1",
    reason="Set IGRIS_E2E_TESTS=1 to run Playwright E2E tests",
)

E2E_SERVER_URL = os.environ.get("IGRIS_E2E_URL", "http://127.0.0.1:7778")


def _is_server_running(url: str = E2E_SERVER_URL) -> bool:
    """Check if the IGRIS server is running."""
    try:
        host = "127.0.0.1"
        port = 7778
        if ":" in url.split("//")[1]:
            host, port_str = url.split("//")[1].split(":")
            port = int(port_str)
        with socket.create_connection((host, port), timeout=2):
            return True
    except (OSError, socket.timeout, IndexError):
        return False


@pytest.fixture(scope="session")
def server_url() -> str:
    """Return the E2E server URL, skip if server not running."""
    if not _is_server_running():
        pytest.skip(f"IGRIS server not running at {E2E_SERVER_URL}")
    return E2E_SERVER_URL


@pytest.fixture(scope="session")
def browser() -> Generator[Any, None, None]:
    """Launch a Playwright browser."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright not installed. Install with: pip install playwright && playwright install")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser: Any, server_url: str) -> Generator[Any, None, None]:
    """Create a new page for each test."""
    context = browser.new_context()
    page = context.new_page()
    page.goto(server_url)
    yield page
    context.close()
