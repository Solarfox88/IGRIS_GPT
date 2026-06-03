"""Tests for #521 CodeHealthMonitor runtime wiring in meta_watchdog and API endpoint."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# meta_watchdog wiring
# ---------------------------------------------------------------------------

def test_meta_watchdog_imports_code_health_monitor():
    """Verify _get_code_health_monitor returns CodeHealthMonitor class."""
    from igris.core.meta_watchdog import _get_code_health_monitor
    from igris.core.code_health_monitor import CodeHealthMonitor
    cls = _get_code_health_monitor()
    assert cls is CodeHealthMonitor


def test_code_health_monitor_degraded_on_empty_project(tmp_path):
    """CodeHealthMonitor must not crash if coverage/TODO/git data unavailable."""
    from igris.core.code_health_monitor import CodeHealthMonitor

    # tmp_path has no igris/ dir, no coverage.json, no git
    with patch("igris.core.code_health_monitor._load_open_proactive_issues", return_value=[]):
        chm = CodeHealthMonitor(str(tmp_path), dry_run=True)
        report = chm.run(run_coverage=False)

    assert report is not None
    assert hasattr(report, "findings")
    assert hasattr(report, "errors")
    # Must return gracefully — errors may exist, but no exception raised


def test_code_health_no_github_calls_in_tests(tmp_path):
    """CodeHealthMonitor must not make real GitHub API calls when patched."""
    from igris.core.code_health_monitor import CodeHealthMonitor

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        with patch("igris.core.code_health_monitor._load_open_proactive_issues", return_value=[]):
            chm = CodeHealthMonitor(str(tmp_path), dry_run=True)
            report = chm.run(run_coverage=False)

        # Verify no gh issue create was called
        for call in mock_run.call_args_list:
            args = call[0][0] if call[0] else []
            cmd_str = " ".join(str(a) for a in args)
            assert "gh issue create" not in cmd_str


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

def test_code_health_summary_returns_no_data_initially():
    """GET /api/code-health/summary returns no_data when monitor has not run yet."""
    import importlib
    import igris.api.routes.code_health as mod
    # Reset the cache
    mod._last_report = None

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(mod.get_code_health_summary())
    assert result == {"status": "no_data"}


def test_code_health_summary_returns_cached_report():
    """GET /api/code-health/summary returns the cached report after update."""
    import asyncio
    import igris.api.routes.code_health as mod

    fake_report = MagicMock()
    fake_report.findings = []
    fake_report.issues_opened = ["https://github.com/x/y/issues/1"]
    fake_report.issues_skipped = 0
    fake_report.errors = []
    fake_report.ran_at = 1234567890.0

    mod.update_code_health_cache(fake_report)

    result = asyncio.get_event_loop().run_until_complete(mod.get_code_health_summary())
    assert result["status"] == "ok"
    assert result["issues_opened"] == ["https://github.com/x/y/issues/1"]
    assert result["ran_at"] == 1234567890.0


def test_code_health_cache_update_wired_in_meta_watchdog():
    """Verify meta_watchdog.py imports update_code_health_cache after health run."""
    import inspect
    import igris.core.meta_watchdog as mw
    src = inspect.getsource(mw)
    assert "update_code_health_cache" in src
    assert "igris.api.routes.code_health" in src
