"""Tests for EPIC #904 — Mission Brain Selected Advisory Reports Activation & Monitoring."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from igris.agent.mission.selected_advisory import (
    ALL_TAXONOMY_TEMPLATES,
    BRIDGE_OUTPUTS_WITHOUT_TAXONOMY_TEMPLATE,
    DEFAULT_SELECTED_CONFIG,
    EXCLUDED_BY_SCOPE_TEMPLATES,
    EXCLUDED_RUN_STATUSES,
    REACHABLE_IN_SCOPE_TEMPLATES,
    SELECTED_ADVISORY_REPORT_TARGETS,
    SELECTED_ADVISORY_RUN_STATUSES,
    UNREACHABLE_FROM_BRIDGE_TEMPLATES,
    SelectedAdvisoryConfig,
    aggregate_selected_cycles,
    compute_selected_metrics,
    enrich_cycle_selected,
    enrich_report_selected,
    is_excluded_status,
    make_selected_activation_config,
    make_selected_monitoring_config,
    make_synthetic_blocked_cycles,
    make_synthetic_excluded_cycles,
    make_synthetic_fallback_cycles,
    make_synthetic_hard_failure_cycles,
    make_synthetic_insufficient_context_cycles,
    rollback_selected_advisory,
    should_compute,
    should_enrich,
    strip_selected_advisory,
)
from igris.agent.mission.advisory_rollout import (
    has_advisory,
    validate_advisory_output,
    validate_no_original_fields_modified,
)

ACT_CFG = make_selected_activation_config(include_blocked=True)
MON_CFG = make_selected_monitoring_config(include_blocked=True)
BASE    = {"run_id": "test", "outcome": "failed",
           "current_loop_decision": "failed", "mission_brain_decision": "partial"}


# ---------------------------------------------------------------------------
# SelectedAdvisoryConfig (#905)
# ---------------------------------------------------------------------------

class TestSelectedAdvisoryConfig:
    def test_default_disabled(self):
        assert DEFAULT_SELECTED_CONFIG.enabled is False

    def test_default_monitoring_only(self):
        assert DEFAULT_SELECTED_CONFIG.monitoring_only is True

    def test_default_is_gate_false(self):
        assert DEFAULT_SELECTED_CONFIG.is_gate is False

    def test_default_should_emit_false(self):
        assert DEFAULT_SELECTED_CONFIG.should_emit is False

    def test_default_should_compute_false(self):
        assert DEFAULT_SELECTED_CONFIG.should_compute is False

    def test_monitoring_config_enabled(self):
        assert MON_CFG.enabled is True

    def test_monitoring_config_monitoring_only(self):
        assert MON_CFG.monitoring_only is True

    def test_monitoring_config_should_compute(self):
        assert MON_CFG.should_compute is True

    def test_monitoring_config_should_not_emit(self):
        assert MON_CFG.should_emit is False

    def test_monitoring_config_is_gate_false(self):
        assert MON_CFG.is_gate is False

    def test_activation_config_should_emit(self):
        assert ACT_CFG.should_emit is True

    def test_activation_config_is_gate_false(self):
        assert ACT_CFG.is_gate is False

    def test_activation_config_include_blocked(self):
        assert ACT_CFG.include_blocked is True

    def test_activation_config_monitoring_only_false(self):
        assert ACT_CFG.monitoring_only is False

    def test_allows_report_type_diagnostic(self):
        assert ACT_CFG.allows_report_type("diagnostic") is True

    def test_allows_report_type_adoption(self):
        assert ACT_CFG.allows_report_type("adoption") is True

    def test_allows_report_type_shadow(self):
        assert ACT_CFG.allows_report_type("shadow") is True

    def test_allows_report_type_hardening(self):
        assert ACT_CFG.allows_report_type("hardening") is True

    def test_allows_report_type_mission_execution(self):
        assert ACT_CFG.allows_report_type("mission_execution") is True

    def test_blocks_unknown_report_type(self):
        assert ACT_CFG.allows_report_type("unknown_report_xyz") is False

    def test_no_report_type_allowed(self):
        # None report_type → in scope by default
        assert ACT_CFG.allows_report_type(None) is True

    def test_allows_failed_run_status(self):
        assert ACT_CFG.allows_run_status("failed") is True

    def test_allows_blocked_run_status(self):
        assert ACT_CFG.allows_run_status("blocked") is True

    def test_blocks_passed_run_status(self):
        assert ACT_CFG.allows_run_status("passed") is False

    def test_blocks_completed_run_status(self):
        assert ACT_CFG.allows_run_status("completed") is False

    def test_effective_statuses_include_failed(self):
        assert "failed" in ACT_CFG.effective_run_statuses

    def test_effective_statuses_include_blocked(self):
        assert "blocked" in ACT_CFG.effective_run_statuses

    def test_to_dict_has_all_keys(self):
        d = ACT_CFG.to_dict()
        for k in ("enabled", "is_gate", "should_emit", "should_compute",
                  "monitoring_only", "include_blocked", "allowed_report_types"):
            assert k in d

    def test_log_template_usage_default_true(self):
        assert ACT_CFG.log_template_usage is True

    def test_report_targets_count(self):
        assert len(SELECTED_ADVISORY_REPORT_TARGETS) == 5

    def test_excluded_run_statuses_has_passed(self):
        assert "passed" in EXCLUDED_RUN_STATUSES

    def test_excluded_run_statuses_has_completed(self):
        assert "completed" in EXCLUDED_RUN_STATUSES


# ---------------------------------------------------------------------------
# Scope predicates (#905)
# ---------------------------------------------------------------------------

class TestScopePredicates:
    def test_is_excluded_passed_completed(self):
        assert is_excluded_status("passed", "completed") is True

    def test_is_excluded_failed_partial_false(self):
        assert is_excluded_status("failed", "partial") is False

    def test_is_excluded_blocked_partial_false(self):
        assert is_excluded_status("blocked", "partial") is False

    def test_is_excluded_passed_partial_false(self):
        # passed+partial is excluded by run_status gate, not is_excluded
        assert is_excluded_status("passed", "partial") is False

    def test_should_enrich_failed_partial_diagnostic_act(self):
        assert should_enrich("failed", "partial", "diagnostic", ACT_CFG) is True

    def test_should_enrich_blocked_partial_diagnostic_act(self):
        assert should_enrich("blocked", "partial", "diagnostic", ACT_CFG) is True

    def test_should_enrich_passed_completed_excluded(self):
        assert should_enrich("passed", "completed", "diagnostic", ACT_CFG) is False

    def test_should_enrich_passed_partial_excluded(self):
        # passed is not in effective_run_statuses
        assert should_enrich("passed", "partial", "diagnostic", ACT_CFG) is False

    def test_should_enrich_wrong_report_type(self):
        assert should_enrich("failed", "partial", "unknown_report", ACT_CFG) is False

    def test_should_enrich_default_config_always_false(self):
        assert should_enrich("failed", "partial", "diagnostic", DEFAULT_SELECTED_CONFIG) is False

    def test_should_enrich_monitoring_config_always_false(self):
        # monitoring_only → should_emit=False → should_enrich=False
        assert should_enrich("failed", "partial", "diagnostic", MON_CFG) is False

    def test_should_compute_failed_partial_diagnostic(self):
        assert should_compute("failed", "partial", "diagnostic", MON_CFG) is True

    def test_should_compute_blocked_partial_diagnostic(self):
        assert should_compute("blocked", "partial", "diagnostic", MON_CFG) is True

    def test_should_compute_passed_completed_false(self):
        assert should_compute("passed", "completed", "diagnostic", MON_CFG) is False

    def test_should_compute_default_false(self):
        assert should_compute("failed", "partial", "diagnostic", DEFAULT_SELECTED_CONFIG) is False


# ---------------------------------------------------------------------------
# Taxonomy coverage constants (#905/#908)
# ---------------------------------------------------------------------------

class TestTaxonomyCoverage:
    def test_all_taxonomy_templates_count(self):
        assert len(ALL_TAXONOMY_TEMPLATES) == 9

    def test_reachable_in_scope_count(self):
        assert len(REACHABLE_IN_SCOPE_TEMPLATES) == 4

    def test_excluded_by_scope_count(self):
        assert len(EXCLUDED_BY_SCOPE_TEMPLATES) == 1

    def test_excluded_by_scope_is_completed(self):
        assert "completed" in EXCLUDED_BY_SCOPE_TEMPLATES

    def test_unreachable_count(self):
        assert len(UNREACHABLE_FROM_BRIDGE_TEMPLATES) == 4

    def test_bridge_gap_count(self):
        assert len(BRIDGE_OUTPUTS_WITHOUT_TAXONOMY_TEMPLATE) == 4

    def test_coverage_partition(self):
        # Reachable + excluded + unreachable = all
        union = (REACHABLE_IN_SCOPE_TEMPLATES
                 | EXCLUDED_BY_SCOPE_TEMPLATES
                 | UNREACHABLE_FROM_BRIDGE_TEMPLATES)
        assert union == ALL_TAXONOMY_TEMPLATES

    def test_technical_failure_in_reachable(self):
        assert "technical_failure_with_goal_progress" in REACHABLE_IN_SCOPE_TEMPLATES

    def test_hard_failure_in_reachable(self):
        assert "hard_failure" in REACHABLE_IN_SCOPE_TEMPLATES

    def test_insufficient_context_in_reachable(self):
        assert "insufficient_context" in REACHABLE_IN_SCOPE_TEMPLATES

    def test_blocked_with_goal_progress_in_reachable(self):
        assert "blocked_with_goal_progress" in REACHABLE_IN_SCOPE_TEMPLATES


# ---------------------------------------------------------------------------
# enrich_cycle_selected / enrich_report_selected (#906)
# ---------------------------------------------------------------------------

class TestEnrichCycleSelected:
    def test_failed_partial_gets_advisory(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert has_advisory(r)

    def test_blocked_partial_gets_advisory(self):
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert has_advisory(r)

    def test_passed_completed_no_advisory(self):
        c = {"current_loop_decision": "passed", "mission_brain_decision": "completed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert not has_advisory(r)

    def test_passed_partial_no_advisory(self):
        c = {"current_loop_decision": "passed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert not has_advisory(r)

    def test_wrong_report_type_no_advisory(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "execution_log"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert not has_advisory(r)

    def test_monitoring_mode_no_advisory(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=MON_CFG)
        assert not has_advisory(r)

    def test_default_config_no_advisory(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=DEFAULT_SELECTED_CONFIG)
        assert not has_advisory(r)

    def test_auto_executable_false(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert r["recovery_recommendation"]["auto_executable"] is False

    def test_advisory_only_true(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert r["recovery_recommendation"]["advisory_only"] is True

    def test_is_gate_false(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert r["bridge_diagnostics"]["is_gate"] is False

    def test_affects_loop_decision_false(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert r["bridge_diagnostics"]["affects_loop_decision"] is False

    def test_template_logged(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert "_advisory_template_used" in r

    def test_original_fields_preserved(self):
        orig = {"run_id": "x", "outcome": "failed",
                "current_loop_decision": "failed", "mission_brain_decision": "partial",
                "report_type": "diagnostic", "extra": "val"}
        enr = enrich_cycle_selected(orig, config=ACT_CFG)
        assert validate_no_original_fields_modified(orig, enr)

    def test_validate_advisory_output_valid(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        v = validate_advisory_output(r)
        assert v["valid"], f"violations: {v['violations']}"

    def test_hard_failure_action(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert has_advisory(r)
        assert r["recovery_recommendation"]["action"] == "diagnose_failure"

    def test_hard_failure_template_logged(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert r.get("_advisory_template_used") == "hard_failure"

    def test_insufficient_context_action(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "unknown",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert has_advisory(r)
        assert r["recovery_recommendation"]["action"] == "request_context"

    def test_blocked_escalate_action(self):
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        assert r["recovery_recommendation"]["action"] == "escalate_blocked"


# ---------------------------------------------------------------------------
# Rollback (#906)
# ---------------------------------------------------------------------------

class TestRollback:
    def test_strip_removes_recovery_recommendation(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        rolled = strip_selected_advisory(r)
        assert "recovery_recommendation" not in rolled

    def test_strip_removes_bridge_diagnostics(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        rolled = strip_selected_advisory(r)
        assert "bridge_diagnostics" not in rolled

    def test_strip_removes_template_log(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        rolled = strip_selected_advisory(r)
        assert "_advisory_template_used" not in rolled

    def test_strip_preserves_original_fields(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic", "original": "data"}
        r = enrich_cycle_selected(c, config=ACT_CFG)
        rolled = strip_selected_advisory(r)
        assert rolled.get("original") == "data"

    def test_batch_rollback(self):
        cycles = [{"current_loop_decision": "failed", "mission_brain_decision": "partial",
                   "report_type": "diagnostic"} for _ in range(5)]
        enriched = [enrich_cycle_selected(c, config=ACT_CFG) for c in cycles]
        rolled = rollback_selected_advisory(enriched)
        for r in rolled:
            assert not has_advisory(r)
            assert "bridge_diagnostics" not in r


# ---------------------------------------------------------------------------
# Synthetic cycles (#906)
# ---------------------------------------------------------------------------

class TestSyntheticCycles:
    def test_hard_failure_cycles_structure(self):
        cycles = make_synthetic_hard_failure_cycles(5)
        assert len(cycles) == 5
        for c in cycles:
            assert c["current_loop_decision"] == "failed"
            assert c["mission_brain_decision"] == "failed"

    def test_insufficient_context_cycles_structure(self):
        cycles = make_synthetic_insufficient_context_cycles(5)
        assert len(cycles) == 5
        for c in cycles:
            assert c["mission_brain_decision"] == "unknown"

    def test_excluded_cycles_structure(self):
        cycles = make_synthetic_excluded_cycles(5)
        assert len(cycles) == 5
        for c in cycles:
            assert c["current_loop_decision"] == "passed"
            assert c["mission_brain_decision"] == "completed"

    def test_excluded_cycles_no_advisory(self):
        cycles = make_synthetic_excluded_cycles(5)
        enriched = [enrich_cycle_selected(c, config=ACT_CFG) for c in cycles]
        assert not any(has_advisory(r) for r in enriched)

    def test_fallback_cycles_get_advisory(self):
        cycles = make_synthetic_fallback_cycles(5)
        enriched = [enrich_cycle_selected(c, config=ACT_CFG) for c in cycles]
        # blocked+failed is in scope (blocked run_status)
        assert all(has_advisory(r) for r in enriched)

    def test_fallback_cycles_valid_invariants(self):
        cycles = make_synthetic_fallback_cycles(5)
        enriched = [enrich_cycle_selected(c, config=ACT_CFG) for c in cycles]
        for r in enriched:
            v = validate_advisory_output(r)
            assert v["valid"], f"violations: {v['violations']}"

    def test_hard_failure_all_get_advisory(self):
        cycles = make_synthetic_hard_failure_cycles(10)
        enriched = [enrich_cycle_selected(c, config=ACT_CFG) for c in cycles]
        assert all(has_advisory(r) for r in enriched)

    def test_hard_failure_all_valid(self):
        cycles = make_synthetic_hard_failure_cycles(10)
        enriched = [enrich_cycle_selected(c, config=ACT_CFG) for c in cycles]
        for r in enriched:
            v = validate_advisory_output(r)
            assert v["valid"], f"violations: {v['violations']}"


# ---------------------------------------------------------------------------
# Monitoring metrics (#907)
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
                shadow.extend(
                    [{**c, "report_type": "diagnostic"} for c in __import__("json").loads(p.read_text())]
                )
        if not shadow:
            pytest.skip("Shadow cycle data not available")
        blocked   = make_synthetic_blocked_cycles(10, goal_status="partial")
        hard_fail = make_synthetic_hard_failure_cycles(10)
        insuf_ctx = make_synthetic_insufficient_context_cycles(10)
        fallback  = make_synthetic_fallback_cycles(5)
        excluded  = make_synthetic_excluded_cycles(5)
        return shadow + blocked + hard_fail + insuf_ctx + fallback + excluded

    def test_in_scope_coverage_full(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["in_scope_coverage_rate"] == 1.0

    def test_auto_exec_violations_zero(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["auto_executable_violations"] == 0

    def test_loop_decision_violations_zero(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["loop_decision_violations"] == 0

    def test_is_gate_violations_zero(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["is_gate_violations"] == 0

    def test_false_completed_zero(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["potential_critical_false_completed"] == 0

    def test_risk_introduced_zero(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["risk_introduced_candidates"] == 0

    def test_skipped_passed_completed_nonzero(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["skipped_passed_completed_count"] >= 5

    def test_exercised_template_count(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["exercised_template_count"] >= 3  # at minimum failed+partial + blocked+partial + hard_fail

    def test_blocked_advisory_count_nonzero(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["blocked_advisory_count"] > 0

    def test_monitoring_mode_does_not_surface(self, all_cycles):
        mon_enriched = [enrich_cycle_selected(c, config=MON_CFG) for c in all_cycles]
        assert not any(has_advisory(r) for r in mon_enriched)

    def test_rollback_verified_true(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        assert m["rollback_verified"] is True

    def test_mandatory_metric_keys_present(self, all_cycles):
        m = compute_selected_metrics(all_cycles, config=MON_CFG)
        mandatory = [
            "total_reports_enriched", "enriched_failed_count", "enriched_partial_count",
            "enriched_blocked_count", "skipped_passed_completed_count",
            "auto_executable_violations", "loop_decision_violations", "is_gate_violations",
            "recovery_template_distribution", "exercised_template_count",
            "unexercised_template_count", "blocked_advisory_count",
            "report_usefulness_score", "rollback_verified",
            "risk_introduced_candidates", "potential_critical_false_completed",
        ]
        for key in mandatory:
            assert key in m, f"Missing mandatory metric: {key}"


# ---------------------------------------------------------------------------
# Aggregation (activation mode)
# ---------------------------------------------------------------------------

class TestAggregateSelectedCycles:
    @pytest.fixture(scope="class")
    def in_scope_cycles(self):
        shadow = []
        for path in (
            "reports/mission_brain/shadow_monitoring/847/shadow_batch1_cycles_847.json",
            "reports/mission_brain/shadow_monitoring/849/shadow_batch2_cycles_849.json",
            "reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json",
            "reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json",
        ):
            p = Path(path)
            if p.exists():
                shadow.extend(
                    [{**c, "report_type": "diagnostic"} for c in __import__("json").loads(p.read_text())]
                )
        if not shadow:
            pytest.skip("Shadow cycle data not available")
        return (shadow
                + make_synthetic_blocked_cycles(10, goal_status="partial")
                + make_synthetic_hard_failure_cycles(10)
                + make_synthetic_insufficient_context_cycles(10)
                + make_synthetic_fallback_cycles(5))

    def test_all_in_scope_get_advisory(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert agg["cycles_with_advisory"] == len(in_scope_cycles)

    def test_zero_auto_exec_violations(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert agg["auto_executable_violations"] == 0

    def test_zero_loop_violations(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert agg["loop_decision_violations"] == 0

    def test_zero_gate_violations(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert agg["is_gate_violations"] == 0

    def test_four_templates_exercised(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert agg["exercised_template_count"] >= 4

    def test_action_distribution_multiple_actions(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert len(agg["action_distribution"]) >= 3

    def test_continue_from_partial_present(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert "continue_from_partial_progress" in agg["action_distribution"]

    def test_escalate_blocked_present(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert "escalate_blocked" in agg["action_distribution"]

    def test_diagnose_failure_present(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ACT_CFG)
        assert "diagnose_failure" in agg["action_distribution"]


# ---------------------------------------------------------------------------
# Consolidated report (#909)
# ---------------------------------------------------------------------------

class TestConsolidatedReport:
    @pytest.fixture(scope="class")
    def report(self):
        p = Path("reports/mission_brain/selected_advisory/909/selected_advisory_consolidated_909.json")
        if not p.exists():
            pytest.skip("Run run_selected_advisory_consolidated_909.py first.")
        return json.loads(p.read_text())

    def test_final_decision_allowed(self, report):
        allowed = {
            "keep_selected_advisory_enabled",
            "expand_selected_advisory_reports",
            "continue_monitoring",
            "calibrate_unexercised_templates",
            "remediate_again",
            "disable_advisory_reports",
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

    def test_no_global_default_guardrail(self, report):
        assert report["guardrails"]["no_global_default"] is True

    def test_rollback_immediate_guardrail(self, report):
        assert report["guardrails"]["rollback_immediate"] is True

    def test_passed_completed_excluded_guardrail(self, report):
        assert report["guardrails"]["passed_completed_excluded"] is True

    def test_auto_exec_violations_zero(self, report):
        assert report["auto_executable_violations"] == 0

    def test_loop_decision_violations_zero(self, report):
        assert report["loop_decision_violations"] == 0

    def test_is_gate_violations_zero(self, report):
        assert report["is_gate_violations"] == 0

    def test_risk_introduced_zero(self, report):
        assert report["risk_introduced_candidates"] == 0

    def test_false_completed_zero(self, report):
        assert report["potential_critical_false_completed"] == 0

    def test_rollback_verified(self, report):
        assert report["rollback_verified"] is True

    def test_epic_complete(self, report):
        assert report["epic_status"] == "complete"

    def test_all_subissues_completed(self, report):
        assert set(report["subissues_completed"]) == {905, 906, 907, 908, 909}

    def test_exercised_template_count(self, report):
        assert report["exercised_template_count"] == 4

    def test_in_scope_coverage_full(self, report):
        assert report["in_scope_coverage_rate"] == 1.0

    def test_monitoring_mode_silent(self, report):
        assert report["monitoring_mode_silent"] is True

    def test_mandatory_metrics_present(self, report):
        mandatory = [
            "total_reports_enriched", "enriched_failed_count", "enriched_partial_count",
            "enriched_blocked_count", "skipped_passed_completed_count",
            "auto_executable_violations", "loop_decision_violations", "is_gate_violations",
            "recovery_template_distribution", "exercised_template_count",
            "unexercised_template_count", "blocked_advisory_count",
            "report_usefulness_score", "rollback_verified",
            "risk_introduced_candidates", "potential_critical_false_completed",
        ]
        for key in mandatory:
            assert key in report, f"Missing mandatory metric key: {key}"
