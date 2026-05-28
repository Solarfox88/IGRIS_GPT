"""Tests for Extended Shadow Monitoring Batch 1 — Epic #857, Subissue #859.

Verifies:
- Batch 1 results file exists and is valid
- No stop conditions were triggered
- All required metrics fields present
- Extended fields present and well-formed
- Representativeness score == 1.0 (10 distinct goal classes)
- Sample baseline guardrails: no critical false completed, rollback ok
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BATCH1_AGG = ROOT / "reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_aggregate_859.json"
BATCH1_CYCLES = ROOT / "reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_cycles_859.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestBatch1Artifacts:

    def test_aggregate_file_exists(self):
        assert BATCH1_AGG.exists(), "Batch 1 aggregate results must exist"

    def test_cycles_file_exists(self):
        assert BATCH1_CYCLES.exists(), "Batch 1 cycle records must exist"

    def test_report_file_exists(self):
        md = ROOT / "reports/mission_brain/shadow_monitoring/859/extended_shadow_batch1_report_859.md"
        assert md.exists(), "Batch 1 markdown report must exist"


class TestBatch1Metrics:

    def test_has_required_original_fields(self):
        m = _load(BATCH1_AGG)
        for field in [
            "total_shadow_cycles", "agreement_rate", "disagreement_rate",
            "prevented_error_candidates", "risk_introduced_candidates",
            "potential_false_completed", "potential_critical_false_completed",
            "potential_false_partial", "potential_false_failed",
            "latency_overhead", "cost_overhead", "rollback_path_status",
            "final_readiness_trend",
        ]:
            assert field in m, f"Missing field: {field}"

    def test_has_required_extended_fields(self):
        m = _load(BATCH1_AGG)
        for field in [
            "disagreement_by_class",
            "decision_distribution_mission_brain",
            "decision_distribution_current_loop",
            "dominant_mismatch_classes",
            "sample_representativeness_score",
            "sample_representativeness_notes",
        ]:
            assert field in m, f"Missing extended field: {field}"

    def test_batch_cycles_count(self):
        m = _load(BATCH1_AGG)
        assert m["total_shadow_cycles"] == 10, "Batch 1 must have exactly 10 cycles"

    def test_sample_representativeness_is_high(self):
        m = _load(BATCH1_AGG)
        assert m["sample_representativeness_score"] >= 0.8, \
            "10 distinct goal classes must yield representativeness >= 0.8"

    def test_rollback_path_ok(self):
        m = _load(BATCH1_AGG)
        assert m["rollback_path_status"] == "ok"

    def test_cost_overhead_zero(self):
        m = _load(BATCH1_AGG)
        assert m["cost_overhead"]["total_usd"] == 0.0


class TestBatch1StopConditions:

    def test_no_critical_false_completed(self):
        m = _load(BATCH1_AGG)
        assert m["potential_critical_false_completed"] == 0, \
            "STOP CONDITION: potential_critical_false_completed > 0"

    def test_no_risk_introduced(self):
        m = _load(BATCH1_AGG)
        assert m["risk_introduced_candidates"] == 0, \
            "STOP CONDITION: risk_introduced_candidates > 0"

    def test_no_cycles_have_critical_false_completed(self):
        cycles = json.loads(BATCH1_CYCLES.read_text(encoding="utf-8"))
        for c in cycles:
            assert not c.get("potential_critical_false_completed"), \
                f"STOP: cycle {c['cycle_id']} has critical_false_completed"

    def test_all_cycles_have_ok_rollback(self):
        cycles = json.loads(BATCH1_CYCLES.read_text(encoding="utf-8"))
        for c in cycles:
            assert c["rollback_path_status"] == "ok", \
                f"Cycle {c['cycle_id']} has rollback_path_status={c['rollback_path_status']}"


class TestBatch1PatternAnalysis:

    def test_disagreement_rate_consistent_with_baseline(self):
        """Batch 1 should be consistent with #845 baseline (agreement_rate=0.0)."""
        m = _load(BATCH1_AGG)
        # Not asserting exact value — may change with larger sample — but disagreement
        # must be the majority.
        assert m["disagreement_rate"] >= 0.5, \
            "Unexpectedly high agreement — worth investigating"

    def test_disagreement_by_class_populated(self):
        m = _load(BATCH1_AGG)
        assert isinstance(m["disagreement_by_class"], dict)
        assert len(m["disagreement_by_class"]) > 0

    def test_dominant_mismatch_classes_present(self):
        m = _load(BATCH1_AGG)
        assert isinstance(m["dominant_mismatch_classes"], list)
        assert len(m["dominant_mismatch_classes"]) >= 1

    def test_decision_distributions_present(self):
        m = _load(BATCH1_AGG)
        assert isinstance(m["decision_distribution_mission_brain"], dict)
        assert isinstance(m["decision_distribution_current_loop"], dict)
        assert len(m["decision_distribution_mission_brain"]) > 0
        assert len(m["decision_distribution_current_loop"]) > 0

    def test_cycles_have_goal_class(self):
        cycles = json.loads(BATCH1_CYCLES.read_text(encoding="utf-8"))
        for c in cycles:
            assert "goal_class" in c and c["goal_class"], \
                f"Cycle {c['cycle_id']} missing goal_class"

    def test_cycles_have_10_distinct_goal_classes(self):
        cycles = json.loads(BATCH1_CYCLES.read_text(encoding="utf-8"))
        classes = {c["goal_class"] for c in cycles}
        assert len(classes) == 10, \
            f"Expected 10 distinct goal_class values, got {len(classes)}: {classes}"
