"""Tests for shadow ML components (#1248) — IntentRiskShadowModel, StrategySelectorShadow, ShadowMLCoordinator."""
from __future__ import annotations
import json
import pytest


def _make_route_decision(route, risk, blocked=False, requires_approval=False):
    class FakeRD:
        pass
    rd = FakeRD()
    rd.route = route
    rd.risk = risk
    rd.blocked = blocked
    rd.requires_approval = requires_approval
    return rd


def _make_mission_plan(route="read_only_inspection", risk="low", blocked=False,
                       requires_approval=False, status="planned"):
    class FakePlan:
        pass
    p = FakePlan()
    p.route = route
    p.risk = risk
    p.blocked = blocked
    p.requires_approval = requires_approval
    p.status = status
    return p


def _make_bundle(status, ok):
    class FakeBundle:
        def __init__(self):
            self.status = status
            self.ok = ok
            self.results = []
    return FakeBundle()


def _make_reflection(outcome, confidence):
    class FakeReflection:
        pass
    r = FakeReflection()
    r.outcome = outcome
    r.confidence = confidence
    return r


# ── IntentRiskShadowModel ─────────────────────────────────────────────────────

def test_intent_shadow_classifies_destructive(tmp_path):
    from igris.core.shadow_ml import IntentRiskShadowModel
    m = IntentRiskShadowModel(project_root=tmp_path)
    report = m.evaluate("cancella database production")
    assert report.ok is True
    assert report.shadow_only is True
    assert report.shadow_decision["risk"] == "destructive"


def test_intent_shadow_classifies_deploy_high(tmp_path):
    from igris.core.shadow_ml import IntentRiskShadowModel
    m = IntentRiskShadowModel(project_root=tmp_path)
    report = m.evaluate("fai deploy in production")
    assert report.shadow_decision["risk"] == "high"
    assert report.shadow_decision["route"] == "deploy_operation"


def test_intent_shadow_classifies_memory_update(tmp_path):
    from igris.core.shadow_ml import IntentRiskShadowModel
    m = IntentRiskShadowModel(project_root=tmp_path)
    report = m.evaluate("ricordati che preferisco risposte brevi")
    assert report.shadow_decision["route"] == "memory_update"
    assert report.shadow_decision["risk"] == "low"


def test_intent_shadow_compares_with_baseline(tmp_path):
    from igris.core.shadow_ml import IntentRiskShadowModel
    m = IntentRiskShadowModel(project_root=tmp_path)
    baseline = _make_route_decision("read_only_inspection", "low")
    report = m.evaluate("controlla i log", baseline_route_decision=baseline)
    assert "baseline_decision" in report.to_dict()
    assert report.baseline_decision["route"] == "read_only_inspection"


def test_intent_shadow_disagreement_warns(tmp_path):
    from igris.core.shadow_ml import IntentRiskShadowModel
    m = IntentRiskShadowModel(project_root=tmp_path)
    # baseline says chat_only, but shadow sees destructive
    baseline = _make_route_decision("chat_only", "low")
    report = m.evaluate("cancella database", baseline_route_decision=baseline)
    assert any("shadow_disagrees_with_baseline" in w for w in report.warnings)


def test_intent_shadow_does_not_change_baseline_decision(tmp_path):
    from igris.core.shadow_ml import IntentRiskShadowModel
    m = IntentRiskShadowModel(project_root=tmp_path)
    baseline = _make_route_decision("read_only_inspection", "low")
    original_route = baseline.route
    original_risk = baseline.risk
    report = m.evaluate("cancella database", baseline_route_decision=baseline)
    # baseline object must not be mutated
    assert baseline.route == original_route
    assert baseline.risk == original_risk
    assert report.changed_decision is False


# ── StrategySelectorShadow ────────────────────────────────────────────────────

def test_strategy_shadow_deploy_suggests_approval(tmp_path):
    from igris.core.shadow_ml import StrategySelectorShadow
    s = StrategySelectorShadow(project_root=tmp_path)
    plan = _make_mission_plan(route="deploy_operation", risk="high")
    report = s.suggest_strategy(plan)
    assert report.shadow_decision["strategy"] == "approval_required"


def test_strategy_shadow_blocked_suggests_blocked(tmp_path):
    from igris.core.shadow_ml import StrategySelectorShadow
    s = StrategySelectorShadow(project_root=tmp_path)
    plan = _make_mission_plan(blocked=True)
    report = s.suggest_strategy(plan)
    assert report.shadow_decision["strategy"] == "blocked"


def test_strategy_shadow_failed_evidence_suggests_verify_first(tmp_path):
    from igris.core.shadow_ml import StrategySelectorShadow
    s = StrategySelectorShadow(project_root=tmp_path)
    plan = _make_mission_plan(route="code_change", risk="medium")
    bundle = _make_bundle("failed", False)
    report = s.suggest_strategy(plan, bundle)
    assert report.shadow_decision["strategy"] == "verify_first"


