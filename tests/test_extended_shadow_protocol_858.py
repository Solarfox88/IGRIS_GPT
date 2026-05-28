"""Tests for Extended Shadow Monitoring Protocol — Epic #857, Subissue #858.

Verifies:
- Extended aggregate schema contains all required new fields
- Extended protocol document declares all allowed/forbidden decisions
- Shadow flag is OFF by default (hard constraint)
- Rollback path config is intact
- aggregate_shadow_cycles() now returns extended fields
- decide_extended_shadow_outcome() returns only allowed decisions
- decide_extended_shadow_outcome() never returns forbidden decisions
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(rel_path: str) -> dict:
    return json.loads((ROOT / rel_path).read_text(encoding="utf-8"))


def _make_cycle(
    agreement: bool = False,
    mismatch_class: str = "other_mismatch",
    prevented: bool = False,
    risk: bool = False,
    pfc: bool = False,
    pcfc: bool = False,
    pfp: bool = False,
    pff: bool = False,
    latency_ms: float = 1.0,
    cost_usd: float = 0.0,
    rollback_status: str = "ok",
    usefulness: float = 0.8,
    mb_decision: str = "partial",
    loop_decision: str = "completed",
    goal_class: str = "policy_check",
) -> dict:
    return {
        "cycle_id": "test",
        "agreement": agreement,
        "mismatch_class": mismatch_class,
        "prevented_error_candidate": prevented,
        "risk_introduced_candidate": risk,
        "potential_false_completed": pfc,
        "potential_critical_false_completed": pcfc,
        "potential_false_partial": pfp,
        "potential_false_failed": pff,
        "latency_overhead_ms": latency_ms,
        "cost_overhead_usd": cost_usd,
        "rollback_path_status": rollback_status,
        "report_usefulness_score": usefulness,
        "mission_brain_decision": mb_decision,
        "current_loop_decision": loop_decision,
        "goal_class": goal_class,
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestExtendedSchema:

    def test_extended_schema_exists(self):
        path = ROOT / "reports/mission_brain/shadow_monitoring/extended_aggregate_metrics_schema.json"
        assert path.exists(), "Extended schema file must exist"

    def test_extended_schema_has_new_fields(self):
        schema = _load_json("reports/mission_brain/shadow_monitoring/extended_aggregate_metrics_schema.json")
        new_fields = {
            "disagreement_by_class",
            "decision_distribution_mission_brain",
            "decision_distribution_current_loop",
            "dominant_mismatch_classes",
            "sample_representativeness_score",
            "sample_representativeness_notes",
        }
        assert new_fields.issubset(schema.keys()), \
            f"Missing fields: {new_fields - schema.keys()}"

    def test_extended_schema_retains_original_fields(self):
        schema = _load_json("reports/mission_brain/shadow_monitoring/extended_aggregate_metrics_schema.json")
        original_fields = {
            "total_shadow_cycles", "agreement_rate", "disagreement_rate",
            "prevented_error_candidates", "risk_introduced_candidates",
            "potential_false_completed", "potential_critical_false_completed",
            "latency_overhead", "cost_overhead", "rollback_path_status",
            "final_readiness_trend",
        }
        assert original_fields.issubset(schema.keys())

    def test_extended_schema_allowed_decisions_updated(self):
        schema = _load_json("reports/mission_brain/shadow_monitoring/extended_aggregate_metrics_schema.json")
        decision_str = schema.get("allowed_final_decision", "")
        assert "extend monitoring again" in decision_str
        assert "start disagreement calibration" in decision_str
        # Forbidden decision must NOT be in allowed list
        assert "enable by default" not in decision_str


# ---------------------------------------------------------------------------
# Protocol document
# ---------------------------------------------------------------------------

class TestExtendedProtocolDoc:

    def test_protocol_document_exists(self):
        path = ROOT / "docs/mission_brain/extended_shadow_protocol.md"
        assert path.exists()

    def test_protocol_declares_all_allowed_decisions(self):
        text = (ROOT / "docs/mission_brain/extended_shadow_protocol.md").read_text(encoding="utf-8")
        for decision in [
            "keep shadow mode",
            "extend monitoring again",
            "start disagreement calibration",
            "remediate again",
            "do not integrate",
        ]:
            assert decision in text, f"Missing decision: {decision}"

    def test_protocol_declares_forbidden_decisions(self):
        text = (ROOT / "docs/mission_brain/extended_shadow_protocol.md").read_text(encoding="utf-8")
        for forbidden in [
            "enable by default",
            "controlled rollout activation",
            "mandatory gate integration",
        ]:
            assert forbidden in text, f"Missing forbidden decision: {forbidden}"

    def test_protocol_declares_stop_conditions(self):
        text = (ROOT / "docs/mission_brain/extended_shadow_protocol.md").read_text(encoding="utf-8")
        assert "Stop Conditions" in text
        assert "potential_critical_false_completed" in text

    def test_protocol_declares_constraints(self):
        text = (ROOT / "docs/mission_brain/extended_shadow_protocol.md").read_text(encoding="utf-8")
        assert "Shadow mode only" in text or "shadow mode only" in text.lower()
        assert "enabled" in text
        assert "False" in text or "false" in text.lower()


# ---------------------------------------------------------------------------
# Shadow flag / rollback path (hard constraints)
# ---------------------------------------------------------------------------

class TestHardConstraints:

    def test_shadow_flag_off_by_default(self):
        from igris.models.config import MissionBrainIntegrationConfig
        cfg = MissionBrainIntegrationConfig()
        assert cfg.enabled is False, "Mission Brain must be DISABLED by default"

    def test_mode_is_shadow_by_default(self):
        from igris.models.config import MissionBrainIntegrationConfig
        cfg = MissionBrainIntegrationConfig()
        assert cfg.mode == "shadow"

    def test_rollback_to_wrapper_enabled_by_default(self):
        from igris.models.config import MissionBrainIntegrationConfig
        cfg = MissionBrainIntegrationConfig()
        assert cfg.rollback_to_wrapper_on_guardrail is True

    def test_enforce_mode_not_allowed_by_default(self):
        from igris.models.config import MissionBrainIntegrationConfig
        cfg = MissionBrainIntegrationConfig()
        assert cfg.allow_enforce_mode is False


# ---------------------------------------------------------------------------
# aggregate_shadow_cycles — extended fields
# ---------------------------------------------------------------------------

class TestAggregateExtendedFields:

    def test_returns_disagreement_by_class(self):
        from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles
        cycles = [
            _make_cycle(agreement=False, mismatch_class="safe_more_optimistic_mission_brain"),
            _make_cycle(agreement=False, mismatch_class="safe_more_optimistic_mission_brain"),
            _make_cycle(agreement=False, mismatch_class="risky_overclaim_by_mission_brain"),
        ]
        result = aggregate_shadow_cycles(cycles)
        assert "disagreement_by_class" in result
        assert result["disagreement_by_class"]["safe_more_optimistic_mission_brain"] == 2
        assert result["disagreement_by_class"]["risky_overclaim_by_mission_brain"] == 1

    def test_returns_dominant_mismatch_classes(self):
        from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles
        cycles = [_make_cycle(agreement=False, mismatch_class="class_a")] * 5 + \
                 [_make_cycle(agreement=False, mismatch_class="class_b")] * 3 + \
                 [_make_cycle(agreement=False, mismatch_class="class_c")] * 1
        result = aggregate_shadow_cycles(cycles)
        assert result["dominant_mismatch_classes"][0] == "class_a"
        assert len(result["dominant_mismatch_classes"]) <= 3

    def test_returns_decision_distributions(self):
        from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles
        cycles = [
            _make_cycle(mb_decision="partial", loop_decision="completed"),
            _make_cycle(mb_decision="completed", loop_decision="completed"),
        ]
        result = aggregate_shadow_cycles(cycles)
        assert "decision_distribution_mission_brain" in result
        assert "decision_distribution_current_loop" in result

    def test_returns_representativeness_score(self):
        from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles
        diverse_cycles = [
            _make_cycle(goal_class=cls)
            for cls in ["policy_check", "risk_assessment", "planning",
                        "verification", "loop_coherence"]
        ]
        result = aggregate_shadow_cycles(diverse_cycles)
        assert "sample_representativeness_score" in result
        assert result["sample_representativeness_score"] > 0.0

    def test_single_class_has_low_representativeness(self):
        from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles
        cycles = [_make_cycle(goal_class="policy_check")] * 10
        result = aggregate_shadow_cycles(cycles)
        # All same class → low representativeness
        assert result["sample_representativeness_score"] < 0.5

    def test_backward_compatible_with_existing_fields(self):
        from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles
        cycles = [_make_cycle()]
        result = aggregate_shadow_cycles(cycles)
        for field in [
            "total_shadow_cycles", "agreement_rate", "disagreement_rate",
            "prevented_error_candidates", "risk_introduced_candidates",
            "potential_false_completed", "potential_critical_false_completed",
            "latency_overhead", "cost_overhead", "rollback_path_status",
            "final_readiness_trend",
        ]:
            assert field in result, f"Missing backward-compatible field: {field}"


# ---------------------------------------------------------------------------
# decide_extended_shadow_outcome
# ---------------------------------------------------------------------------

class TestDecideExtendedOutcome:

    def test_never_returns_forbidden_decision(self):
        from igris.agent.mission.shadow_monitoring_decision import (
            decide_extended_shadow_outcome,
            FORBIDDEN_DECISIONS,
        )
        # Try various metric combinations
        for agreement in [0.0, 0.5, 1.0]:
            for risk in [0, 1]:
                for critical in [0, 1]:
                    metrics = {
                        "agreement_rate": agreement,
                        "disagreement_rate": 1.0 - agreement,
                        "potential_critical_false_completed": critical,
                        "risk_introduced_candidates": risk,
                        "rollback_path_status": "ok",
                        "final_readiness_trend": "stable",
                        "sample_representativeness_score": 0.8,
                    }
                    decision = decide_extended_shadow_outcome(metrics, cumulative_cycles=30)
                    assert decision not in FORBIDDEN_DECISIONS, \
                        f"Forbidden decision returned: {decision}"

    def test_only_returns_allowed_decisions(self):
        from igris.agent.mission.shadow_monitoring_decision import (
            decide_extended_shadow_outcome,
            ALLOWED_DECISIONS,
        )
        metrics = {
            "agreement_rate": 0.0,
            "disagreement_rate": 1.0,
            "potential_critical_false_completed": 0,
            "risk_introduced_candidates": 0,
            "rollback_path_status": "ok",
            "final_readiness_trend": "stable",
            "sample_representativeness_score": 0.7,
        }
        decision = decide_extended_shadow_outcome(metrics, cumulative_cycles=30)
        assert decision in ALLOWED_DECISIONS

    def test_critical_false_completed_triggers_do_not_integrate(self):
        from igris.agent.mission.shadow_monitoring_decision import decide_extended_shadow_outcome
        metrics = {
            "agreement_rate": 0.0,
            "disagreement_rate": 1.0,
            "potential_critical_false_completed": 1,
            "risk_introduced_candidates": 0,
            "rollback_path_status": "ok",
            "final_readiness_trend": "stable",
            "sample_representativeness_score": 0.8,
        }
        assert decide_extended_shadow_outcome(metrics, cumulative_cycles=30) == "do not integrate"

    def test_failed_rollback_triggers_remediate(self):
        from igris.agent.mission.shadow_monitoring_decision import decide_extended_shadow_outcome
        metrics = {
            "agreement_rate": 0.0,
            "disagreement_rate": 1.0,
            "potential_critical_false_completed": 0,
            "risk_introduced_candidates": 0,
            "rollback_path_status": "failed",
            "final_readiness_trend": "stable",
            "sample_representativeness_score": 0.8,
        }
        assert decide_extended_shadow_outcome(metrics, cumulative_cycles=30) == "remediate again"

    def test_insufficient_cycles_triggers_extend(self):
        from igris.agent.mission.shadow_monitoring_decision import decide_extended_shadow_outcome
        metrics = {
            "agreement_rate": 0.0,
            "disagreement_rate": 1.0,
            "potential_critical_false_completed": 0,
            "risk_introduced_candidates": 0,
            "rollback_path_status": "ok",
            "final_readiness_trend": "stable",
            "sample_representativeness_score": 0.8,
        }
        # Only 20 cycles — not enough
        assert decide_extended_shadow_outcome(metrics, cumulative_cycles=20) == "extend monitoring again"

    def test_zero_agreement_stable_30_cycles_rep_ok_triggers_calibration(self):
        from igris.agent.mission.shadow_monitoring_decision import decide_extended_shadow_outcome
        metrics = {
            "agreement_rate": 0.0,
            "disagreement_rate": 1.0,
            "potential_critical_false_completed": 0,
            "risk_introduced_candidates": 0,
            "rollback_path_status": "ok",
            "final_readiness_trend": "stable",
            "sample_representativeness_score": 0.7,
        }
        # 30 cycles, rep >= 0.5, stable zero agreement → calibrate
        decision = decide_extended_shadow_outcome(metrics, cumulative_cycles=30)
        assert decision == "start disagreement calibration"

    def test_backward_compatible_original_function(self):
        """decide_shadow_monitoring_outcome still works for #845 callers."""
        from igris.agent.mission.shadow_monitoring_decision import decide_shadow_monitoring_outcome
        metrics = {
            "agreement_rate": 0.0,
            "disagreement_rate": 1.0,
            "potential_critical_false_completed": 0,
            "risk_introduced_candidates": 0,
            "rollback_path_status": "ok",
        }
        result = decide_shadow_monitoring_outcome(metrics)
        assert result in {"keep shadow mode", "candidate for controlled rollout",
                          "remediate again", "do not integrate"}
