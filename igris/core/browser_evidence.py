"""Browser/UI smoke evidence with optional Playwright and test-friendly fakes."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class BrowserSmokeResult:
    ok: bool
    degraded: bool = False
    url: str = ""
    selector: str = "body"
    selector_found: Optional[bool] = None
    screenshot_path: str = ""
    screenshot_metadata: Dict[str, Any] = field(default_factory=dict)
    console_errors: List[str] = field(default_factory=list)
    network_errors: List[str] = field(default_factory=list)
    error: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BrowserRunner(ABC):
    @abstractmethod
    def run_smoke(
        self,
        *,
        url: str,
        selector: str = "body",
        artifact_dir: Optional[str] = None,
    ) -> BrowserSmokeResult:
        pass


class FakeBrowserRunner(BrowserRunner):
    """Deterministic in-memory browser runner for tests."""

    def __init__(
        self,
        *,
        selector_found: bool = True,
        console_errors: Optional[List[str]] = None,
        network_errors: Optional[List[str]] = None,
        forced_error: str = "",
    ) -> None:
        self.selector_found = selector_found
        self.console_errors = list(console_errors or [])
        self.network_errors = list(network_errors or [])
        self.forced_error = forced_error

    def run_smoke(
        self,
        *,
        url: str,
        selector: str = "body",
        artifact_dir: Optional[str] = None,
    ) -> BrowserSmokeResult:
        if self.forced_error:
            return BrowserSmokeResult(
                ok=False,
                degraded=True,
                url=url,
                selector=selector,
                error=self.forced_error,
            )
        artifact = Path(artifact_dir or ".") / "fake_browser_screenshot.png"
        return BrowserSmokeResult(
            ok=self.selector_found and not self.console_errors and not self.network_errors,
            degraded=False,
            url=url,
            selector=selector,
            selector_found=self.selector_found,
            screenshot_path=str(artifact),
            screenshot_metadata={"fake": True, "format": "png", "bytes": 0},
            console_errors=self.console_errors,
            network_errors=self.network_errors,
        )


class PlaywrightBrowserRunner(BrowserRunner):
    """Optional Playwright-backed runner; raises if Playwright is unavailable."""

    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"playwright_unavailable: {exc}") from exc
        self._sync_playwright = sync_playwright

    def run_smoke(
        self,
        *,
        url: str,
        selector: str = "body",
        artifact_dir: Optional[str] = None,
    ) -> BrowserSmokeResult:
        console_errors: List[str] = []
        network_errors: List[str] = []
        out_dir = Path(artifact_dir or ".igris/browser")
        out_dir.mkdir(parents=True, exist_ok=True)
        screenshot = out_dir / f"browser_smoke_{int(time.time() * 1000)}.png"
        try:
            with self._sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on("requestfailed", lambda req: network_errors.append(req.url))
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                found = page.locator(selector).first.count() > 0
                page.screenshot(path=str(screenshot), full_page=True)
                browser.close()
                return BrowserSmokeResult(
                    ok=found and not console_errors and not network_errors,
                    degraded=False,
                    url=url,
                    selector=selector,
                    selector_found=found,
                    screenshot_path=str(screenshot),
                    screenshot_metadata={"fake": False, "format": "png"},
                    console_errors=console_errors[:20],
                    network_errors=network_errors[:20],
                )
        except Exception as exc:  # noqa: BLE001
            return BrowserSmokeResult(
                ok=False,
                degraded=True,
                url=url,
                selector=selector,
                screenshot_path=str(screenshot),
                screenshot_metadata={"fake": False, "format": "png"},
                console_errors=console_errors[:20],
                network_errors=network_errors[:20],
                error=str(exc)[:300],
            )


def run_browser_smoke_with_fallback(
    *,
    url: str,
    selector: str = "body",
    artifact_dir: Optional[str] = None,
    runner: Optional[BrowserRunner] = None,
) -> BrowserSmokeResult:
    """Run browser smoke; degrade gracefully when no real browser is available."""
    effective = runner
    if effective is None:
        try:
            effective = PlaywrightBrowserRunner()
        except Exception as exc:  # noqa: BLE001
            return BrowserSmokeResult(
                ok=False,
                degraded=True,
                url=url,
                selector=selector,
                error=str(exc)[:300],
            )
    try:
        return effective.run_smoke(url=url, selector=selector, artifact_dir=artifact_dir)
    except Exception as exc:  # noqa: BLE001
        return BrowserSmokeResult(
            ok=False,
            degraded=True,
            url=url,
            selector=selector,
            error=str(exc)[:300],
        )
