"""Tests for #885 — consolidated rollout readiness report."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPORT_PATH = Path("reports/mission_brain/rollout/885/bridge_rollout_readiness_885.json")

ALLOWED_DECISIONS = frozenset({
    "keep_diagnostic_bridge_only",
    "candidate_for_assisted_recovery_recommendations",
    "continue_shadow_bridge_monitoring",
    "remediate_again",
    "do_not_integrate",
})
FORBIDDEN_DECISIONS = frozenset({
    "activate_rollout", "enable_by_default", "mandatory_gate", "deploy", "integrate",
})


@pytest.fixture(scope="module")
def report() -> dict:
    if not REPORT_PATH.exists():
        pytest.skip("Run run_bridge_rollout_readiness_885.py first.")
    return json.loads(REPORT_PATH.read_text())


class TestReportExists:
    def test_json(self):
        assert REPORT_PATH.exists()

    def test_md(self):
        assert Path("reports/mission_brain/rollout/885/bridge_rollout_readiness_885.md").exists()


class TestCoreFields:
    def test_subissue(self, report): assert report["subissue"] == 885
    def test_epic(self, report): assert report["epic"] == 880
    def test_evaluation(self, report): assert report["evaluation"] == "passed"
    def test_stop_reason(self, report): assert report["stop_reason"] is None
    def test_epic_status(self, report): assert report["epic_status"] == "complete"


class TestFinalDecision:
    def test_present(self, report): assert "final_decision" in report
    def test_allowed(self, report): assert report["final_decision"] in ALLOWED_DECISIONS
    def test_not_forbidden(self, report): assert report["final_decision"] not in FORBIDDEN_DECISIONS
    def test_rationale(self, report): assert len(report.get("final_decision_rationale", "")) > 50
    def test_not_activated(self, report): assert report["guardrails"]["candidate_does_not_mean_activated"] is True


class TestGateChain:
    def test_passed(self, report): assert report["gate_chain_passed"] is True
    def test_subissues(self, report): assert set(report["subissues_completed"]) == {881, 882, 883, 884, 885}


class TestSafetyMetrics:
    def test_risk_zero(self, report): assert report["risk_introduced_candidates"] == 0
    def test_critical_zero(self, report): assert report["potential_critical_false_completed"] == 0
    def test_false_completed_zero(self, report): assert report["false_completed_count"] == 0
    def test_gate_violations_zero(self, report): assert report["gate_violations"] == 0


class TestReadinessCriteria:
    def test_present(self, report): assert len(report.get("readiness_criteria", [])) >= 5
    def test_all_required_met(self, report): assert report["all_required_criteria_met"] is True
    def test_criteria_fields(self, report):
        for c in report["readiness_criteria"]:
            for f in ("criterion", "met", "required"):
                assert f in c


class TestUsefulnessMetrics:
    def test_usefulness_score(self, report): assert report["reviewer_usefulness_score"] >= 0.8
    def test_cycles_validated(self, report): assert report["total_cycles_validated"] == 30


class TestGuardrails:
    def test_default_off(self, report): assert report["guardrails"]["default_off"] is True
    def test_no_gate(self, report): assert report["guardrails"]["no_mandatory_gate"] is True
    def test_no_rollout(self, report): assert report["guardrails"]["no_rollout_activation"] is True
    def test_loop_unaffected(self, report): assert report["guardrails"]["loop_decision_unaffected"] is True


class TestRecommendations:
    def test_present(self, report): assert len(report.get("recommendations", [])) >= 2
    def test_no_activate_rollout(self, report):
        for r in report["recommendations"]:
            assert "activate rollout" not in r["recommendation"].lower()
            assert "enable by default" not in r["recommendation"].lower()


class TestFindings:
    def test_present(self, report): assert len(report.get("findings", [])) >= 3
    def test_fields(self, report):
        for f in report["findings"]:
            for field in ("id", "finding", "evidence", "impact"):
                assert field in f


class TestMd:
    def _md(self): return Path("reports/mission_brain/rollout/885/bridge_rollout_readiness_885.md").read_text()
    def test_decision_in_md(self): assert "CANDIDATE_FOR_ASSISTED_RECOVERY_RECOMMENDATIONS" in self._md()
    def test_gate_chain_in_md(self): assert "Gate Chain" in self._md()
    def test_guardrails_in_md(self): assert "Guardrails" in self._md()
