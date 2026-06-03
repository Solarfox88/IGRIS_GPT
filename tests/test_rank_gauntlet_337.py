"""
Tests for Rank S gauntlet — issue #337.

Verifies:
- RankGauntlet().run() returns GauntletResult with passed/failed/blocked/skipped
- score is float 0-1
- checks list is non-empty
- GET /api/rank/gauntlet returns machine-readable result
- Mock root with missing modules → blocked=True
- result has rank field ("S", "A", "B", "C")
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from igris.core.rank_gauntlet import RankGauntlet, GauntletResult, GauntletCheck


@pytest.fixture
def client(tmp_path):
    from igris.models.config import CONFIG
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    for d in [".igris/tasks", ".igris/timeline", ".igris/memory"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["IGRIS_PROJECT_ROOT"] = str(root)
    CONFIG.project_root = Path(str(root))
    from igris.web.server import create_app
    return TestClient(create_app())


@pytest.fixture
def empty_root(tmp_path) -> Path:
    """Empty project root with no IGRIS modules."""
    root = tmp_path / "empty_project"
    root.mkdir()
    return root


@pytest.fixture
def real_root() -> Path:
    """Point to actual IGRIS_GPT project root."""
    return Path(__file__).parent.parent


# ---- Unit tests for RankGauntlet ----

class TestRankGauntlet:
    def test_run_returns_gauntlet_result(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        assert isinstance(result, GauntletResult)

    def test_result_has_passed_failed_blocked_skipped(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        assert isinstance(result.passed, bool)
        assert isinstance(result.failed, bool)
        assert isinstance(result.blocked, bool)
        assert isinstance(result.skipped, bool)

    def test_passed_and_failed_are_inverses(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        assert result.passed != result.failed

    def test_score_is_float_0_to_1(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0

    def test_checks_list_nonempty(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        assert len(result.checks) > 0

    def test_rank_field_is_valid(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        assert result.rank in ("S", "A", "B", "C")

    def test_empty_root_gives_blocked(self, empty_root):
        """A root with no modules should produce blocked=True."""
        result = RankGauntlet().run(project_root=empty_root)
        assert result.blocked is True

    def test_empty_root_rank_not_s(self, empty_root):
        result = RankGauntlet().run(project_root=empty_root)
        assert result.rank != "S"

    def test_to_dict_structure(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        d = result.to_dict()
        for key in ("passed", "failed", "blocked", "skipped", "rank", "score", "checks"):
            assert key in d, f"Missing key: {key}"

    def test_checks_have_required_fields(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        for check in result.checks:
            assert hasattr(check, "name")
            assert hasattr(check, "passed")
            assert hasattr(check, "evidence")
            assert hasattr(check, "required")

    def test_gauntlet_check_in_to_dict(self, real_root):
        result = RankGauntlet().run(project_root=real_root)
        d = result.to_dict()
        for check_dict in d["checks"]:
            assert "name" in check_dict
            assert "passed" in check_dict
            assert "evidence" in check_dict

    def test_score_zero_for_fully_empty_root(self, tmp_path):
        """All module checks should fail for a completely empty dir."""
        result = RankGauntlet().run(project_root=tmp_path)
        # All module existence checks fail → score < 1
        assert result.score < 1.0


# ---- Integration: /api/rank/gauntlet endpoint ----

class TestRankGauntletEndpoint:
    def test_endpoint_returns_200(self, client):
        r = client.get("/api/rank/gauntlet")
        assert r.status_code == 200

    def test_endpoint_has_passed_field(self, client):
        r = client.get("/api/rank/gauntlet")
        data = r.json()
        assert "passed" in data

    def test_endpoint_has_rank_field(self, client):
        r = client.get("/api/rank/gauntlet")
        data = r.json()
        assert "rank" in data

    def test_endpoint_has_score_field(self, client):
        r = client.get("/api/rank/gauntlet")
        data = r.json()
        assert "score" in data

    def test_endpoint_has_checks_field(self, client):
        r = client.get("/api/rank/gauntlet")
        data = r.json()
        assert "checks" in data

    def test_endpoint_score_is_numeric(self, client):
        r = client.get("/api/rank/gauntlet")
        data = r.json()
        score = data.get("score")
        if score is not None:
            assert isinstance(score, (int, float))
            assert 0.0 <= float(score) <= 1.0

    def test_endpoint_graceful_on_error(self, client):
        """Even if RankGauntlet raises, endpoint returns machine-readable dict."""
        with patch("igris.core.rank_gauntlet.RankGauntlet.run", side_effect=RuntimeError("mock")):
            r = client.get("/api/rank/gauntlet")
        assert r.status_code == 200
        data = r.json()
        assert "passed" in data or "error" in data
