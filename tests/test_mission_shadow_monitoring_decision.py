from __future__ import annotations

from igris.agent.mission.shadow_monitoring_decision import decide_shadow_monitoring_outcome


def test_decision_do_not_integrate_on_critical():
    d = decide_shadow_monitoring_outcome(
        {
            "potential_critical_false_completed": 1,
            "risk_introduced_candidates": 0,
            "agreement_rate": 1.0,
            "rollback_path_status": "ok",
            "disagreement_rate": 0.0,
        }
    )
    assert d == "do not integrate"


def test_decision_candidate_for_controlled_rollout():
    d = decide_shadow_monitoring_outcome(
        {
            "potential_critical_false_completed": 0,
            "risk_introduced_candidates": 0,
            "agreement_rate": 0.9,
            "rollback_path_status": "ok",
            "disagreement_rate": 0.1,
        }
    )
    assert d == "candidate for controlled rollout"


def test_decision_keep_shadow_mode():
    d = decide_shadow_monitoring_outcome(
        {
            "potential_critical_false_completed": 0,
            "risk_introduced_candidates": 0,
            "agreement_rate": 0.5,
            "rollback_path_status": "ok",
            "disagreement_rate": 0.5,
        }
    )
    assert d == "keep shadow mode"

