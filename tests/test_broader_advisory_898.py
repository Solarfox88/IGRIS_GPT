"""Tests for EPIC #898 — Broader Advisory Rollout Activation Plan (#899-#903)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from igris.agent.mission.broader_advisory import (
    BROADER_ADVISORY_REPORT_TYPES,
    DEFAULT_BROADER_CONFIG,
    BroaderAdvisoryConfig,
    aggregate_broader_cycles,
    compute_monitoring_metrics,
    enrich_cycle_broader,
    enrich_report_broader,
    has_advisory as _has,
    make_broader_activation_config,
    make_broader_monitoring_config,
    make_synthetic_blocked_cycles,
    should_compute_for_run_broader,
    should_emit_for_run_broader,
)
from igris.agent.mission.advisory_rollout import (
    validate_advisory_output,
    validate_no_original_fields_modified,
)

ACT_CFG     = make_broader_activation_config(include_blocked=False)
ACT_BLOCKED = make_broader_activation_config(include_blocked=True)
MON_CFG     = make_broader_monitoring_config(include_blocked=True)
BASE        = {"run_id": "test", "outcome": "failed"}


# ---------------------------------------------------------------------------
# BroaderAdvisoryConfig (#899)
# ---------------------------------------------------------------------------

class TestBroaderAdvisoryConfig:
    def test_default_disabled(self):
        assert DEFAULT_BROADER_CONFIG.enabled is False

    def test_default_monitoring_only(self):
        assert DEFAULT_BROADER_CONFIG.monitoring_only is True

    def test_default_is_gate_false(self):
        assert DEFAULT_BROADER_CONFIG.is_gate is False

    def test_default_should_emit_false(self):
        assert DEFAULT_BROADER_CONFIG.should_emit is False

    def test_default_should_compute_false(self):
        assert DEFAULT_BROADER_CONFIG.should_compute is False

    def test_monitoring_config_enabled(self):
        assert MON_CFG.enabled is True

    def test_monitoring_config_monitoring_only(self):
        assert MON_CFG.monitoring_only is True

    def test_monitoring_config_should_compute_true(self):
        assert MON_CFG.should_compute is True

    def test_monitoring_config_should_emit_false(self):
        assert MON_CFG.should_emit is False

    def test_monitoring_config_is_gate_false(self):
        assert MON_CFG.is_gate is False

    def test_activation_config_should_emit_true(self):
        assert ACT_CFG.should_emit is True

    def test_activation_config_is_gate_false(self):
        assert ACT_CFG.is_gate is False

    def test_effective_statuses_failed_only(self):
        assert "failed" in ACT_CFG.effective_run_statuses
        assert "blocked" not in ACT_CFG.effective_run_statuses

    def test_effective_statuses_with_blocked(self):
        assert "blocked" in ACT_BLOCKED.effective_run_statuses
        assert "failed"  in ACT_BLOCKED.effective_run_statuses

    def test_report_types_mission_execution(self):
        assert "mission_execution" in BROADER_ADVISORY_REPORT_TYPES

    def test_report_types_diagnostic(self):
        assert "diagnostic" in BROADER_ADVISORY_REPORT_TYPES

    def test_to_dict_keys(self):
        d = ACT_CFG.to_dict()
        for k in ("enabled", "is_gate", "should_emit", "should_compute",
                  "effective_run_statuses", "monitoring_only"):
            assert k in d


# ---------------------------------------------------------------------------
# should_emit / should_compute (#899)
# ---------------------------------------------------------------------------

class TestShouldEmitAndCompute:
    def test_default_emit_false_failed(self):
        assert should_emit_for_run_broader("failed", DEFAULT_BROADER_CONFIG) is False

    def test_monitoring_emit_false_failed(self):
        assert should_emit_for_run_broader("failed", MON_CFG) is False

    def test_activation_emit_true_failed(self):
        assert should_emit_for_run_broader("failed", ACT_CFG) is True

    def test_activation_emit_false_blocked_without_flag(self):
        assert should_emit_for_run_broader("blocked", ACT_CFG) is False

    def test_activation_emit_true_blocked_with_flag(self):
        assert should_emit_for_run_broader("blocked", ACT_BLOCKED) is True

    def test_activation_emit_false_passed(self):
        assert should_emit_for_run_broader("passed", ACT_BLOCKED) is False

    def test_monitoring_compute_true_failed(self):
        assert should_compute_for_run_broader("failed", MON_CFG) is True

    def test_monitoring_compute_true_blocked(self):
        assert should_compute_for_run_broader("blocked", MON_CFG) is True

    def test_default_compute_false(self):
        assert should_compute_for_run_broader("failed", DEFAULT_BROADER_CONFIG) is False


# ---------------------------------------------------------------------------
# Blocked-status advisory (#900)
# ---------------------------------------------------------------------------

class TestBlockedStatusAdvisory:
    @pytest.fixture(scope="class")
    def blocked_enriched(self):
        cycles = make_synthetic_blocked_cycles(10, goal_status="partial")
        return [enrich_cycle_broader(c, config=ACT_BLOCKED) for c in cycles]

    def test_all_blocked_get_advisory(self, blocked_enriched):
        assert all(_has(r) for r in blocked_enriched)

    def test_blocked_action_escalate_blocked(self, blocked_enriched):
        for r in blocked_enriched:
            assert r["recovery_recommendation"]["action"] == "escalate_blocked"

    def test_blocked_auto_executable_false(self, blocked_enriched):
        for r in blocked_enriched:
            assert r["recovery_recommendation"]["auto_executable"] is False

    def test_blocked_advisory_only_true(self, blocked_enriched):
        for r in blocked_enriched:
            assert r["recovery_recommendation"]["advisory_only"] is True

    def test_blocked_is_gate_false(self, blocked_enriched):
        for r in blocked_enriched:
            assert r.get("bridge_diagnostics", {}).get("is_gate") is False

    def test_blocked_affects_loop_decision_false(self, blocked_enriched):
        for r in blocked_enriched:
            assert r.get("bridge_diagnostics", {}).get("affects_loop_decision") is False

    def test_blocked_all_valid(self, blocked_enriched):
        for r in blocked_enriched:
            v = validate_advisory_output(r)
            assert v["valid"], f"violations: {v['violations']}"

    def test_blocked_not_in_scope_without_flag(self):
        cycle = make_synthetic_blocked_cycles(1)[0]
        r = enrich_cycle_broader(cycle, config=ACT_CFG)  # include_blocked=False
        assert not _has(r)


# ---------------------------------------------------------------------------
# enrich_report_broader (#901)
# ---------------------------------------------------------------------------

class TestEnrichReportBroader:
    def test_default_unchanged(self):
        r = enrich_report_broader(BASE, run_status="failed", goal_status="partial",
                                   config=DEFAULT_BROADER_CONFIG)
        assert r == BASE
        assert not _has(r)

    def test_monitoring_mode_unchanged(self):
        r = enrich_report_broader(BASE, run_status="failed", goal_status="partial",
                                   config=MON_CFG)
        assert not _has(r)

    def test_activation_failed_has_advisory(self):
        r = enrich_report_broader(BASE, run_status="failed", goal_status="partial",
                                   config=ACT_CFG)
        assert _has(r)

    def test_activation_blocked_has_advisory(self):
        base = {"run_id": "test", "outcome": "blocked"}
        r = enrich_report_broader(base, run_status="blocked", goal_status="partial",
                                   config=ACT_BLOCKED)
        assert _has(r)

    def test_activation_passed_no_advisory(self):
        r = enrich_report_broader(BASE, run_status="passed", goal_status="completed",
                                   config=ACT_CFG)
        assert not _has(r)

    def test_auto_executable_false(self):
        r = enrich_report_broader(BASE, run_status="failed", goal_status="partial",
                                   config=ACT_CFG)
        assert r["recovery_recommendation"]["auto_executable"] is False

    def test_advisory_only_true(self):
        r = enrich_report_broader(BASE, run_status="failed", goal_status="partial",
                                   config=ACT_CFG)
        assert r["recovery_recommendation"]["advisory_only"] is True

    def test_original_fields_preserved(self):
        base = {"run_id": "test", "outcome": "failed", "extra": "value"}
        r = enrich_report_broader(base, run_status="failed", goal_status="partial",
                                   config=ACT_CFG)
        assert validate_no_original_fields_modified(base, r)

    def test_bridge_is_gate_false(self):
        r = enrich_report_broader(BASE, run_status="failed", goal_status="partial",
                                   config=ACT_CFG)
        assert r["bridge_diagnostics"]["is_gate"] is False

    def test_bridge_affects_loop_false(self):
        r = enrich_report_broader(BASE, run_status="failed", goal_status="partial",
                                   config=ACT_CFG)
        assert r["bridge_diagnostics"]["affects_loop_decision"] is False


# ---------------------------------------------------------------------------
# Monitoring mode (#902)
# ---------------------------------------------------------------------------

class TestMonitoringMetrics:
    @pytest.fixture(scope="class")
    def all_cycles(self):
        shadow = []
        for path in (
            "reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json",
            "reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json",
            "reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json",
            "reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json",
        ):
            p = Path(path)
            if p.exists():
                shadow.extend(json.loads(p.read_text()))
        if not shadow:
            pytest.skip("Shadow cycle data not available")
        blocked = make_synthetic_blocked_cycles(10, goal_status="partial")
        return shadow + blocked

    def test_coverage_rate_nonzero(self, all_cycles):
        m = compute_monitoring_metrics(all_cycles, config=MON_CFG)
        assert m["coverage_rate"] > 0

    def test_in_scope_coverage_full(self, all_cycles):
        m = compute_monitoring_metrics(all_cycles, config=MON_CFG)
        assert m["in_scope_coverage_rate"] == 1.0

    def test_auto_exec_violations_zero(self, all_cycles):
        m = compute_monitoring_metrics(all_cycles, config=MON_CFG)
        assert m["auto_executable_violations"] == 0

    def test_action_distribution_present(self, all_cycles):
        m = compute_monitoring_metrics(all_cycles, config=MON_CFG)
        assert len(m["action_distribution"]) > 0

    def test_both_actions_present(self, all_cycles):
        m = compute_monitoring_metrics(all_cycles, config=MON_CFG)
        assert "continue_from_partial_progress" in m["action_distribution"]
        assert "escalate_blocked" in m["action_distribution"]

    def test_monitoring_mode_does_not_surface(self, all_cycles):
        mon_enriched = [enrich_cycle_broader(c, config=MON_CFG) for c in all_cycles]
        assert not any(_has(r) for r in mon_enriched)

    def test_default_disabled_zero_scope(self):
        cycles = [{"current_loop_decision": "failed", "mission_brain_decision": "partial"}]
        m = compute_monitoring_metrics(cycles, config=DEFAULT_BROADER_CONFIG)
        assert m["cycles_with_advisory"] == 0


# ---------------------------------------------------------------------------
# Dataset replay with broader config (#901)
# ---------------------------------------------------------------------------

class TestDatasetReplayBroader:
    @pytest.fixture(scope="class")
    def all_enriched(self):
        shadow = []
        for path in (
            "reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json",
            "reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json",
            "reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json",
            "reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json",
        ):
            p = Path(path)
            if p.exists():
                shadow.extend(json.loads(p.read_text()))
        if not shadow:
            pytest.skip("Shadow cycle data not available")
        blocked = make_synthetic_blocked_cycles(10, goal_status="partial")
        all_c = shadow + blocked
        return [enrich_cycle_broader(c, config=ACT_BLOCKED) for c in all_c]

    def test_all_40_enriched(self, all_enriched):
        assert all(_has(r) for r in all_enriched)

    def test_zero_auto_exec_violations(self, all_enriched):
        viol = [r for r in all_enriched if r["recovery_recommendation"].get("auto_executable") is not False]
        assert len(viol) == 0

    def test_zero_advisory_only_violations(self, all_enriched):
        viol = [r for r in all_enriched if r["recovery_recommendation"].get("advisory_only") is not True]
        assert len(viol) == 0

    def test_zero_loop_decision_violations(self, all_enriched):
        viol = [r for r in all_enriched
                if r.get("bridge_diagnostics", {}).get("affects_loop_decision") is not False]
        assert len(viol) == 0

    def test_zero_is_gate_violations(self, all_enriched):
        viol = [r for r in all_enriched
                if r.get("bridge_diagnostics", {}).get("is_gate") is not False]
        assert len(viol) == 0

    def test_all_valid(self, all_enriched):
        for r in all_enriched:
            v = validate_advisory_output(r)
            assert v["valid"], f"violations: {v['violations']}"

    def test_two_actions_present(self, all_enriched):
        actions = {r["recovery_recommendation"]["action"] for r in all_enriched if _has(r)}
        assert "continue_from_partial_progress" in actions
        assert "escalate_blocked" in actions


# ---------------------------------------------------------------------------
# Consolidated report (#903)
# ---------------------------------------------------------------------------

class TestConsolidatedReport:
    @pytest.fixture(scope="class")
    def report(self):
        p = Path("reports/mission_brain/broader_advisory/903/broader_advisory_consolidated_903.json")
        if not p.exists():
            pytest.skip("Run run_broader_advisory_consolidated_903.py first.")
        return json.loads(p.read_text())

    def test_final_decision_allowed(self, report):
        allowed = {
            "keep_advisory_disabled", "enable_selected_advisory_reports",
            "extend_advisory_rollout", "remediate_again", "do_not_integrate",
        }
        assert report["final_decision"] in allowed

    def test_gate_chain_passed(self, report):
        assert report["gate_chain_passed"] is True

    def test_advisory_only_guardrail(self, report):
        assert report["guardrails"]["advisory_only"] is True

    def test_no_auto_execution_guardrail(self, report):
        assert report["guardrails"]["no_auto_execution"] is True

    def test_flag_required_guardrail(self, report):
        assert report["guardrails"]["flag_required"] is True

    def test_no_global_default(self, report):
        assert report["guardrails"]["no_global_default"] is True

    def test_rollback_immediate(self, report):
        assert report["guardrails"]["rollback_immediate"] is True

    def test_monitoring_mode_available(self, report):
        assert report["guardrails"]["monitoring_mode_available"] is True

    def test_auto_exec_violations_zero(self, report):
        assert report["auto_executable_violations"] == 0

    def test_loop_decision_violations_zero(self, report):
        assert report["loop_decision_violations"] == 0

    def test_blocked_validated(self, report):
        assert report["blocked_advisory_validated"] is True

    def test_epic_complete(self, report):
        assert report["epic_status"] == "complete"

    def test_all_subissues_completed(self, report):
        assert set(report["subissues_completed"]) == {899, 900, 901, 902, 903}

    def test_cycles_validated(self, report):
        assert report["total_cycles_validated"] == 40

    def test_in_scope_coverage(self, report):
        assert report["in_scope_coverage_rate"] == 1.0
