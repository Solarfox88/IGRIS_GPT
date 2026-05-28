"""Tests for Extended Shadow Monitoring Batch 2 — Epic #857, Subissue #860.

Verifies:
- Batch 2 results file exists and is valid
- No stop conditions triggered
- All required metrics fields present (original + extended)
- Trend direction field present
- Representativeness >= 0.8 (10 distinct goal classes including edge cases)
- Safety guardrails maintained
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BATCH2_AGG = ROOT / "reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_aggregate_860.json"
BATCH2_CYCLES = ROOT / "reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_cycles_860.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestBatch2Artifacts:

    def test_aggregate_file_exists(self):
        assert BATCH2_AGG.exists()

    def test_cycles_file_exists(self):
        assert BATCH2_CYCLES.exists()

    def test_report_file_exists(self):
        md = ROOT / "reports/mission_brain/shadow_monitoring/860/extended_shadow_batch2_report_860.md"
        assert md.exists()


class TestBatch2Metrics:

    def test_has_required_original_fields(self):
        m = _load(BATCH2_AGG)
        for field in [
            "total_shadow_cycles", "agreement_rate", "disagreement_rate",
            "prevented_error_candidates", "risk_introduced_candidates",
            "potential_false_completed", "potential_critical_false_completed",
            "latency_overhead", "cost_overhead", "rollback_path_status",
            "final_readiness_trend",
        ]:
            assert field in m, f"Missing field: {field}"

    def test_has_required_extended_fields(self):
        m = _load(BATCH2_AGG)
        for field in [
            "disagreement_by_class",
            "decision_distribution_mission_brain",
            "decision_distribution_current_loop",
            "dominant_mismatch_classes",
            "sample_representativeness_score",
        ]:
            assert field in m, f"Missing extended field: {field}"

    def test_has_trend_direction_field(self):
        m = _load(BATCH2_AGG)
        assert "trend_direction_vs_batch1" in m

    def test_has_batch1_agreement_rate(self):
        m = _load(BATCH2_AGG)
        assert "batch1_agreement_rate" in m

    def test_batch_cycles_count(self):
        m = _load(BATCH2_AGG)
        assert m["total_shadow_cycles"] == 10

    def test_representativeness_high(self):
        m = _load(BATCH2_AGG)
        assert m["sample_representativeness_score"] >= 0.8

    def test_rollback_path_ok(self):
        m = _load(BATCH2_AGG)
        assert m["rollback_path_status"] == "ok"

    def test_cost_overhead_zero(self):
        m = _load(BATCH2_AGG)
        assert m["cost_overhead"]["total_usd"] == 0.0


class TestBatch2StopConditions:

    def test_no_critical_false_completed(self):
        m = _load(BATCH2_AGG)
        assert m["potential_critical_false_completed"] == 0

    def test_no_risk_introduced(self):
        m = _load(BATCH2_AGG)
        assert m["risk_introduced_candidates"] == 0

    def test_no_cycles_have_critical_false_completed(self):
        cycles = json.loads(BATCH2_CYCLES.read_text(encoding="utf-8"))
        for c in cycles:
            assert not c.get("potential_critical_false_completed"), \
                f"STOP: cycle {c['cycle_id']} triggered critical_false_completed"

    def test_all_cycles_rollback_ok(self):
        cycles = json.loads(BATCH2_CYCLES.read_text(encoding="utf-8"))
        for c in cycles:
            assert c["rollback_path_status"] == "ok"


class TestBatch2PatternStability:

    def test_trend_direction_is_valid(self):
        m = _load(BATCH2_AGG)
        assert m["trend_direction_vs_batch1"] in {"improving", "stable", "worsening"}

    def test_disagreement_still_majority(self):
        m = _load(BATCH2_AGG)
        assert m["disagreement_rate"] >= 0.5

    def test_cycles_include_edge_cases(self):
        cycles = json.loads(BATCH2_CYCLES.read_text(encoding="utf-8"))
        classes = {c["goal_class"] for c in cycles}
        edge_cases = {"ambiguous_goal", "empty_context", "conflicting_signals"}
        assert edge_cases.issubset(classes), \
            f"Missing edge case goal classes: {edge_cases - classes}"

    def test_cycles_include_reprise_classes(self):
        """Batch 2 must include 3 goal classes from #845 baseline."""
        cycles = json.loads(BATCH2_CYCLES.read_text(encoding="utf-8"))
        classes = {c["goal_class"] for c in cycles}
        reprise = {"policy_check", "risk_assessment", "verification"}
        assert reprise.issubset(classes), \
            f"Missing reprise classes: {reprise - classes}"

    def test_10_distinct_goal_classes(self):
        cycles = json.loads(BATCH2_CYCLES.read_text(encoding="utf-8"))
        classes = {c["goal_class"] for c in cycles}
        assert len(classes) == 10
