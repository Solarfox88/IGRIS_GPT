"""Tests for #878 — bridge usefulness validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPORT_PATH = Path("reports/mission_brain/bridge/878/bridge_usefulness_878.json")


@pytest.fixture(scope="module")
def report() -> dict:
    if not REPORT_PATH.exists():
        pytest.skip("Run run_bridge_usefulness_validation_878.py first.")
    return json.loads(REPORT_PATH.read_text())


class TestReportExists:
    def test_json_exists(self):
        assert REPORT_PATH.exists()

    def test_md_exists(self):
        assert Path("reports/mission_brain/bridge/878/bridge_usefulness_878.md").exists()


class TestCoreFields:
    def test_subissue(self, report):
        assert report["subissue"] == 878

    def test_evaluation(self, report):
        assert report["evaluation"] == "passed"

    def test_stop_reason_none(self, report):
        assert report["stop_reason"] is None


class TestUsefulnessMetrics:
    def test_reviewer_usefulness_score_is_float(self, report):
        assert isinstance(report["reviewer_usefulness_score"], float)

    def test_reviewer_usefulness_score_high(self, report):
        assert report["reviewer_usefulness_score"] >= 0.8

    def test_high_value_fraction_is_float(self, report):
        assert isinstance(report["high_value_fraction"], float)

    def test_high_value_fraction_positive(self, report):
        assert report["high_value_fraction"] > 0.0


class TestSafetyGate:
    def test_risk_zero(self, report):
        assert report["risk_introduced_candidates"] == 0

    def test_critical_zero(self, report):
        assert report["potential_critical_false_completed"] == 0

    def test_dangerous_zero(self, report):
        assert report["dangerous_combined_statuses_found"] == 0


class TestUsefulnessAnalysis:
    def test_usefulness_analysis_present(self, report):
        assert "usefulness_analysis" in report
        assert len(report["usefulness_analysis"]) >= 1

    def test_usefulness_analysis_fields(self, report):
        for u in report["usefulness_analysis"]:
            for field in ("combined_status", "count", "information_gain", "actionability", "risk"):
                assert field in u

    def test_next_action_analysis_present(self, report):
        assert "next_action_analysis" in report
        assert len(report["next_action_analysis"]) >= 1


class TestGuardrails:
    def test_shadow_mode_only(self, report):
        assert report["guardrails"]["shadow_mode_only"] is True

    def test_observational_only(self, report):
        assert report["guardrails"]["observational_only"] is True

    def test_not_a_loop_gate(self, report):
        assert report["guardrails"]["not_a_loop_gate"] is True
