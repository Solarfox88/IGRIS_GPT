"""Tests for EPIC #910 — Mission Brain Taxonomy-Bridge Alignment."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from igris.agent.mission.taxonomy_bridge import (
    ALL_TAXONOMY_TEMPLATES,
    BRIDGE_TO_TAXONOMY_ALIGNMENT,
    INTERNAL_FALLBACK_ONLY_TEMPLATES,
    NEWLY_ALIGNED_BRIDGE_OUTPUTS,
    NEWLY_REACHABLE_IN_SCOPE_TEMPLATES,
    POST_ALIGNMENT_REACHABLE,
    PRE_ALIGNMENT_REACHABLE,
    REACHABLE_OUTSIDE_SCOPE,
    compute_alignment_coverage,
    get_aligned_template,
    get_aligned_template_key,
    get_bridge_to_taxonomy_report,
    validate_alignment_invariants,
)
from igris.agent.mission.selected_advisory import (
    aggregate_selected_cycles,
    compute_selected_metrics,
    enrich_cycle_selected,
    make_selected_activation_config,
    make_selected_aligned_activation_config,
    make_selected_aligned_monitoring_config,
    make_synthetic_blocked_cycles,
    make_synthetic_excluded_cycles,
    make_synthetic_fallback_cycles,
    make_synthetic_hard_failure_cycles,
    make_synthetic_insufficient_context_cycles,
)
from igris.agent.mission.advisory_rollout import (
    has_advisory,
    validate_advisory_output,
)
from igris.agent.mission.status_bridge import COMBINED_STATUSES


ALIGNED_ACT = make_selected_aligned_activation_config(include_blocked=True)
ALIGNED_MON = make_selected_aligned_monitoring_config(include_blocked=True)
STD_ACT     = make_selected_activation_config(include_blocked=True)


# ---------------------------------------------------------------------------
# Alignment map (#911)
# ---------------------------------------------------------------------------

class TestAlignmentMap:
    def test_alignment_map_has_9_entries(self):
        assert len(BRIDGE_TO_TAXONOMY_ALIGNMENT) == 9

    def test_all_bridge_outputs_in_map(self):
        for cs in COMBINED_STATUSES:
            assert cs in BRIDGE_TO_TAXONOMY_ALIGNMENT, f"Missing: {cs}"

    def test_direct_matches_present(self):
        direct = {
            "completed", "technical_failure_with_goal_progress",
            "hard_failure", "insufficient_context", "blocked_with_goal_progress",
        }
        for cs in direct:
            assert BRIDGE_TO_TAXONOMY_ALIGNMENT[cs] == cs

    def test_new_alignments_present(self):
        assert BRIDGE_TO_TAXONOMY_ALIGNMENT["technical_success_but_goal_incomplete"] == "run_passed_goal_partial"
        assert BRIDGE_TO_TAXONOMY_ALIGNMENT["blocked_goal_failed"] == "blocked_no_goal_progress"
        assert BRIDGE_TO_TAXONOMY_ALIGNMENT["goal_complete_run_failed"] == "anomaly_run_passed_goal_not_completed"
        assert BRIDGE_TO_TAXONOMY_ALIGNMENT["goal_complete_run_blocked"] == "anomaly_run_passed_goal_not_completed"

    def test_newly_aligned_count(self):
        assert len(NEWLY_ALIGNED_BRIDGE_OUTPUTS) == 4

    def test_invariants_pass(self):
        violations = validate_alignment_invariants()
        assert violations == [], f"Violations: {violations}"

    def test_all_taxonomy_partitioned(self):
        all_accounted = (
            POST_ALIGNMENT_REACHABLE
            | REACHABLE_OUTSIDE_SCOPE
            | INTERNAL_FALLBACK_ONLY_TEMPLATES
        )
        assert all_accounted == ALL_TAXONOMY_TEMPLATES

    def test_sets_disjoint(self):
        sets = [POST_ALIGNMENT_REACHABLE, REACHABLE_OUTSIDE_SCOPE,
                INTERNAL_FALLBACK_ONLY_TEMPLATES]
        for i, s1 in enumerate(sets):
            for s2 in sets[i+1:]:
                assert not (s1 & s2), f"Overlap: {s1 & s2}"


# ---------------------------------------------------------------------------
# get_aligned_template / get_aligned_template_key (#912)
# ---------------------------------------------------------------------------

class TestGetAlignedTemplate:
    def test_direct_match_technical_failure(self):
        tmpl = get_aligned_template("technical_failure_with_goal_progress")
        assert tmpl is not None
        assert tmpl["action"] == "continue_from_partial_progress"

    def test_aligned_blocked_goal_failed(self):
        tmpl = get_aligned_template("blocked_goal_failed")
        assert tmpl is not None
        assert tmpl["action"] == "escalate_blocked"

    def test_aligned_goal_complete_run_failed(self):
        tmpl = get_aligned_template("goal_complete_run_failed")
        assert tmpl is not None
        assert tmpl["action"] == "investigate_anomaly"

    def test_aligned_goal_complete_run_blocked(self):
        tmpl = get_aligned_template("goal_complete_run_blocked")
        assert tmpl is not None
        assert tmpl["action"] == "investigate_anomaly"

    def test_aligned_technical_success_goal_incomplete(self):
        tmpl = get_aligned_template("technical_success_but_goal_incomplete")
        assert tmpl is not None
        assert tmpl["action"] == "review_partial_complete"

    def test_all_bridge_outputs_have_template(self):
        for cs in COMBINED_STATUSES:
            tmpl = get_aligned_template(cs)
            assert tmpl is not None, f"No template for {cs}"

    def test_all_templates_advisory_invariants(self):
        for cs in COMBINED_STATUSES:
            tmpl = get_aligned_template(cs)
            assert tmpl["auto_executable"] is False, f"{cs}.auto_executable"
            assert tmpl["advisory_only"] is True, f"{cs}.advisory_only"

    def test_get_key_blocked_goal_failed(self):
        key = get_aligned_template_key("blocked_goal_failed")
        assert key == "blocked_no_goal_progress"

    def test_get_key_direct_match(self):
        key = get_aligned_template_key("hard_failure")
        assert key == "hard_failure"

    def test_get_key_fallback_for_unknown(self):
        key = get_aligned_template_key("nonexistent_status_xyz")
        assert key == "fallback"


# ---------------------------------------------------------------------------
# Coverage analysis (#911/#914)
# ---------------------------------------------------------------------------

class TestAlignmentCoverage:
    def test_pre_alignment_count(self):
        assert len(PRE_ALIGNMENT_REACHABLE) == 4

    def test_post_alignment_count(self):
        assert len(POST_ALIGNMENT_REACHABLE) == 6

    def test_newly_reachable_count(self):
        assert len(NEWLY_REACHABLE_IN_SCOPE_TEMPLATES) == 2

    def test_newly_reachable_templates(self):
        assert "blocked_no_goal_progress" in NEWLY_REACHABLE_IN_SCOPE_TEMPLATES
        assert "anomaly_run_passed_goal_not_completed" in NEWLY_REACHABLE_IN_SCOPE_TEMPLATES

    def test_excluded_from_scope_count(self):
        assert len(REACHABLE_OUTSIDE_SCOPE) == 2

    def test_excluded_contains_completed(self):
        assert "completed" in REACHABLE_OUTSIDE_SCOPE

    def test_excluded_contains_run_passed_goal_partial(self):
        assert "run_passed_goal_partial" in REACHABLE_OUTSIDE_SCOPE

    def test_internal_fallback_only(self):
        assert len(INTERNAL_FALLBACK_ONLY_TEMPLATES) == 1
        assert "unknown_status" in INTERNAL_FALLBACK_ONLY_TEMPLATES

    def test_compute_coverage_all_bridge_have_template(self):
        cov = compute_alignment_coverage()
        assert cov["all_bridge_outputs_have_template"] is True

    def test_compute_coverage_all_templates_reachable(self):
        cov = compute_alignment_coverage()
        assert cov["all_taxonomy_templates_reachable"] is True

    def test_compute_coverage_no_unaccounted(self):
        cov = compute_alignment_coverage()
        assert cov["unaccounted_templates"] == []


# ---------------------------------------------------------------------------
# SelectedAdvisoryConfig — aligned config (#912)
# ---------------------------------------------------------------------------

class TestAlignedConfig:
    def test_aligned_act_has_flag_true(self):
        assert ALIGNED_ACT.use_taxonomy_bridge_alignment is True

    def test_aligned_mon_has_flag_true(self):
        assert ALIGNED_MON.use_taxonomy_bridge_alignment is True

    def test_standard_config_flag_false(self):
        assert STD_ACT.use_taxonomy_bridge_alignment is False

    def test_aligned_config_is_gate_false(self):
        assert ALIGNED_ACT.is_gate is False

    def test_aligned_config_should_emit(self):
        assert ALIGNED_ACT.should_emit is True

    def test_aligned_mon_should_not_emit(self):
        assert ALIGNED_MON.should_emit is False

    def test_to_dict_has_alignment_key(self):
        d = ALIGNED_ACT.to_dict()
        assert "use_taxonomy_bridge_alignment" in d
        assert d["use_taxonomy_bridge_alignment"] is True


# ---------------------------------------------------------------------------
# Enrichment with aligned config (#912/#913)
# ---------------------------------------------------------------------------

class TestAlignedEnrichment:
    def test_failed_partial_gets_advisory(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert has_advisory(r)

    def test_failed_partial_correct_template(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert r.get("_advisory_template_used") == "technical_failure_with_goal_progress"
        assert r["recovery_recommendation"]["action"] == "continue_from_partial_progress"

    def test_blocked_failed_gets_advisory(self):
        # blocked+failed → bridge: blocked_goal_failed → taxonomy: blocked_no_goal_progress
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert has_advisory(r)

    def test_blocked_failed_correct_template(self):
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert r.get("_advisory_template_used") == "blocked_no_goal_progress"
        assert r["recovery_recommendation"]["action"] == "escalate_blocked"

    def test_failed_completed_gets_advisory(self):
        # failed+completed → bridge: goal_complete_run_failed → taxonomy: anomaly_run_passed_goal_not_completed
        c = {"current_loop_decision": "failed", "mission_brain_decision": "completed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert has_advisory(r)

    def test_failed_completed_correct_template(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "completed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert r.get("_advisory_template_used") == "anomaly_run_passed_goal_not_completed"
        assert r["recovery_recommendation"]["action"] == "investigate_anomaly"

    def test_blocked_completed_gets_advisory(self):
        # blocked+completed → bridge: goal_complete_run_blocked → taxonomy: anomaly
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "completed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert has_advisory(r)

    def test_blocked_completed_correct_template(self):
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "completed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert r.get("_advisory_template_used") == "anomaly_run_passed_goal_not_completed"

    def test_passed_completed_excluded(self):
        c = {"current_loop_decision": "passed", "mission_brain_decision": "completed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert not has_advisory(r)

    def test_auto_executable_false(self):
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert r["recovery_recommendation"]["auto_executable"] is False

    def test_advisory_only_true(self):
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert r["recovery_recommendation"]["advisory_only"] is True

    def test_is_gate_false(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert r["bridge_diagnostics"]["is_gate"] is False

    def test_affects_loop_decision_false(self):
        c = {"current_loop_decision": "failed", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        assert r["bridge_diagnostics"]["affects_loop_decision"] is False

    def test_validate_advisory_output(self):
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_ACT)
        v = validate_advisory_output(r)
        assert v["valid"], f"violations: {v['violations']}"

    def test_aligned_monitoring_mode_silent(self):
        c = {"current_loop_decision": "blocked", "mission_brain_decision": "failed",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=ALIGNED_MON)
        assert not has_advisory(r)

    def test_standard_config_backward_compatible(self):
        # Standard config should still work exactly as before
        c = {"current_loop_decision": "failed", "mission_brain_decision": "partial",
             "report_type": "diagnostic"}
        r = enrich_cycle_selected(c, config=STD_ACT)
        assert has_advisory(r)
        assert r["recovery_recommendation"]["action"] == "continue_from_partial_progress"

    def test_fallback_cycles_aligned(self):
        # blocked+failed: previously fallback await_clarification, now escalate_blocked
        cycles = make_synthetic_fallback_cycles(5)
        enriched = [enrich_cycle_selected(c, config=ALIGNED_ACT) for c in cycles]
        for r in enriched:
            assert has_advisory(r)
            assert r["recovery_recommendation"]["action"] == "escalate_blocked"
            assert r.get("_advisory_template_used") == "blocked_no_goal_progress"

    def test_fallback_cycles_standard_config_action(self):
        # Standard config: blocked+failed → blocked_goal_failed → no taxonomy match → fallback
        cycles = make_synthetic_fallback_cycles(5)
        enriched = [enrich_cycle_selected(c, config=STD_ACT) for c in cycles]
        for r in enriched:
            assert has_advisory(r)
            assert r.get("_advisory_template_used") == "fallback"


# ---------------------------------------------------------------------------
# Full dataset replay (#913)
# ---------------------------------------------------------------------------

class TestAlignedReplay:
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
                    [{**c, "report_type": "diagnostic"}
                     for c in __import__("json").loads(p.read_text())]
                )
        if not shadow:
            pytest.skip("Shadow cycle data not available")
        return (shadow
                + make_synthetic_blocked_cycles(10, goal_status="partial")
                + make_synthetic_hard_failure_cycles(10)
                + make_synthetic_insufficient_context_cycles(10)
                + make_synthetic_fallback_cycles(5))

    def test_all_in_scope_get_advisory(self, in_scope_cycles):
        enriched = [enrich_cycle_selected(c, config=ALIGNED_ACT) for c in in_scope_cycles]
        assert all(has_advisory(r) for r in enriched)

    def test_zero_auto_exec_violations(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ALIGNED_ACT)
        assert agg["auto_executable_violations"] == 0

    def test_zero_loop_violations(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ALIGNED_ACT)
        assert agg["loop_decision_violations"] == 0

    def test_zero_gate_violations(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ALIGNED_ACT)
        assert agg["is_gate_violations"] == 0

    def test_six_templates_exercised(self, in_scope_cycles):
        # Extended with anomaly cycles to exercise all 6 post-alignment templates
        anomaly = [
            {"cycle_id": "a-fc", "current_loop_decision": "failed",
             "mission_brain_decision": "completed", "report_type": "diagnostic"},
            {"cycle_id": "a-bc", "current_loop_decision": "blocked",
             "mission_brain_decision": "completed", "report_type": "diagnostic"},
        ]
        m = compute_selected_metrics(in_scope_cycles + anomaly, config=ALIGNED_MON)
        assert m["exercised_template_count"] >= 6

    def test_blocked_no_goal_progress_exercised(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ALIGNED_ACT)
        assert "blocked_no_goal_progress" in agg.get("exercised_templates", [])

    def test_escalate_blocked_in_action_dist(self, in_scope_cycles):
        agg = aggregate_selected_cycles(in_scope_cycles, config=ALIGNED_ACT)
        assert "escalate_blocked" in agg["action_distribution"]

    def test_monitoring_silent(self, in_scope_cycles):
        mon_enriched = [enrich_cycle_selected(c, config=ALIGNED_MON) for c in in_scope_cycles]
        assert not any(has_advisory(r) for r in mon_enriched)

    def test_excluded_no_advisory(self):
        excl = make_synthetic_excluded_cycles(5)
        enriched = [enrich_cycle_selected(c, config=ALIGNED_ACT) for c in excl]
        assert not any(has_advisory(r) for r in enriched)

    def test_all_valid_invariants(self, in_scope_cycles):
        enriched = [enrich_cycle_selected(c, config=ALIGNED_ACT) for c in in_scope_cycles]
        for r in enriched:
            v = validate_advisory_output(r)
            assert v["valid"], f"violations: {v['violations']}"


# ---------------------------------------------------------------------------
# Consolidated report (#915)
# ---------------------------------------------------------------------------

class TestConsolidatedReport:
    @pytest.fixture(scope="class")
    def report(self):
        p = Path("reports/mission_brain/taxonomy_bridge/915/taxonomy_bridge_consolidated_915.json")
        if not p.exists():
            pytest.skip("Run run_taxonomy_bridge_consolidated_915.py first.")
        return json.loads(p.read_text())

    def test_final_decision_allowed(self, report):
        allowed = {
            "taxonomy_bridge_aligned",
            "keep_selected_advisory_enabled_with_known_gaps",
            "remove_orphan_templates",
            "continue_calibration",
            "remediate_again",
            "do_not_expand",
        }
        assert report["final_decision"] in allowed

    def test_gate_chain_passed(self, report):
        assert report["gate_chain_passed"] is True

    def test_templates_gained(self, report):
        assert report["templates_gained"] == 2

    def test_post_alignment_templates(self, report):
        assert report["post_alignment_in_scope_templates"] == 6

    def test_auto_exec_violations_zero(self, report):
        assert report["auto_executable_violations"] == 0

    def test_loop_violations_zero(self, report):
        assert report["loop_decision_violations"] == 0

    def test_is_gate_violations_zero(self, report):
        assert report["is_gate_violations"] == 0

    def test_risk_introduced_zero(self, report):
        assert report["risk_introduced_candidates"] == 0

    def test_false_completed_zero(self, report):
        assert report["potential_critical_false_completed"] == 0

    def test_excluded_safe(self, report):
        assert report["excluded_got_advisory"] == 0

    def test_monitoring_silent(self, report):
        assert report["monitoring_mode_silent"] is True

    def test_rollback_verified(self, report):
        assert report["rollback_verified"] is True

    def test_scope_unchanged_guardrail(self, report):
        assert report["guardrails"]["scope_unchanged"] is True

    def test_backward_compatible_guardrail(self, report):
        assert report["guardrails"]["backward_compatible"] is True

    def test_advisory_only_guardrail(self, report):
        assert report["guardrails"]["advisory_only"] is True

    def test_epic_complete(self, report):
        assert report["epic_status"] == "complete"

    def test_all_subissues_completed(self, report):
        assert set(report["subissues_completed"]) == {911, 912, 913, 914, 915}
