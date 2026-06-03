"""Tests for CodeHealthMonitor check in RankGauntlet (#521 alignment)."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from igris.web.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_code_health_monitor_check_passes():
    """code_health_monitor module is wired → check must pass."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g._check_module_wired("igris.core.code_health_monitor")
    assert result.passed, f"CodeHealthMonitor check failed: {result.evidence}"


def test_gauntlet_includes_code_health_check():
    """Full gauntlet run must include a code_health_monitor check."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g.run()
    check_names = [c.name for c in result.checks]
    assert any("code_health_monitor" in n for n in check_names), \
        f"code_health_monitor not in gauntlet checks: {check_names}"


def test_gauntlet_still_passes_after_new_check():
    """Adding code_health_monitor check must not reduce score — all module checks must pass."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g.run()
    # All module_exists checks must pass (they are env-independent)
    module_checks = [c for c in result.checks if c.name.startswith("module_exists:")]
    failed_module_checks = [c for c in module_checks if not c.passed]
    assert not failed_module_checks, \
        f"Module checks failed: {[(c.name, c.evidence) for c in failed_module_checks]}"


def test_gauntlet_score_unchanged_or_better():
    """Score must be >= 0.85 (S threshold) after adding the new check."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g.run()
    assert result.score >= 0.85, f"Score {result.score} below S threshold after adding code_health check"


def test_missing_module_check_fails():
    """Verify _check_module_wired still correctly fails for missing modules."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g._check_module_wired("igris.core.totally_nonexistent_xyz_module")
    assert not result.passed


def test_api_rank_gauntlet_includes_code_health(client):
    """API endpoint must include code_health_monitor in checks list."""
    r = client.get("/api/rank/gauntlet")
    assert r.status_code == 200
    d = r.json()
    check_names = [c["name"] for c in d.get("checks", [])]
    assert any("code_health" in n for n in check_names), \
        f"code_health not in API checks: {check_names}"
