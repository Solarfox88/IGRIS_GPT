"""Tests for #882 — bridge_reporter module: enrichment, rollback, non-blocking."""
from __future__ import annotations

import pytest

from igris.agent.mission.bridge_config import DEFAULT_BRIDGE_CONFIG, make_diagnostic_config, make_shadow_config
from igris.agent.mission.bridge_reporter import (
    enrich_report, enrich_report_from_cycle, is_enriched,
    strip_bridge_diagnostics, validate_bridge_diagnostics,
)
from igris.agent.mission.status_bridge import COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS


BASE = {"run_id": "test", "outcome": "failed", "score": 0.5}
DIAG_CFG = make_diagnostic_config()


class TestDefaultConfigNoEnrichment:
    def test_returns_original(self):
        result = enrich_report(BASE, run_status="failed", goal_status="partial",
                               config=DEFAULT_BRIDGE_CONFIG)
        assert result == BASE

    def test_not_enriched(self):
        result = enrich_report(BASE, run_status="failed", goal_status="partial",
                               config=DEFAULT_BRIDGE_CONFIG)
        assert not is_enriched(result)

    def test_shadow_config_no_enrichment(self):
        result = enrich_report(BASE, run_status="failed", goal_status="partial",
                               config=make_shadow_config())
        assert result == BASE


class TestDiagnosticEnrichment:
    def test_is_enriched(self):
        r = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert is_enriched(r)

    def test_combined_status_correct(self):
        r = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert r["bridge_diagnostics"]["combined_status"] == COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS

    def test_is_gate_false(self):
        r = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert r["bridge_diagnostics"]["is_gate"] is False

    def test_affects_loop_decision_false(self):
        r = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert r["bridge_diagnostics"]["affects_loop_decision"] is False

    def test_original_fields_preserved(self):
        r = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        for k, v in BASE.items():
            assert r[k] == v

    def test_original_not_modified(self):
        original_keys = set(BASE.keys())
        _ = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert set(BASE.keys()) == original_keys


class TestValidateBridgeDiagnostics:
    def test_valid_diagnostics(self):
        r = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        assert validate_bridge_diagnostics(r["bridge_diagnostics"]) is True

    def test_is_gate_not_false_raises(self):
        bd = {"combined_status": "hard_failure", "next_action_recommendation": "diagnose_failure",
              "run_status_normalized": "failed", "goal_status_normalized": "failed",
              "is_gate": True, "affects_loop_decision": False}
        with pytest.raises(ValueError, match="is_gate"):
            validate_bridge_diagnostics(bd)

    def test_affects_loop_not_false_raises(self):
        bd = {"combined_status": "hard_failure", "next_action_recommendation": "diagnose_failure",
              "run_status_normalized": "failed", "goal_status_normalized": "failed",
              "is_gate": False, "affects_loop_decision": True}
        with pytest.raises(ValueError, match="affects_loop_decision"):
            validate_bridge_diagnostics(bd)

    def test_missing_fields_raises(self):
        with pytest.raises(ValueError, match="missing"):
            validate_bridge_diagnostics({"combined_status": "completed"})


class TestStrip:
    def test_strip_restores_original(self):
        r = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        stripped = strip_bridge_diagnostics(r)
        assert stripped == BASE

    def test_strip_no_op_on_non_enriched(self):
        stripped = strip_bridge_diagnostics(BASE)
        assert stripped == BASE

    def test_strip_does_not_modify_original(self):
        r = enrich_report(BASE, run_status="failed", goal_status="partial", config=DIAG_CFG)
        original_has_bd = "bridge_diagnostics" in r
        strip_bridge_diagnostics(r)
        assert ("bridge_diagnostics" in r) == original_has_bd


class TestNoneInputs:
    def test_none_run_and_goal(self):
        r = enrich_report({"run_id": "x"}, run_status=None, goal_status=None, config=DIAG_CFG)
        assert is_enriched(r)
        assert r["bridge_diagnostics"]["is_gate"] is False

    def test_infer_from_report(self):
        report = {"current_loop_decision": "failed", "mission_brain_decision": "partial"}
        r = enrich_report(report, config=DIAG_CFG)
        assert r["bridge_diagnostics"]["combined_status"] == COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS


class TestEnrichFromCycle:
    def test_enrich_cycle(self):
        cycle = {"cycle_id": "c1", "current_loop_decision": "failed", "mission_brain_decision": "partial"}
        r = enrich_report_from_cycle(dict(cycle), cycle, config=DIAG_CFG)
        assert is_enriched(r)
        assert r["bridge_diagnostics"]["combined_status"] == COMBINED_TECHNICAL_FAILURE_GOAL_PROGRESS

    def test_original_cycle_not_modified(self):
        cycle = {"cycle_id": "c1", "current_loop_decision": "failed", "mission_brain_decision": "partial"}
        keys_before = set(cycle.keys())
        _ = enrich_report_from_cycle(dict(cycle), cycle, config=DIAG_CFG)
        assert set(cycle.keys()) == keys_before
