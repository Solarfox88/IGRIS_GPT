"""Tests for igris/core/outcome_quality_tracker.py (issue #522)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from igris.core.outcome_quality_tracker import (
    OutcomeQualityTracker,
    QualityRecord,
    QualityReport,
    QUALITY_STICKY,
    QUALITY_REOPENED,
    QUALITY_ROLLBACK,
    _history_path,
    avg_quality_for_profile,
    compute_quality_score,
    enrich_outcome_with_quality,
    load_quality_scores,
    save_quality_scores,
)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestQualityScorePersistence:
    def test_save_and_load(self, tmp_path):
        rec = QualityRecord("id1", issue_number=42, profile="mini", closed_at=1000.0, quality_score=0.5)
        save_quality_scores(str(tmp_path), {"id1": rec})
        loaded = load_quality_scores(str(tmp_path))
        assert "id1" in loaded
        assert loaded["id1"].quality_score == pytest.approx(0.5)
        assert loaded["id1"].issue_number == 42

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_quality_scores(str(tmp_path)) == {}

    def test_load_corrupt_returns_empty(self, tmp_path):
        _history_path(str(tmp_path)).parent.mkdir(parents=True, exist_ok=True)
        _history_path(str(tmp_path)).write_text("CORRUPT")
        assert load_quality_scores(str(tmp_path)) == {}

    def test_save_creates_parent(self, tmp_path):
        rec = QualityRecord("x", None, "p", 0.0)
        save_quality_scores(str(tmp_path / "deep"), {"x": rec})
        assert _history_path(str(tmp_path / "deep")).exists()

    def test_roundtrip_reopen_flags(self, tmp_path):
        rec = QualityRecord("id2", 10, "strong", 500.0,
                            quality_score=0.5, reopen_detected=True, rollback_detected=False)
        save_quality_scores(str(tmp_path), {"id2": rec})
        loaded = load_quality_scores(str(tmp_path))
        assert loaded["id2"].reopen_detected is True
        assert loaded["id2"].rollback_detected is False


# ---------------------------------------------------------------------------
# Quality score computation
# ---------------------------------------------------------------------------

class TestComputeQualityScore:
    def _make_rec(self, days_ago: float, issue_number: int = 1) -> QualityRecord:
        return QualityRecord(
            outcome_id="oid",
            issue_number=issue_number,
            profile="mini",
            closed_at=time.time() - days_ago * 86400,
        )

    def test_too_recent_returns_current_score(self, tmp_path):
        rec = self._make_rec(days_ago=3)
        score = compute_quality_score(str(tmp_path), rec)
        assert score == QUALITY_STICKY  # unchanged

    def test_old_closed_issue_is_sticky(self, tmp_path):
        rec = self._make_rec(days_ago=10)
        with patch("igris.core.outcome_quality_tracker._issue_was_reopened", return_value=False):
            score = compute_quality_score(str(tmp_path), rec)
        assert score == QUALITY_STICKY

    def test_reopened_issue_gets_reopened_score(self, tmp_path):
        rec = self._make_rec(days_ago=10)
        with patch("igris.core.outcome_quality_tracker._issue_was_reopened", return_value=True):
            score = compute_quality_score(str(tmp_path), rec)
        assert score == QUALITY_REOPENED

    def test_no_issue_number_is_sticky(self, tmp_path):
        rec = QualityRecord("oid", None, "mini", time.time() - 10 * 86400)
        score = compute_quality_score(str(tmp_path), rec)
        assert score == QUALITY_STICKY


# ---------------------------------------------------------------------------
# Enrich and avg helpers
# ---------------------------------------------------------------------------

class TestEnrichOutcome:
    def test_adds_quality_score_when_available(self, tmp_path):
        scores = {"oid1": QualityRecord("oid1", 1, "mini", 0.0, quality_score=0.7)}
        outcome = {"outcome_id": "oid1", "outcome": "success"}
        enriched = enrich_outcome_with_quality(outcome, scores)
        assert enriched["quality_score"] == pytest.approx(0.7)

    def test_no_change_when_not_in_scores(self, tmp_path):
        outcome = {"outcome_id": "oid_missing", "outcome": "success"}
        enriched = enrich_outcome_with_quality(outcome, {})
        assert "quality_score" not in enriched

    def test_does_not_mutate_original(self):
        scores = {"oid1": QualityRecord("oid1", 1, "mini", 0.0, quality_score=0.5)}
        outcome = {"outcome_id": "oid1", "outcome": "success"}
        enrich_outcome_with_quality(outcome, scores)
        assert "quality_score" not in outcome


class TestAvgQualityForProfile:
    def test_returns_avg_of_matching(self):
        scores = {
            "a": QualityRecord("a", 1, "mini", 0.0, quality_score=1.0),
            "b": QualityRecord("b", 2, "mini", 0.0, quality_score=0.5),
            "c": QualityRecord("c", 3, "mini", 0.0, quality_score=0.5),
        }
        outcomes = [
            {"outcome_id": "a", "preferred_profile": "mini", "outcome": "success"},
            {"outcome_id": "b", "preferred_profile": "mini", "outcome": "success"},
            {"outcome_id": "c", "preferred_profile": "mini", "outcome": "success"},
        ]
        avg = avg_quality_for_profile(outcomes, "mini", scores, min_history=1)
        assert avg == pytest.approx(2.0 / 3, rel=1e-3)

    def test_returns_none_below_min_history(self):
        scores = {"a": QualityRecord("a", 1, "mini", 0.0, quality_score=1.0)}
        outcomes = [{"outcome_id": "a", "preferred_profile": "mini", "outcome": "success"}]
        assert avg_quality_for_profile(outcomes, "mini", scores, min_history=5) is None

    def test_ignores_failures(self):
        scores = {"a": QualityRecord("a", 1, "mini", 0.0, quality_score=1.0)}
        outcomes = [
            {"outcome_id": "a", "preferred_profile": "mini", "outcome": "success"},
            {"outcome_id": "b", "preferred_profile": "mini", "outcome": "failure"},
        ]
        avg = avg_quality_for_profile(outcomes, "mini", scores, min_history=1)
        assert avg == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Router integration: quality_weighted_success_rate
# ---------------------------------------------------------------------------

class TestQualityWeightedSuccessRate:
    def _make_tracker(self, tmp_path):
        return OutcomeQualityTracker(str(tmp_path))

    def test_returns_none_below_min_history(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        result = tracker.quality_weighted_success_rate([], "mini", "implementer", "code_fix", min_history=3)
        assert result is None

    def test_falls_back_to_plain_success_rate_without_scores(self, tmp_path):
        outcomes = [
            {"preferred_profile": "mini", "agent_role": "implementer",
             "task_type": "code_fix", "outcome": "success", "outcome_id": "a"},
            {"preferred_profile": "mini", "agent_role": "implementer",
             "task_type": "code_fix", "outcome": "success", "outcome_id": "b"},
            {"preferred_profile": "mini", "agent_role": "implementer",
             "task_type": "code_fix", "outcome": "failure", "outcome_id": "c"},
        ]
        tracker = self._make_tracker(tmp_path)
        result = tracker.quality_weighted_success_rate(
            outcomes, "mini", "implementer", "code_fix", min_history=1
        )
        # 2 success / 3 total = 0.667, no quality scores available → plain rate
        assert result == pytest.approx(2 / 3, rel=1e-3)

    def test_applies_quality_multiplier(self, tmp_path):
        outcomes = [
            {"preferred_profile": "mini", "agent_role": "implementer",
             "task_type": "code_fix", "outcome": "success", "outcome_id": "a"},
            {"preferred_profile": "mini", "agent_role": "implementer",
             "task_type": "code_fix", "outcome": "success", "outcome_id": "b"},
            {"preferred_profile": "mini", "agent_role": "implementer",
             "task_type": "code_fix", "outcome": "success", "outcome_id": "c"},
        ]
        # All success but quality = 0.5 → weighted = 1.0 * 0.5
        scores = {
            "a": QualityRecord("a", 1, "mini", 0.0, quality_score=0.5),
            "b": QualityRecord("b", 2, "mini", 0.0, quality_score=0.5),
            "c": QualityRecord("c", 3, "mini", 0.0, quality_score=0.5),
        }
        save_quality_scores(str(tmp_path), scores)
        tracker = self._make_tracker(tmp_path)
        result = tracker.quality_weighted_success_rate(
            outcomes, "mini", "implementer", "code_fix", min_history=1
        )
        assert result == pytest.approx(0.5, rel=1e-3)


# ---------------------------------------------------------------------------
# Background job run()
# ---------------------------------------------------------------------------

class TestOutcomeQualityTrackerRun:
    def test_run_returns_report(self, tmp_path):
        (tmp_path / ".igris").mkdir()
        (tmp_path / ".igris" / "assignment_outcomes.json").write_text("[]")
        tracker = OutcomeQualityTracker(
            str(tmp_path),
            outcomes_path=str(tmp_path / ".igris" / "assignment_outcomes.json"),
        )
        report = tracker.run()
        assert isinstance(report, QualityReport)

    def test_skips_recent_outcomes(self, tmp_path):
        outcome = {
            "outcome_id": "recent1",
            "outcome": "success",
            "preferred_profile": "mini",
            "timestamp": time.time() - 86400,  # 1 day ago — below 7 day window
        }
        path = tmp_path / ".igris" / "assignment_outcomes.json"
        path.parent.mkdir()
        path.write_text(json.dumps([outcome]))
        tracker = OutcomeQualityTracker(str(tmp_path), outcomes_path=str(path))
        report = tracker.run()
        assert report.skipped >= 1
        assert report.updated == 0

    def test_missing_outcomes_file_is_graceful(self, tmp_path):
        tracker = OutcomeQualityTracker(str(tmp_path), outcomes_path=str(tmp_path / "nofile.json"))
        report = tracker.run()
        assert isinstance(report, QualityReport)
