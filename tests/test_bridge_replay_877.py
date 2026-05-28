"""Tests for #877 — bridge replay on 30 shadow cycles."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPORT_PATH = Path("reports/mission_brain/bridge/877/bridge_replay_877.json")


@pytest.fixture(scope="module")
def report() -> dict:
    if not REPORT_PATH.exists():
        pytest.skip("Run run_bridge_replay_877.py first.")
    return json.loads(REPORT_PATH.read_text())


class TestReportExists:
    def test_json_exists(self):
        assert REPORT_PATH.exists()

    def test_md_exists(self):
        assert Path("reports/mission_brain/bridge/877/bridge_replay_877.md").exists()


class TestCoreFields:
    def test_subissue(self, report):
        assert report["subissue"] == 877

    def test_epic(self, report):
        assert report["epic"] == 874

    def test_evaluation(self, report):
        assert report["evaluation"] == "passed"

    def test_stop_reason_none(self, report):
        assert report["stop_reason"] is None

    def test_next_subissue(self, report):
        assert report["next_subissue"] == 878


class TestCycleCounts:
    def test_total_cycles(self, report):
        assert report["total_cycles_replayed"] == 30

    def test_baseline(self, report):
        assert report["baseline_cycles"] == 10

    def test_new_cycles(self, report):
        assert report["new_cycles"] == 20

    def test_per_cycle_length(self, report):
        assert len(report["per_cycle_replay"]) == 30


class TestSafetyGate:
    def test_risk_zero(self, report):
        assert report["risk_introduced_candidates"] == 0

    def test_critical_zero(self, report):
        assert report["potential_critical_false_completed"] == 0

    def test_completed_zero(self, report):
        assert report["completed_count"] == 0


class TestDistributions:
    def test_run_status_distribution_present(self, report):
        assert "run_status_distribution" in report

    def test_goal_status_distribution_present(self, report):
        assert "goal_status_distribution" in report

    def test_combined_status_distribution_present(self, report):
        assert "combined_status_distribution" in report

    def test_next_action_distribution_present(self, report):
        assert "next_action_recommendation_distribution" in report

    def test_combined_dist_sums_to_total(self, report):
        total = sum(report["combined_status_distribution"].values())
        assert total == report["total_cycles_replayed"]

    def test_next_dist_sums_to_total(self, report):
        total = sum(report["next_action_recommendation_distribution"].values())
        assert total == report["total_cycles_replayed"]

    def test_technical_failure_goal_progress_count(self, report):
        assert report["technical_failure_with_goal_progress_count"] == 30

    def test_hard_failure_count_zero(self, report):
        assert report["hard_failure_count"] == 0


class TestGuardrails:
    def test_shadow_mode_only(self, report):
        assert report["guardrails"]["shadow_mode_only"] is True

    def test_no_completed_inflation(self, report):
        assert report["guardrails"]["no_completed_inflation"] is True