def test_strategy_shadow_low_confidence_suggests_human_review(tmp_path):
    from igris.core.shadow_ml import StrategySelectorShadow
    s = StrategySelectorShadow(project_root=tmp_path)
    plan = _make_mission_plan(route="read_only_inspection", risk="low")
    reflection = _make_reflection("inconclusive", 0.3)
    report = s.suggest_strategy(plan, reflection_report=reflection)
    assert report.shadow_decision["strategy"] == "human_review"


def test_strategy_shadow_does_not_modify_mission_plan(tmp_path):
    from igris.core.shadow_ml import StrategySelectorShadow
    s = StrategySelectorShadow(project_root=tmp_path)
    plan = _make_mission_plan(route="deploy_operation", risk="high",
                               requires_approval=False, blocked=False)
    orig_route = plan.route
    orig_blocked = plan.blocked
    orig_approval = plan.requires_approval
    report = s.suggest_strategy(plan)
    # Plan must NOT be mutated
    assert plan.route == orig_route
    assert plan.blocked == orig_blocked
    assert plan.requires_approval == orig_approval
    assert report.changed_decision is False
    assert report.shadow_only is True


# ── ShadowMLCoordinator ───────────────────────────────────────────────────────

def test_shadow_coordinator_combines_reports(tmp_path):
    from igris.core.shadow_ml import ShadowMLCoordinator
    c = ShadowMLCoordinator(project_root=tmp_path)
    report = c.evaluate_request("controlla i log")
    assert report.ok is True
    assert "sub_reports" in report.metadata
    assert "intent_risk" in report.metadata["sub_reports"]
    assert "strategy" in report.metadata["sub_reports"]


def test_shadow_coordinator_shadow_only(tmp_path):
    from igris.core.shadow_ml import ShadowMLCoordinator
    c = ShadowMLCoordinator(project_root=tmp_path)
    report = c.evaluate_request("fai deploy")
    assert report.shadow_only is True


def test_shadow_coordinator_changed_decision_false(tmp_path):
    from igris.core.shadow_ml import ShadowMLCoordinator
    c = ShadowMLCoordinator(project_root=tmp_path)
    report = c.evaluate_request("cancella database")
    assert report.changed_decision is False


def test_shadow_coordinator_no_raw_secret(tmp_path):
    FAKE_TOKEN = "FAKE_TOKEN_SHADOW_1234567890"
    FAKE_PASS = "FAKE_PASSWORD_SHADOW_1234567890"
    FAKE_KEY = "FAKE_API_KEY_SHADOW_1234567890"
    FAKE_PHRASE = "FAKE_PASSPHRASE_SHADOW_1234567890"
    from igris.core.shadow_ml import ShadowMLCoordinator
    c = ShadowMLCoordinator(project_root=tmp_path)
    message = (
        f"deploy with token={FAKE_TOKEN} "
        f"password={FAKE_PASS} "
        f"api_key={FAKE_KEY} "
        f"passphrase={FAKE_PHRASE}"
    )
    report = c.evaluate_request(message)
    output = json.dumps(report.to_dict())
    assert f"token={FAKE_TOKEN}" not in output
    assert f"password={FAKE_PASS}" not in output
    assert f"api_key={FAKE_KEY}" not in output
    assert f"passphrase={FAKE_PHRASE}" not in output
    # summary too
    summary = report.summary_text()
    assert f"token={FAKE_TOKEN}" not in summary
    assert f"password={FAKE_PASS}" not in summary


def test_shadow_coordinator_degraded_component_warning(tmp_path):
    """If a sub-component raises, coordinator must warn and continue."""
    import unittest.mock as mock
    from igris.core.shadow_ml import ShadowMLCoordinator, IntentRiskShadowModel
    c = ShadowMLCoordinator(project_root=tmp_path)

    with mock.patch.object(
        c._intent_model, "evaluate",
        side_effect=RuntimeError("component failure")
    ):
        report = c.evaluate_request("some message")

    assert any("intent_risk_degraded" in w or "failure" in w.lower() for w in report.warnings)
    # Coordinator must not crash — still returns a report
    assert report is not None


# ── ShadowScore / ShadowReport data classes ───────────────────────────────────

def test_shadow_score_to_dict_redacts_secret(tmp_path):
    FAKE = "FAKE_TOKEN_SHADOW_1234567890"
    from igris.core.shadow_ml import ShadowScore
    ss = ShadowScore(
        item_id="x",
        score=0.5,
        reason=f"token={FAKE}",
        features={"key": f"token={FAKE}"},
    )
    d = ss.to_dict()
    output = json.dumps(d)
    assert f"token={FAKE}" not in output


def test_shadow_report_changed_decision_defaults_false():
    from igris.core.shadow_ml import ShadowReport
    import uuid
    r = ShadowReport(report_id=str(uuid.uuid4()), kind="test")
    assert r.changed_decision is False
    assert r.shadow_only is True


def test_shadow_report_summary_text_contains_kind():
    from igris.core.shadow_ml import ShadowReport
    import uuid
    r = ShadowReport(report_id=str(uuid.uuid4()), kind="test_kind")
    text = r.summary_text()
    assert "test_kind" in text
    assert "[SHADOW REPORT]" in text
