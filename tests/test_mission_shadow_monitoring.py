from __future__ import annotations

from igris.agent.mission.shadow_monitoring import aggregate_shadow_cycles


def test_aggregate_shadow_cycles_metrics_shape():
    cycles = [
        {
            "agreement": True,
            "prevented_error_candidate": False,
            "risk_introduced_candidate": False,
            "potential_false_completed": False,
            "potential_critical_false_completed": False,
            "potential_false_partial": False,
            "potential_false_failed": False,
            "report_usefulness_score": 0.8,
            "latency_overhead_ms": 20.0,
            "cost_overhead_usd": 0.0,
            "rollback_path_status": "ok",
        },
        {
            "agreement": False,
            "prevented_error_candidate": True,
            "risk_introduced_candidate": False,
            "potential_false_completed": False,
            "potential_critical_false_completed": False,
            "potential_false_partial": True,
            "potential_false_failed": False,
            "report_usefulness_score": 0.7,
            "latency_overhead_ms": 30.0,
            "cost_overhead_usd": 0.0,
            "rollback_path_status": "degraded",
        },
    ]
    out = aggregate_shadow_cycles(cycles)
    assert out["total_shadow_cycles"] == 2
    assert out["agreement_rate"] == 0.5
    assert out["disagreement_rate"] == 0.5
    assert out["prevented_error_candidates"] == 1
    assert out["rollback_path_status"] == "degraded"

