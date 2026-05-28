from __future__ import annotations

from igris.agent.mission.shadow_comparison import (
    classify_mismatch,
    compare_shadow_records,
)


def test_classify_mismatch_agreement():
    assert classify_mismatch("completed", "completed") == "agreement"


def test_classify_mismatch_risky_false_completed_candidate():
    assert (
        classify_mismatch("completed", "failed")
        == "risky_false_completed_candidate"
    )


def test_classify_mismatch_risky_overclaim():
    assert (
        classify_mismatch("failed", "completed")
        == "risky_overclaim_by_mission_brain"
    )


def test_compare_shadow_records_metrics():
    rows = [
        {
            "loop_decision": "completed",
            "mission_brain_decision": "completed",
            "quality_gate_passed": True,
            "satisfaction_gate_passed": True,
        },
        {
            "loop_decision": "completed",
            "mission_brain_decision": "failed",
            "quality_gate_passed": False,
            "satisfaction_gate_passed": False,
        },
        {
            "loop_decision": "failed",
            "mission_brain_decision": "completed",
            "quality_gate_passed": True,
            "satisfaction_gate_passed": False,
        },
    ]
    out = compare_shadow_records(rows).to_dict()
    assert out["total_runs"] == 3
    assert out["agreement_count"] == 1
    assert out["disagreement_count"] == 2
    assert out["risky_mismatch_count"] == 2
    assert out["quality_gate_pass_rate"] == 0.667
    assert out["satisfaction_gate_pass_rate"] == 0.333

