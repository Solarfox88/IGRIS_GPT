"""Tests for RankGauntlet module resolution fix (issue #337)."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from fastapi.testclient import TestClient

from igris.web.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_check_module_wired_existing_module():
    """A module that exists must return passed=True."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g._check_module_wired("igris.core.chat_interlocutor_preflight")
    assert result.passed, f"Expected passed=True, got: {result.evidence}"


def test_check_module_wired_action_guard():
    """action_guard must be found."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g._check_module_wired("igris.core.action_guard")
    assert result.passed, f"Expected passed=True, got: {result.evidence}"


def test_check_module_wired_missing_module():
    """A module that does not exist must return passed=False."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g._check_module_wired("igris.core.totally_nonexistent_xyz_abc")
    assert not result.passed


def test_gauntlet_run_returns_valid_result(tmp_path):
    """Full gauntlet run returns a GauntletResult with required fields."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g.run(project_root=tmp_path)
    assert hasattr(result, "rank")
    assert hasattr(result, "score")
    assert hasattr(result, "passed")
    assert hasattr(result, "checks")
    assert isinstance(result.checks, list)
    assert 0.0 <= result.score <= 1.0
    assert result.rank in ("S", "A", "B", "C")


def test_gauntlet_score_improves_with_fix(tmp_path):
    """After fix, score must be > 0.714 (pre-fix value)."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g.run(project_root=tmp_path)
    # With correct module detection, at least chat_interlocutor_preflight
    # and action_guard must now pass → score > 0.714
    assert result.score > 0.714, f"Score {result.score} should be > 0.714 after fix"


def test_gauntlet_passed_not_hardcoded(tmp_path):
    """passed must be computed from checks, not hardcoded."""
    from igris.core.rank_gauntlet import RankGauntlet
    g = RankGauntlet()
    result = g.run(project_root=tmp_path)
    # If all required checks pass → passed=True
    required_checks = [c for c in result.checks if c.required]
    expected_passed = all(c.passed for c in required_checks) and result.score >= 0.85
    assert result.passed == expected_passed


def test_api_rank_gauntlet_endpoint(client):
    """API endpoint returns correct structure."""
    r = client.get("/api/rank/gauntlet")
    assert r.status_code == 200
    d = r.json()
    assert "rank" in d
    assert "score" in d
    assert "passed" in d
    assert "checks" in d
    assert isinstance(d["checks"], list)
    assert d["rank"] in ("S", "A", "B", "C")
