"""Tests for AfterActionReviewer (#1247)."""
from __future__ import annotations
import json
import pytest


def _make_bundle(status, ok, results=None):
    class FakeBundle:
        def __init__(self):
            self.status = status
            self.ok = ok
            self.results = results or []
    return FakeBundle()


def _make_fake_plan(route="read_only_inspection", blocked=False,
                    status="planned", requires_approval=False, mission_id="m1"):
    class FakePlan:
        pass
    p = FakePlan()
    p.mission_id = mission_id
    p.route = route
    p.blocked = blocked
    p.status = status
    p.requires_approval = requires_approval
    return p


# ── infer_outcome ─────────────────────────────────────────────────────────────

def test_infer_outcome_success_from_passed_bundle(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    assert reviewer.infer_outcome(None, bundle) == "success"


def test_infer_outcome_failure_from_failed_bundle(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("failed", False)
    assert reviewer.infer_outcome(None, bundle) == "failure"


def test_infer_outcome_blocked_from_plan(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan(blocked=True)
    assert reviewer.infer_outcome(plan, None) == "blocked"


def test_infer_outcome_blocked_from_blocked_bundle(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("blocked", False)
    plan = _make_fake_plan(blocked=False)
    assert reviewer.infer_outcome(plan, bundle) == "blocked"


def test_infer_outcome_waiting_approval(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan(status="waiting_approval", requires_approval=True)
    assert reviewer.infer_outcome(plan, None) == "waiting_approval"


def test_infer_outcome_partial_from_warning_bundle(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("warning", False)
    assert reviewer.infer_outcome(None, bundle) == "partial"


def test_infer_outcome_inconclusive_default(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    assert reviewer.infer_outcome(None, None) == "inconclusive"


# ── extract_learning_signals ──────────────────────────────────────────────────

def test_success_generates_lesson_and_memory_feedback(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer, LearningSignalKind
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan(route="read_only_inspection")
    signals = reviewer.extract_learning_signals(plan, bundle)
    kinds = [s.kind for s in signals]
    assert LearningSignalKind.LESSON.value in kinds
    assert LearningSignalKind.MEMORY_FEEDBACK.value in kinds


def test_failure_generates_failure_pattern(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer, LearningSignalKind
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("failed", False)
    plan = _make_fake_plan(route="code_edit")
    signals = reviewer.extract_learning_signals(plan, bundle)
    kinds = [s.kind for s in signals]
    assert LearningSignalKind.FAILURE_PATTERN.value in kinds


def test_blocked_generates_lesson_and_memory_feedback(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer, LearningSignalKind
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan(blocked=True)
    signals = reviewer.extract_learning_signals(plan, None)
    kinds = [s.kind for s in signals]
    assert LearningSignalKind.LESSON.value in kinds
    assert LearningSignalKind.MEMORY_FEEDBACK.value in kinds


def test_waiting_approval_generates_policy_recommendation(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer, LearningSignalKind
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan(status="waiting_approval", requires_approval=True)
    signals = reviewer.extract_learning_signals(plan, None)
    kinds = [s.kind for s in signals]
    assert LearningSignalKind.POLICY_RECOMMENDATION.value in kinds


def test_user_feedback_remember_generates_lesson(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer, LearningSignalKind
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan()
    bundle = _make_bundle("passed", True)
    signals = reviewer.extract_learning_signals(plan, bundle,
                                                 user_feedback="ricordati che preferisco risposte brevi")
    kinds = [s.kind for s in signals]
    assert LearningSignalKind.LESSON.value in kinds


def test_user_feedback_correction_generates_correction(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer, LearningSignalKind
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan()
    bundle = _make_bundle("passed", True)
    signals = reviewer.extract_learning_signals(plan, bundle,
                                                 user_feedback="no, mi sbagliavo, usa pytest")
    kinds = [s.kind for s in signals]
    assert LearningSignalKind.CORRECTION.value in kinds


def test_user_feedback_negative_generates_correction(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer, LearningSignalKind
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan()
    bundle = _make_bundle("passed", True)
    signals = reviewer.extract_learning_signals(plan, bundle,
                                                 user_feedback="non fare più questo errore")
    kinds = [s.kind for s in signals]
    assert LearningSignalKind.CORRECTION.value in kinds


# ── review ────────────────────────────────────────────────────────────────────

def test_review_returns_report_with_outcome(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan()
    report = reviewer.review(plan, bundle)
    assert report.outcome == "success"
    assert report.mission_id == "m1"
    assert report.confidence > 0


def test_review_summary_text_produced(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan()
    report = reviewer.review(plan, bundle)
    text = report.summary_text()
    assert "[REFLECTION REPORT]" in text
    assert "success" in text


def test_report_no_raw_secret(tmp_path):
    FAKE = "FAKE_TOKEN_REFLECT_NOTREAL_1234567890"
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan()
    # The fake token appears only in key=value form inside user_feedback — must be redacted
    report = reviewer.review(plan, bundle, user_feedback=f"token={FAKE}")
    # Check all signal texts and summary don't contain raw secret
    output = json.dumps(report.to_dict())
    # secret in key=value form should be redacted
    assert f"token={FAKE}" not in output


def test_policy_recommendation_requires_review(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan(status="waiting_approval", requires_approval=True)
    bundle = _make_bundle("passed", True)
    signals = reviewer.extract_learning_signals(plan, bundle)
    policy_sigs = [s for s in signals if s.kind == "policy_recommendation"]
    assert len(policy_sigs) > 0
    for sig in policy_sigs:
        assert sig.requires_human_review is True
        assert sig.safe_to_persist is False


def test_review_with_none_bundle_no_crash(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    plan = _make_fake_plan(blocked=True)
    report = reviewer.review(plan, None)
    assert report.outcome == "blocked"
    assert len(report.warnings) == 0


def test_review_with_none_plan_no_crash(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    report = reviewer.review(None, bundle)
    assert report.outcome == "success"


def test_healthcheck_ok(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    h = reviewer.healthcheck()
    assert h["ok"] is True


def test_to_dict_structure(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan()
    report = reviewer.review(plan, bundle)
    d = report.to_dict()
    for key in ("report_id", "mission_id", "route", "outcome", "confidence",
                 "lessons", "failure_patterns", "corrections",
                 "memory_feedback", "policy_recommendations", "warnings"):
        assert key in d


def test_all_signals_returns_flat_list(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    reviewer = AfterActionReviewer(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan()
    report = reviewer.review(plan, bundle)
    assert isinstance(report.all_signals(), list)
    assert len(report.all_signals()) > 0


# ── MissionPlan integration ───────────────────────────────────────────────────

def test_review_with_real_mission_plan(tmp_path):
    from igris.core.mission_first import MissionFirstController, MissionPlan
    from igris.core.jarvis_request_router import JarvisRequestRouter
    from igris.core.after_action_review import AfterActionReviewer

    router = JarvisRequestRouter(project_root=tmp_path)
    mfc = MissionFirstController(project_root=tmp_path)
    reviewer = AfterActionReviewer(project_root=tmp_path)

    rd = router.classify("controlla i log", interlocutor_id="owner", trust_level="admin")
    plan = mfc.build_plan("controlla i log", route_decision=rd,
                           trust_level="admin", interlocutor_id="owner")

    bundle = _make_bundle("passed", True)
    report = reviewer.review(plan, bundle)
    assert report.outcome in ("success", "waiting_approval", "blocked", "partial", "inconclusive")
    assert report.mission_id == plan.mission_id
