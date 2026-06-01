"""Browser/UI smoke evidence with optional Playwright and test-friendly fakes.

#1124 hardening: artifact store, retention, structured console/network events,
screenshot metadata persistence.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from igris.core.safety import redact_secrets

_log = logging.getLogger("igris.browser_evidence")


# ---------------------------------------------------------------------------
# Structured event models (#1124)
# ---------------------------------------------------------------------------

@dataclass
class ConsoleEvent:
    """Structured browser console event."""
    level: str = "error"        # error | warning | info | log
    message: str = ""
    source: str = ""            # url/file that emitted the console msg
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NetworkEvent:
    """Structured browser network event (failures only)."""
    url: str = ""
    method: str = "GET"
    status_code: int = 0        # 0 = no response (connection failed)
    error: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScreenshotMeta:
    """Persistent screenshot metadata (#1124)."""
    path: str = ""
    url: str = ""
    selector: str = ""
    format: str = "png"
    size_bytes: int = 0
    fake: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
    # #1124: structured events
    console_events: List[Dict[str, Any]] = field(default_factory=list)
    network_events: List[Dict[str, Any]] = field(default_factory=list)
    screenshot_meta: Optional[Dict[str, Any]] = None

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
        now = time.time()
        console_events = [
            ConsoleEvent(level="error", message=msg, source=url, timestamp=now).to_dict()
            for msg in self.console_errors
        ]
        network_events = [
            NetworkEvent(url=nerr, method="GET", error="request_failed", timestamp=now).to_dict()
            for nerr in self.network_errors
        ]
        smeta = ScreenshotMeta(
            path=str(artifact), url=url, selector=selector,
            format="png", size_bytes=0, fake=True, timestamp=now,
        )
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
            console_events=console_events,
            network_events=network_events,
            screenshot_meta=smeta.to_dict(),
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
                size = screenshot.stat().st_size if screenshot.exists() else 0
                smeta = ScreenshotMeta(
                    path=str(screenshot), url=url, selector=selector,
                    format="png", size_bytes=size, fake=False,
                )
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
                    screenshot_meta=smeta.to_dict(),
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


# ---------------------------------------------------------------------------
# Artifact store (#1124)
# ---------------------------------------------------------------------------

class BrowserArtifactStore:
    """Persistent store for browser evidence artifacts (#1124).

    Stores screenshot metadata, console/network events as JSON.
    Supports retention/cleanup policy.
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        from igris.models.config import CONFIG
        self._base = Path(base_dir or str(Path(CONFIG.igris_dir) / "browser" / "artifacts"))
        self._base.mkdir(parents=True, exist_ok=True)
        self._index_file = self._base / "index.json"
        self._entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self._index_file.exists():
            try:
                self._entries = json.loads(self._index_file.read_text())
            except (json.JSONDecodeError, OSError):
                _log.warning("browser artifact index corrupt; starting fresh")
                self._entries = []

    def _save(self) -> None:
        try:
            self._index_file.write_text(json.dumps(self._entries, indent=2))
        except OSError as exc:
            _log.warning("failed to save browser artifact index: %s", exc)

    def store_result(self, result: BrowserSmokeResult, run_id: str = "") -> Dict[str, Any]:
        """Persist a smoke result as an artifact entry."""
        entry = {
            "run_id": run_id,
            "url": result.url,
            "ok": result.ok,
            "degraded": result.degraded,
            "screenshot_path": redact_secrets(result.screenshot_path),
            "screenshot_meta": result.screenshot_meta,
            "console_events": result.console_events[:50],
            "network_events": result.network_events[:50],
            "console_error_count": len(result.console_errors),
            "network_error_count": len(result.network_errors),
            "error": redact_secrets(result.error) if result.error else "",
            "timestamp": result.timestamp,
        }
        self._entries.append(entry)
        self._save()
        return entry

    def get_entries(self, run_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Return stored entries, optionally filtered by run_id."""
        if run_id:
            filtered = [e for e in self._entries if e.get("run_id") == run_id]
        else:
            filtered = list(self._entries)
        return filtered[-limit:]

    def apply_retention(self, max_entries: int = 200, max_age_seconds: float = 7 * 86400) -> int:
        """Remove old entries beyond retention limits. Returns count removed."""
        now = time.time()
        before = len(self._entries)
        self._entries = [
            e for e in self._entries
            if (now - e.get("timestamp", 0)) < max_age_seconds
        ]
        if len(self._entries) > max_entries:
            self._entries = self._entries[-max_entries:]
        removed = before - len(self._entries)
        if removed > 0:
            self._save()
            _log.info("browser artifact retention: removed %d entries", removed)
        return removed

    @property
    def count(self) -> int:
        return len(self._entries)
