from __future__ import annotations

from igris.agent.mission.rollback_policy import (
    evaluate_wrapper_policy,
    persist_wrapper_policy_decision,
)


def test_manual_force_wrapper_has_priority():
    out = evaluate_wrapper_policy(
        requested_mode="shadow",
        shadow_record={"mismatch_class": "agreement"},
        force_wrapper_mode=True,
    )
    assert out["effective_mode"] == "wrapper"
    assert out["manual_force_wrapper"] is True
    assert out["reason"] == "manual_force_wrapper_mode"


def test_risky_mismatch_triggers_auto_rollback():
    out = evaluate_wrapper_policy(
        requested_mode="shadow",
        shadow_record={"mismatch_class": "risky_false_completed_candidate"},
        rollback_to_wrapper_on_guardrail=True,
        auto_rollback_on_risky_mismatch=True,
    )
    assert out["effective_mode"] == "wrapper"
    assert out["auto_rollback_triggered"] is True
    assert out["reason"] == "risky_mismatch_guardrail"


def test_agreement_keeps_mode():
    out = evaluate_wrapper_policy(
        requested_mode="shadow",
        shadow_record={"mismatch_class": "agreement"},
    )
    assert out["effective_mode"] == "shadow"
    assert out["auto_rollback_triggered"] is False


def test_policy_persistence_jsonl(tmp_path):
    d = {"requested_mode": "shadow", "effective_mode": "wrapper", "reason": "test"}
    path = persist_wrapper_policy_decision(str(tmp_path), d)
    assert path.endswith("rollback_policy_decisions.jsonl")

