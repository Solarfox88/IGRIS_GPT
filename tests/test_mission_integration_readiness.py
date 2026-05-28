from __future__ import annotations

from igris.agent.mission.integration_readiness import (
    build_readiness_payload,
    decide_integration_readiness,
)


def test_decision_do_not_integrate_on_critical_false_completed():
    d = decide_integration_readiness(
        risky_mismatch_count=0,
        agreement_rate=1.0,
        critical_false_completed_count=1,
        rollback_policy_working=True,
    )
    assert d == "do not integrate"


def test_decision_controlled_rollout_candidate():
    d = decide_integration_readiness(
        risky_mismatch_count=0,
        agreement_rate=0.85,
        critical_false_completed_count=0,
        rollback_policy_working=True,
    )
    assert d == "controlled rollout candidate"


def test_decision_keep_shadow_mode():
    d = decide_integration_readiness(
        risky_mismatch_count=1,
        agreement_rate=0.4,
        critical_false_completed_count=0,
        rollback_policy_working=True,
    )
    assert d == "keep shadow mode"


def test_decision_remediate_again_without_rollback():
    d = decide_integration_readiness(
        risky_mismatch_count=2,
        agreement_rate=0.4,
        critical_false_completed_count=0,
        rollback_policy_working=False,
    )
    assert d == "remediate again"


def test_build_payload_uses_inputs():
    payload = build_readiness_payload(
        shadow_summary={"risky_mismatch_count": 2, "agreement_rate": 0.5},
        rollback_summary={"wrapper_effective_count": 3},
        critical_false_completed_count=0,
    )
    assert payload["decision"] == "keep shadow mode"
    assert payload["shadow_summary"]["risky_mismatch_count"] == 2

