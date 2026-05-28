from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_json(rel_path: str):
    return json.loads((ROOT / rel_path).read_text(encoding="utf-8"))


def test_shadow_monitoring_aggregate_schema_contains_required_metrics():
    schema = _load_json("reports/mission_brain/shadow_monitoring/aggregate_metrics_schema.json")
    required = {
        "total_shadow_cycles",
        "mission_brain_decision",
        "current_loop_decision",
        "agreement_rate",
        "disagreement_rate",
        "prevented_error_candidates",
        "risk_introduced_candidates",
        "potential_false_completed",
        "potential_critical_false_completed",
        "potential_false_partial",
        "potential_false_failed",
        "report_usefulness_score",
        "latency_overhead",
        "cost_overhead",
        "rollback_path_status",
        "final_readiness_trend",
        "allowed_final_decision",
    }
    assert required.issubset(schema.keys())


def test_shadow_monitoring_cycle_template_contains_required_fields():
    template = _load_json("reports/mission_brain/shadow_monitoring/cycle_report_template.json")
    required = {
        "cycle_id",
        "timestamp",
        "mission_brain_decision",
        "current_loop_decision",
        "agreement",
        "mismatch_class",
        "prevented_error_candidate",
        "risk_introduced_candidate",
        "potential_false_completed",
        "potential_critical_false_completed",
        "potential_false_partial",
        "potential_false_failed",
        "latency_overhead_ms",
        "cost_overhead_usd",
        "rollback_path_status",
        "report_usefulness_score",
    }
    assert required.issubset(template.keys())


def test_protocol_declares_allowed_final_decisions():
    protocol_text = (ROOT / "docs/MISSION_BRAIN_SHADOW_MONITORING_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    assert "keep shadow mode" in protocol_text
    assert "candidate for controlled rollout" in protocol_text
    assert "remediate again" in protocol_text
    assert "do not integrate" in protocol_text

