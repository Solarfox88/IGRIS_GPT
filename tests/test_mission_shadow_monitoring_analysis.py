from __future__ import annotations

from igris.agent.mission.shadow_monitoring_analysis import analyze_disagreements


def test_analyze_disagreements_counts_and_classes():
    rows = [
        {"agreement": False, "mismatch_class": "safe_more_optimistic_mission_brain", "prevented_error_candidate": True},
        {"agreement": False, "mismatch_class": "safe_more_optimistic_mission_brain", "prevented_error_candidate": True},
        {"agreement": True, "mismatch_class": "agreement"},
    ]
    out = analyze_disagreements(rows)
    assert out["total_cycles"] == 3
    assert out["disagreement_count"] == 2
    assert out["dominant_mismatch_class"] == "safe_more_optimistic_mission_brain"
    assert out["prevented_error_candidates"] == 2
    assert out["risk_introduced_candidates"] == 0

