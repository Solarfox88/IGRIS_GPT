"""Tests for EPIC #892 — Advisory Recovery Rollout (#893-#897)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from igris.agent.mission.advisory_rollout import (
    ADVISORY_DEFAULT_RUN_STATUSES,
    ADVISORY_REPORT_TARGETS,
    DEFAULT_ADVISORY_CONFIG,
    AdvisoryRolloutConfig,
    aggregate_advisory_cycles,
    advisory_config_from_env,
    enrich_cycle_with_advisory,
    enrich_report_with_advisory,
    has_advisory,
    make_advisory_enabled_config,
    rollback,
    should_emit_for_run,
    strip_advisory,
    validate_advisory_output,
    validate_no_original_fields_modified,
)

ENABLED_CFG = make_advisory_enabled_config()
BASE = {"run_id": "test", "outcome": "failed"}


# ---------------------------------------------------------------------------
# AdvisoryRolloutConfig (#893)
# ---------------------------------------------------------------------------

class TestAdvisoryRolloutConfig:
    def test_default_not_enabled(self):
        assert DEFAULT_ADVISORY_CONFIG.enabled is False

    def test_default_should_emit_false(self):
        assert DEFAULT_ADVISORY_CONFIG.should_emit is False

    def test_default_is_gate_false(self):
        assert DEFAULT_ADVISORY_CONFIG.is_gate is False

    def test_enabled_config_enabled(self):
        assert ENABLED_CFG.enabled is True

    def test_enabled_config_should_emit_true(self):
        assert ENABLED_CFG.should_emit is True

    def test_enabled_config_is_gate_false(self):
        assert ENABLED_CFG.is_gate is False

    def test_target_run_statuses_contains_failed(self):
        assert "failed" in DEFAULT_ADVISORY_CONFIG.target_run_statuses

    def test_target_run_statuses_contains_blocked(self):
        assert "blocked" in DEFAULT_ADVISORY_CONFIG.target_run_statuses

    def test_target_run_statuses_excludes_passed(self):
        assert "passed" not in DEFAULT_ADVISORY_CONFIG.target_run_statuses

    def test_report_targets_mission_execution(self):
        assert "mission_execution" in ADVISORY_REPORT_TARGETS

    def test_report_targets_diagnostic(self):
        assert "diagnostic" in ADVISORY_REPORT_TARGETS

    def test_report_targets_shadow_cycle(self):
        assert "shadow_cycle" in ADVISORY_REPORT_TARGETS

    def test_to_dict_contains_expected_keys(self):
        d = DEFAULT_ADVISORY_CONFIG.to_dict()
        for k in ("enabled", "is_gate", "should_emit", "target_run_statuses", "target_report_types"):
            assert k in d

    def test_advisory_config_from_env_default_off(self, monkeypatch):
        monkeypatch.delenv("ADVISORY_ROLLOUT_ENABLED", raising=False)
        cfg = advisory_config_from_env()
        assert cfg.enabled is False

    def test_advisory_config_from_env_enabled(self, monkeypatch):
        monkeypatch.setenv("ADVISORY_ROLLOUT_ENABLED", "true")
        cfg = advisory_config_from_env()
        assert cfg.enabled is True
        assert cfg.is_gate is False


# ---------------------------------------------------------------------------
# should_emit_for_run (#893)
# ---------------------------------------------------------------------------

class TestShouldEmitForRun:
    def test_disabled_always_false_failed(self):
        assert should_emit_for_run("failed", "partial", DEFAULT_ADVISORY_CONFIG) is False

    def test_disabled_always_false_blocked(self):
        assert should_emit_for_run("blocked", "failed", DEFAULT_ADVISORY_CONFIG) is False

    def test_enabled_failed_partial(self):
        assert should_emit_for_run("failed", "partial", ENABLED_CFG) is True

    def test_enabled_failed_failed(self):
        assert should_emit_for_run("failed", "failed", ENABLED_CFG) is True

    def test_enabled_failed_completed(self):
        assert should_emit_for_run("failed", "completed", ENABLED_CFG) is True

    def test_enabled_blocked_partial(self):
        assert should_emit_for_run("blocked", "partial", ENABLED_CFG) is True

    def test_passed_completed_excluded(self):
        assert should_emit_for_run("passed", "completed", ENABLED_CFG) is False

    def test_passed_partial_excluded_by_default(self):
        assert should_emit_for_run("passed", "partial", ENABLED_CFG) is False

    def test_passed_partial_included_when_flag_set(self):
        cfg = make_advisory_enabled_config(include_passed_goal_incomplete=True)
        assert should_emit_for_run("passed", "partial", cfg) is True

    def test_none_run_status_disabled(self):
        assert should_emit_for_run(None, "partial", DEFAULT_ADVISORY_CONFIG) is False

    def test_none_run_status_enabled(self):
        assert should_emit_for_run(None, "partial", ENABLED_CFG) is False


# ---------------------------------------------------------------------------
# enrich_report_with_advisory (#894)
# ---------------------------------------------------------------------------

class TestEnrichReportWithAdvisory:
    def test_default_config_unchanged(self):
        r = enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                         advisory_config=DEFAULT_ADVISORY_CONFIG)
        assert r == BASE
        assert not has_advisory(r)

    def test_enabled_has_advisory(self):
        r = enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        assert has_advisory(r)

    def test_auto_executable_false(self):
        r = enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        assert r["recovery_recommendation"]["auto_executable"] is False

    def test_advisory_only_true(self):
        r = enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        assert r["recovery_recommendation"]["advisory_only"] is True

    def test_original_fields_preserved(self):
        base = {"run_id": "test", "outcome": "failed", "custom": "value"}
        r = enrich_report_with_advisory(base, run_status="failed", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        assert validate_no_original_fields_modified(base, r)

    def test_passed_completed_no_advisory(self):
        r = enrich_report_with_advisory(BASE, run_status="passed", goal_status="completed",
                                         advisory_config=ENABLED_CFG)
        assert not has_advisory(r)

    def test_bridge_diagnostics_present(self):
        r = enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        assert "bridge_diagnostics" in r

    def test_bridge_is_gate_false(self):
        r = enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        assert r["bridge_diagnostics"]["is_gate"] is False

    def test_bridge_affects_loop_decision_false(self):
        r = enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        assert r["bridge_diagnostics"]["affects_loop_decision"] is False

    def test_blocked_run_gets_advisory(self):
        r = enrich_report_with_advisory(BASE, run_status="blocked", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        assert has_advisory(r)


# ---------------------------------------------------------------------------
# Rollback (#896)
# ---------------------------------------------------------------------------

class TestRollback:
    def _enriched(self):
        return enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                            advisory_config=ENABLED_CFG)

    def test_rollback_removes_advisory(self):
        rb = rollback(self._enriched())
        assert not has_advisory(rb)

    def test_rollback_removes_bridge_diagnostics(self):
        rb = rollback(self._enriched())
        assert "bridge_diagnostics" not in rb

    def test_rollback_preserves_original_fields(self):
        rb = rollback(self._enriched())
        assert rb["run_id"] == BASE["run_id"]

    def test_rollback_result_matches_original(self):
        rb = rollback(self._enriched())
        assert set(rb.keys()) == set(BASE.keys())

    def test_strip_advisory_removes_recommendation(self):
        stripped = strip_advisory(self._enriched())
        assert not has_advisory(stripped)

    def test_strip_advisory_preserves_run_id(self):
        stripped = strip_advisory(self._enriched())
        assert stripped["run_id"] == BASE["run_id"]


# ---------------------------------------------------------------------------
# validate_advisory_output (#896)
# ---------------------------------------------------------------------------

class TestValidateAdvisoryOutput:
    def test_valid_enriched_report(self):
        r = enrich_report_with_advisory(BASE, run_status="failed", goal_status="partial",
                                         advisory_config=ENABLED_CFG)
        v = validate_advisory_output(r)
        assert v["valid"] is True
        assert len(v["violations"]) == 0

    def test_report_without_advisory_is_valid(self):
        v = validate_advisory_output({"run_id": "test"})
        assert v["valid"] is True

    def test_auto_executable_true_violation(self):
        r = {"recovery_recommendation": {
            "auto_executable": True, "advisory_only": True,
            "action": "diagnose_failure", "confidence": "high",
            "safe_next_action": "do something",
        }}
        v = validate_advisory_output(r)
        assert v["valid"] is False
        assert any("auto_executable" in s for s in v["violations"])

    def test_advisory_only_false_violation(self):
        r = {"recovery_recommendation": {
            "auto_executable": False, "advisory_only": False,
            "action": "diagnose_failure", "confidence": "high",
            "safe_next_action": "do something",
        }}
        v = validate_advisory_output(r)
        assert v["valid"] is False

    def test_bridge_affects_loop_violation(self):
        r = {"bridge_diagnostics": {"affects_loop_decision": True, "is_gate": False}}
        v = validate_advisory_output(r)
        assert v["valid"] is False

    def test_bridge_is_gate_violation(self):
        r = {"bridge_diagnostics": {"affects_loop_decision": False, "is_gate": True}}
        v = validate_advisory_output(r)
        assert v["valid"] is False


# ---------------------------------------------------------------------------
# Dataset replay (#895)
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
        return [enrich_cycle_with_advisory(c, advisory_config=ENABLED_CFG) for c in cycles]

    def test_all_enriched(self, enriched):
        assert all(has_advisory(r) for r in enriched)

    def test_zero_auto_exec_violations(self, enriched):
        viol = [r for r in enriched if r["recovery_recommendation"].get("auto_executable") is not False]
        assert len(viol) == 0

    def test_zero_advisory_only_violations(self, enriched):
        viol = [r for r in enriched if r["recovery_recommendation"].get("advisory_only") is not True]
        assert len(viol) == 0

    def test_zero_loop_decision_violations(self, enriched):
        viol = [r for r in enriched
                if r.get("bridge_diagnostics", {}).get("affects_loop_decision") is not False]
        assert len(viol) == 0

    def test_zero_is_gate_violations(self, enriched):
        viol = [r for r in enriched
                if r.get("bridge_diagnostics", {}).get("is_gate") is not False]
        assert len(viol) == 0

    def test_all_valid(self, enriched):
        for r in enriched:
            v = validate_advisory_output(r)
            assert v["valid"], f"violations: {v['violations']}"

    def test_aggregate_no_violations(self):
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
        agg = aggregate_advisory_cycles(cycles, advisory_config=ENABLED_CFG)
        assert agg["auto_executable_violations"] == 0
        assert agg["loop_decision_violations"]   == 0
        assert agg["is_gate_violations"]         == 0

    def test_default_config_no_advisory(self):
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
        default_enriched = [enrich_cycle_with_advisory(c, advisory_config=DEFAULT_ADVISORY_CONFIG)
                            for c in cycles]
        assert not any(has_advisory(r) for r in default_enriched)


# ---------------------------------------------------------------------------
# Consolidated report (#897)
# ---------------------------------------------------------------------------

class TestConsolidatedReport:
    @pytest.fixture(scope="class")
    def report(self):
        p = Path("reports/mission_brain/advisory_rollout/897/advisory_rollout_consolidated_897.json")
        if not p.exists():
            pytest.skip("Run run_advisory_rollout_consolidated_897.py first.")
        return json.loads(p.read_text())

    def test_final_decision_allowed(self, report):
        allowed = {
            "keep_advisory_disabled", "keep_diagnostic_only",
            "candidate_for_broader_advisory_rollout", "continue_calibration",
            "remediate_again", "do_not_integrate",
        }
        assert report["final_decision"] in allowed

    def test_not_activated(self, report):
        assert report["guardrails"]["candidate_does_not_mean_activated"] is True

    def test_advisory_only_guardrail(self, report):
        assert report["guardrails"]["advisory_only"] is True

    def test_no_auto_execution_guardrail(self, report):
        assert report["guardrails"]["no_auto_execution"] is True

    def test_default_off_guardrail(self, report):
        assert report["guardrails"]["default_off"] is True

    def test_rollback_immediate_guardrail(self, report):
        assert report["guardrails"]["rollback_immediate"] is True

    def test_auto_exec_violations_zero(self, report):
        assert report["auto_executable_violations"] == 0

    def test_loop_decision_violations_zero(self, report):
        assert report["loop_decision_violations"] == 0

    def test_epic_complete(self, report):
        assert report["epic_status"] == "complete"

    def test_gate_chain_passed(self, report):
        assert report["gate_chain_passed"] is True

    def test_all_subissues_completed(self, report):
        assert set(report["subissues_completed"]) == {893, 894, 895, 896, 897}

    def test_invariants_checked(self, report):
        assert report["invariants_checked"] >= 8

    def test_cycles_validated(self, report):
        assert report["total_cycles_validated"] == 30
