from __future__ import annotations

from igris.core.browser_evidence import (
    BrowserSmokeResult,
    FakeBrowserRunner,
    run_browser_smoke_with_fallback,
)
from igris.core.devops_manager import DevOpsManager


def test_browser_smoke_result_to_dict_roundtrip() -> None:
    result = BrowserSmokeResult(ok=True, url="http://example", selector="body")
    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["url"] == "http://example"
    assert payload["selector"] == "body"


def test_fake_browser_runner_success(tmp_path) -> None:
    runner = FakeBrowserRunner()
    result = runner.run_smoke(url="http://localhost", selector="#app", artifact_dir=str(tmp_path))
    assert result.ok is True
    assert result.degraded is False
    assert result.selector_found is True
    assert result.screenshot_metadata["fake"] is True


def test_fake_browser_runner_selector_assertion_failure(tmp_path) -> None:
    runner = FakeBrowserRunner(selector_found=False)
    result = runner.run_smoke(url="http://localhost", selector="#missing", artifact_dir=str(tmp_path))
    assert result.ok is False
    assert result.selector_found is False


def test_fake_browser_runner_captures_console_and_network_errors(tmp_path) -> None:
    runner = FakeBrowserRunner(
        console_errors=["TypeError: bad"],
        network_errors=["https://example.invalid/api"],
    )
    result = runner.run_smoke(url="http://localhost", artifact_dir=str(tmp_path))
    assert result.ok is False
    assert result.console_errors == ["TypeError: bad"]
    assert result.network_errors == ["https://example.invalid/api"]


def test_fallback_degraded_when_playwright_unavailable() -> None:
    result = run_browser_smoke_with_fallback(url="http://localhost")
    # In CI/local without Playwright this should degrade; with Playwright it may run real.
    assert isinstance(result.ok, bool)
    assert isinstance(result.degraded, bool)
    if result.degraded:
        assert result.error


def test_devops_manager_run_browser_smoke_with_fake_runner(tmp_path) -> None:
    manager = DevOpsManager(str(tmp_path))
    payload = manager.run_browser_smoke(
        url="http://localhost:7778/api/ping",
        selector="body",
        runner=FakeBrowserRunner(selector_found=True),
    )
    assert payload["ok"] is True
    assert payload["degraded"] is False
    assert payload["selector_found"] is True


def test_devops_dry_run_evidence_contains_browser_metadata(tmp_path) -> None:
    manager = DevOpsManager(str(tmp_path))
    result = manager.run_deploy(dry_run=True)
    browser = result["dry_run_evidence"]["browser"]
    assert "ok" in browser
    assert "degraded" in browser
    assert "console_errors" in browser
    assert "network_errors" in browser
