"""Tests for #879 — consolidated bridge report and final decision."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPORT_PATH = Path("reports/mission_brain/bridge/879/bridge_consolidated_879.json")

ALLOWED_DECISIONS = frozenset({
    "keep_shadow_diagnostic_bridge",
    "candidate_for_controlled_bridge_rollout",
    "continue_calibration",
    "remediate_again",
    "do_not_integrate",
})

FORBIDDEN_DECISIONS = frozenset({
    "activate_rollout",
    "enable_by_default",
    "mandatory_gate",
    "integrate",
    "deploy",
    "rollout",
})


@pytest.fixture(scope="module")
def report() -> dict:
    if not REPORT_PATH.exists():
        pytest.skip("Run run_bridge_consolidated_879.py first.")
    return json.loads(REPORT_PATH.read_text())


class TestReportExists:
    def test_json_exists(self):
        assert REPORT_PATH.exists()

    def test_md_exists(self):
        assert Path("reports/mission_brain/bridge/879/bridge_consolidated_879.md").exists()


class TestCoreFields:
    def test_subissue(self, report):
        assert report["subissue"] == 879

    def test_epic(self, report):
        assert report["epic"] == 874

    def test_evaluation(self, report):
        assert report["evaluation"] == "passed"

    def test_stop_reason_none(self, report):
        assert report["stop_reason"] is None

    def test_epic_status_complete(self, report):
        assert report["epic_status"] == "complete"


class TestFinalDecision:
    def test_final_decision_present(self, report):
        assert "final_decision" in report

    def test_final_decision_in_allowed_set(self, report):
        assert report["final_decision"] in ALLOWED_DECISIONS

    def test_final_decision_not_forbidden(self, report):
        assert report["final_decision"] not in FORBIDDEN_DECISIONS

    def test_final_decision_rationale_present(self, report):
        assert len(report.get("final_decision_rationale", "")) > 50

    def test_candidate_does_not_mean_activated_guardrail(self, report):
        assert report["guardrails"]["candidate_does_not_mean_activated"] is True


class TestGateChain:
    def test_gate_chain_passed(self, report):
        assert report["gate_chain_passed"] is True

    def test_all_subissues_completed(self, report):
        assert set(report["subissues_completed"]) == {875, 876, 877, 878, 879}


class TestSafetyMetrics:
    def test_risk_zero(self, report):
        assert report["risk_introduced_candidates"] == 0

    def test_critical_zero(self, report):
        assert report["potential_critical_false_completed"] == 0

    def test_dangerous_zero(self, report):
        assert report["dangerous_combined_statuses_found"] == 0

    def test_completed_zero(self, report):
        assert report["completed_count"] == 0


class TestKeyMetrics:
    def test_total_cycles(self, report):
        assert report["total_cycles_replayed"] == 30

    def test_reviewer_usefulness_score(self, report):
        assert report["reviewer_usefulness_score"] >= 0.8

    def test_high_value_fraction(self, report):
        assert report["high_value_fraction"] >= 0.8

    def test_mapping_table_size(self, report):
        assert report["mapping_table_size"] == 16


class TestFindings:
    def test_findings_present(self, report):
        assert len(report.get("findings", [])) >= 3

    def test_findings_fields(self, report):
        for f in report["findings"]:
            for field in ("id", "finding", "evidence", "impact"):
                assert field in f


class TestRecommendations:
    def test_recommendations_present(self, report):
        assert len(report.get("recommendations", [])) >= 2

    def test_no_rollout_activation_in_recommendations(self, report):
        for r in report["recommendations"]:
            text = r["recommendation"].lower()
            for forbidden in ("activate rollout", "enable by default", "mandatory gate"):
                assert forbidden not in text

    def test_shadow_diagnostic_recommendation_present(self, report):
        scopes = [r["scope"] for r in report["recommendations"]]
        assert "shadow_diagnostic" in scopes or "constraint" in scopes


class TestGuardrails:
    def test_shadow_mode_only(self, report):
        assert report["guardrails"]["shadow_mode_only"] is True

    def test_default_behavior_unchanged(self, report):
        assert report["guardrails"]["default_behavior_unchanged"] is True

    def test_no_enable_by_default(self, report):
        assert report["guardrails"]["no_enable_by_default"] is True

    def test_no_mandatory_gate(self, report):
        assert report["guardrails"]["no_mandatory_gate"] is True

    def test_no_rollout_activation(self, report):
        assert report["guardrails"]["no_rollout_activation"] is True

    def test_no_integration_without_approval(self, report):
        assert report["guardrails"]["no_integration_without_approval"] is True


class TestMdContent:
    def _md(self):
        return Path("reports/mission_brain/bridge/879/bridge_consolidated_879.md").read_text()

    def test_md_contains_final_decision(self):
        assert "CANDIDATE_FOR_CONTROLLED_BRIDGE_ROLLOUT" in self._md()

    def test_md_contains_gate_chain(self):
        assert "Gate Chain" in self._md()

    def test_md_contains_guardrails(self):
        assert "Guardrails" in self._md()

    def test_md_contains_complete(self):
        assert "complete" in self._md().lower()
