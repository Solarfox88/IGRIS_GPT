"""Tests for EPIC #886 — Recovery Taxonomy (#887), Advisor module (#888-#890)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from igris.agent.mission.bridge_config import DEFAULT_BRIDGE_CONFIG, make_diagnostic_config
from igris.agent.mission.recovery_advisor import (
    aggregate_recovery_cycles,
    build_recovery_recommendation,
    enrich_cycle_with_recovery,
    enrich_with_recovery,
    has_recovery_recommendation,
    strip_recovery_recommendation,
    validate_recovery_recommendation,
)
from igris.agent.mission.recovery_taxonomy import (
    CONFIDENCE_LEVELS,
    RECOVERY_ACTIONS,
    RECOVERY_TEMPLATES,
    _validate_taxonomy,
    get_template,
    list_statuses_with_templates,
)
from igris.agent.mission.status_bridge import COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS

DIAG_CFG = make_diagnostic_config()
BASE = {"run_id": "test", "outcome": "failed"}


# ---------------------------------------------------------------------------
# Taxonomy (#887)
# ---------------------------------------------------------------------------

class TestTaxonomyInvariants:
    def test_validate_taxonomy_passes(self):
        _validate_taxonomy()

    def test_all_templates_auto_executable_false(self):
        for status, tmpl in RECOVERY_TEMPLATES.items():
            assert tmpl["auto_executable"] is False, f"{status}: auto_executable must be False"

    def test_all_actions_in_set(self):
        for status, tmpl in RECOVERY_TEMPLATES.items():
            assert tmpl["action"] in RECOVERY_ACTIONS, f"{status}: unknown action {tmpl['action']!r}"

    def test_all_confidences_valid(self):
        for status, tmpl in RECOVERY_TEMPLATES.items():
            assert tmpl["confidence"] in CONFIDENCE_LEVELS

    def test_safe_next_action_non_empty(self):
        for status, tmpl in RECOVERY_TEMPLATES.items():
            assert tmpl["safe_next_action"].strip(), f"{status}: empty safe_next_action"

    def test_nine_templates_defined(self):
        assert len(RECOVERY_TEMPLATES) == 9

    def test_critical_combined_status_covered(self):
        for cs in (
            COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS,
            "hard_failure", "blocked_with_goal_progress",
            "completed", "insufficient_context",
        ):
            assert cs in RECOVERY_TEMPLATES, f"{cs} not in RECOVERY_TEMPLATES"

    @pytest.mark.parametrize("status", list(RECOVERY_TEMPLATES.keys()))
    def test_get_template_returns_entry(self, status: str):
        tmpl = get_template(status)
        assert tmpl is not None
        assert tmpl["auto_executable"] is False

    def test_get_template_unknown_returns_none(self):
        assert get_template("totally_unknown_xyz") is None

    def test_list_statuses_correct(self):
        statuses = list_statuses_with_templates()
        assert set(statuses) == set(RECOVERY_TEMPLATES.keys())


# ---------------------------------------------------------------------------
# build_recovery_recommendation (#888)
# ---------------------------------------------------------------------------

class TestBuildRecoveryRecommendation:
    def test_technical_failure_action(self):
        rec = build_recovery_recommendation(COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS)
        assert rec["action"] == "continue_from_partial_progress"

    def test_auto_executable_false(self):
        for status in RECOVERY_TEMPLATES:
            rec = build_recovery_recommendation(status)
            assert rec["auto_executable"] is False

    def test_advisory_only_true(self):
        for status in RECOVERY_TEMPLATES:
            rec = build_recovery_recommendation(status)
            assert rec["advisory_only"] is True

    def test_unknown_status_fallback(self):
        rec = build_recovery_recommendation("totally_unknown_status_xyz")
        assert rec["auto_executable"] is False
        assert rec["advisory_only"] is True

    def test_hard_failure_action(self):
        rec = build_recovery_recommendation("hard_failure")
        assert rec["action"] == "diagnose_failure"

    def test_completed_action(self):
        rec = build_recovery_recommendation("completed")
        assert rec["action"] == "mark_complete"

    def test_evidence_present_with_cycle(self):
        cycle = {"current_loop_decision": "failed", "mission_brain_decision": "partial", "goal_class": "planning"}
        rec = build_recovery_recommendation(COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS, cycle=cycle)
        assert "current_loop_decision" in rec["evidence_present"]

    def test_evidence_missing_without_cycle(self):
        rec = build_recovery_recommendation(COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS)
        assert len(rec["evidence_missing"]) > 0


# ---------------------------------------------------------------------------
# enrich_with_recovery (#888 / #889)
# ---------------------------------------------------------------------------

class TestEnrichWithRecovery:
    def test_default_no_recommendation(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial",
                                 config=DEFAULT_BRIDGE_CONFIG)
        assert r == BASE
        assert not has_recovery_recommendation(r)

    def test_diagnostic_has_recommendation(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert has_recovery_recommendation(r)

    def test_recommendation_auto_executable_false(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert r["recovery_recommendation"]["auto_executable"] is False

    def test_recommendation_advisory_only_true(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert r["recovery_recommendation"]["advisory_only"] is True

    def test_original_fields_preserved(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        for k, v in BASE.items():
            assert r[k] == v

    def test_bridge_diagnostics_also_present(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert "bridge_diagnostics" in r

    def test_strip_removes_recommendation(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        stripped = strip_recovery_recommendation(r)
        assert "recovery_recommendation" not in stripped
        assert stripped["run_id"] == BASE["run_id"]

    def test_based_on_combined_status(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        bd = r["bridge_diagnostics"]["combined_status"]
        rec = r["recovery_recommendation"]
        assert rec["based_on_combined_status"] == bd


# ---------------------------------------------------------------------------
# validate_recovery_recommendation
# ---------------------------------------------------------------------------

class TestValidateRecoveryRecommendation:
    def test_valid_recommendation(self):
        r = enrich_with_recovery(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert validate_recovery_recommendation(r["recovery_recommendation"]) is True

    def test_auto_executable_true_raises(self):
        bad = {"auto_executable": True, "advisory_only": True, "action": "diagnose_failure",
               "confidence": "high", "safe_next_action": "do something"}
        with pytest.raises(ValueError, match="auto_executable"):
            validate_recovery_recommendation(bad)

    def test_advisory_only_false_raises(self):
        bad = {"auto_executable": False, "advisory_only": False, "action": "diagnose_failure",
               "confidence": "high", "safe_next_action": "do something"}
        with pytest.raises(ValueError, match="advisory_only"):
            validate_recovery_recommendation(bad)

    def test_invalid_action_raises(self):
        bad = {"auto_executable": False, "advisory_only": True, "action": "DELETE_EVERYTHING",
               "confidence": "high", "safe_next_action": "x"}
        with pytest.raises(ValueError, match="action"):
            validate_recovery_recommendation(bad)


# ---------------------------------------------------------------------------
# Dataset replay (#890)
# ---------------------------------------------------------------------------

class TestDatasetReplay:
    @pytest.fixture(scope="class")
    def enriched(self):
        cycles = []
        for path in (
            "reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json",
            "reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json",
            "reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json",
            "reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json",
        ):
            p = Path(path)
            if p.exists():
                cycles.extend(json.loads(p.read_text()))
        if not cycles:
            pytest.skip("Shadow cycle data not available")
        return [enrich_cycle_with_recovery(c, config=DIAG_CFG) for c in cycles]

    def test_all_enriched(self, enriched):
        assert all(has_recovery_recommendation(r) for r in enriched)

    def test_zero_auto_exec_violations(self, enriched):
        violations = [r for r in enriched if r["recovery_recommendation"].get("auto_executable") is not False]
        assert not violations

    def test_zero_advisory_only_violations(self, enriched):
        violations = [r for r in enriched if r["recovery_recommendation"].get("advisory_only") is not True]
        assert not violations

    def test_all_recommendations_valid(self, enriched):
        for r in enriched:
            assert validate_recovery_recommendation(r["recovery_recommendation"]) is True

    def test_aggregate_no_violations(self, enriched):
        raw = [json.loads(json.dumps(r)) for r in enriched]
        # Use original cycles for aggregate
        cycles = []
        for path in (
            "reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json",
            "reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json",
            "reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json",
            "reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json",
        ):
            p = Path(path)
            if p.exists():
                cycles.extend(json.loads(p.read_text()))
        agg = aggregate_recovery_cycles(cycles, config=DIAG_CFG)
        assert agg["auto_executable_violations"] == 0


# ---------------------------------------------------------------------------
# Consolidated report (#891)
# ---------------------------------------------------------------------------

class TestConsolidatedReport:
    @pytest.fixture(scope="class")
    def report(self):
        p = Path("reports/mission_brain/recovery/891/recovery_consolidated_891.json")
        if not p.exists():
            pytest.skip("Run run_recovery_consolidated_891.py first.")
        return json.loads(p.read_text())

    def test_final_decision_allowed(self, report):
        allowed = {"keep_diagnostic_only", "candidate_for_advisory_rollout",
                   "continue_recommendation_calibration", "remediate_again", "do_not_integrate"}
        assert report["final_decision"] in allowed

    def test_not_activated(self, report):
        assert report["guardrails"]["candidate_does_not_mean_activated"] is True

    def test_advisory_only_guardrail(self, report):
        assert report["guardrails"]["advisory_only"] is True

    def test_no_auto_execution_guardrail(self, report):
        assert report["guardrails"]["no_auto_execution"] is True

    def test_auto_exec_violations_zero(self, report):
        assert report["auto_executable_violations"] == 0

    def test_epic_complete(self, report):
        assert report["epic_status"] == "complete"

    def test_gate_chain_passed(self, report):
        assert report["gate_chain_passed"] is True

    def test_all_subissues_completed(self, report):
        assert set(report["subissues_completed"]) == {887, 888, 889, 890, 891}
