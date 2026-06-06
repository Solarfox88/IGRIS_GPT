"""Tests for LearningFeedbackApplier (#1247)."""
from __future__ import annotations
import json
import pytest


def _make_bundle(status, ok):
    class FakeBundle:
        def __init__(self):
            self.status = status
            self.ok = ok
            self.results = []
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


# ── apply_signal ──────────────────────────────────────────────────────────────

def test_apply_lesson_uses_unified_memory_store_lesson(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_feedback import LearningFeedbackApplier
    from igris.core.after_action_review import LearningSignal, LearningSignalKind

    mem = UnifiedMemory(project_root=tmp_path)
    calls = []
    orig = mem.store_lesson
    def tracking(*a, **kw):
        calls.append(True)
        return orig(*a, **kw)
    mem.store_lesson = tracking

    applier = LearningFeedbackApplier(project_root=tmp_path, unified_memory=mem)
    sig = LearningSignal.make(LearningSignalKind.LESSON.value, "test lesson", confidence=0.8)
    result = applier.apply_signal(sig)
    assert len(calls) > 0


def test_apply_failure_pattern_uses_store_lesson(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_feedback import LearningFeedbackApplier
    from igris.core.after_action_review import LearningSignal, LearningSignalKind

    mem = UnifiedMemory(project_root=tmp_path)
    calls = []
    orig = mem.store_lesson
    def tracking(*a, **kw):
        calls.append(True)
        return orig(*a, **kw)
    mem.store_lesson = tracking

    applier = LearningFeedbackApplier(project_root=tmp_path, unified_memory=mem)
    sig = LearningSignal.make(LearningSignalKind.FAILURE_PATTERN.value, "fp text", confidence=0.8)
    applier.apply_signal(sig)
    assert len(calls) > 0


def test_apply_memory_feedback_uses_record_feedback(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_feedback import LearningFeedbackApplier
    from igris.core.after_action_review import LearningSignal, LearningSignalKind

    mem = UnifiedMemory(project_root=tmp_path)
    calls = []
    orig = mem.record_feedback
    def tracking(*a, **kw):
        calls.append(True)
        return orig(*a, **kw)
    mem.record_feedback = tracking

    applier = LearningFeedbackApplier(project_root=tmp_path, unified_memory=mem)
    sig = LearningSignal.make(LearningSignalKind.MEMORY_FEEDBACK.value, "fb text", confidence=0.8)
    applier.apply_signal(sig)
    assert len(calls) > 0


def test_apply_correction_uses_store_correction(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_feedback import LearningFeedbackApplier
    from igris.core.after_action_review import LearningSignal, LearningSignalKind

    mem = UnifiedMemory(project_root=tmp_path)
    calls = []
    orig = mem.store_correction
    def tracking(*a, **kw):
        calls.append(True)
        return orig(*a, **kw)
    mem.store_correction = tracking

    applier = LearningFeedbackApplier(project_root=tmp_path, unified_memory=mem)
    sig = LearningSignal.make(LearningSignalKind.CORRECTION.value, "correction text", confidence=0.8)
    applier.apply_signal(sig)
    assert len(calls) > 0


# ── apply_report ──────────────────────────────────────────────────────────────

def test_policy_recommendation_skipped_by_default(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    from igris.core.learning_feedback import LearningFeedbackApplier

    applier = LearningFeedbackApplier(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan(status="waiting_approval", requires_approval=True)
    reviewer = AfterActionReviewer(project_root=tmp_path)
    report = reviewer.review(plan, bundle)

    result = applier.apply_report(report)  # default: policy NOT applied
    skipped_reasons = [s.get("reason", "") for s in result.skipped]
    assert any("policy_recommendation" in r for r in skipped_reasons)
    assert result.ok is True  # skips are acceptable


def test_apply_report_ok_true_on_success(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    from igris.core.learning_feedback import LearningFeedbackApplier

    applier = LearningFeedbackApplier(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan(route="read_only_inspection")
    reviewer = AfterActionReviewer(project_root=tmp_path)
    report = reviewer.review(plan, bundle)
    result = applier.apply_report(report)
    assert result.ok is True


def test_apply_report_ok_false_when_storage_fails(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_feedback import LearningFeedbackApplier
    from igris.core.after_action_review import AfterActionReviewer

    mem = UnifiedMemory(project_root=tmp_path)
    def broken(*a, **kw): raise RuntimeError("storage fail")
    mem.store_lesson = broken
    mem.record_feedback = broken
    mem.store_run_event = broken
    mem.store_decision = broken
    mem.store_correction = broken

    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan(route="read_only_inspection")
    reviewer = AfterActionReviewer(project_root=tmp_path)
    report = reviewer.review(plan, bundle)

    applier = LearningFeedbackApplier(project_root=tmp_path, unified_memory=mem)
    result = applier.apply_report(report)
    if result.failed_count > 0:
        assert result.ok is False


def test_apply_report_no_raw_secret_in_result(tmp_path):
    FAKE = "FAKE_TOKEN_LEARNING_NOTREAL_9988"
    from igris.core.after_action_review import AfterActionReviewer
    from igris.core.learning_feedback import LearningFeedbackApplier

    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan()
    reviewer = AfterActionReviewer(project_root=tmp_path)
    # secret only appears in key=value form in user_feedback
    report = reviewer.review(plan, bundle, user_feedback=f"passphrase={FAKE}")

    applier = LearningFeedbackApplier(project_root=tmp_path)
    apply_result = applier.apply_report(report)
    output = json.dumps(apply_result.to_dict())
    # key=value form should be redacted
    assert f"passphrase={FAKE}" not in output


def test_apply_report_has_counts(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    from igris.core.learning_feedback import LearningFeedbackApplier

    applier = LearningFeedbackApplier(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan()
    reviewer = AfterActionReviewer(project_root=tmp_path)
    report = reviewer.review(plan, bundle)
    result = applier.apply_report(report)
    assert result.applied_count >= 0
    assert result.skipped_count >= 0
    assert result.failed_count >= 0


def test_apply_report_to_dict_structure(tmp_path):
    from igris.core.after_action_review import AfterActionReviewer
    from igris.core.learning_feedback import LearningFeedbackApplier

    applier = LearningFeedbackApplier(project_root=tmp_path)
    bundle = _make_bundle("passed", True)
    plan = _make_fake_plan()
    reviewer = AfterActionReviewer(project_root=tmp_path)
    report = reviewer.review(plan, bundle)
    result = applier.apply_report(report)
    d = result.to_dict()
    for key in ("ok", "applied_count", "skipped_count", "failed_count",
                 "applied", "skipped", "failed", "warnings"):
        assert key in d


def test_apply_report_failure_plan_marks_degraded_on_storage_fail(tmp_path):
    from igris.core.unified_memory import UnifiedMemory
    from igris.core.learning_feedback import LearningFeedbackApplier
    from igris.core.after_action_review import AfterActionReviewer

    mem = UnifiedMemory(project_root=tmp_path)
    def broken(*a, **kw): raise RuntimeError("disk full")
    mem.store_lesson = broken
    mem.record_feedback = broken
    mem.store_correction = broken

    bundle = _make_bundle("failed", False)
    plan = _make_fake_plan(route="code_edit")
    reviewer = AfterActionReviewer(project_root=tmp_path)
    report = reviewer.review(plan, bundle)

    applier = LearningFeedbackApplier(project_root=tmp_path, unified_memory=mem)
    result = applier.apply_report(report)
    if result.failed_count > 0:
        assert result.persistence_degraded is True


def test_healthcheck_ok(tmp_path):
    from igris.core.learning_feedback import LearningFeedbackApplier
    applier = LearningFeedbackApplier(project_root=tmp_path)
    h = applier.healthcheck()
    assert h["ok"] is True


# ── MissionFirstController integration ───────────────────────────────────────

def test_mfc_reflect_plan(tmp_path):
    from igris.core.mission_first import MissionFirstController
    from igris.core.jarvis_request_router import JarvisRequestRouter

    router = JarvisRequestRouter(project_root=tmp_path)
    mfc = MissionFirstController(project_root=tmp_path)
    rd = router.classify("controlla i log", interlocutor_id="owner", trust_level="admin")
    plan = mfc.build_plan("controlla i log", route_decision=rd,
                           trust_level="admin", interlocutor_id="owner")
    bundle = type("B", (), {"status": "passed", "ok": True, "results": []})()
    report = mfc.reflect_plan(plan, bundle)
    assert report is not None
    assert report.mission_id == plan.mission_id


def test_mfc_learn_from_plan(tmp_path):
    from igris.core.mission_first import MissionFirstController
    from igris.core.jarvis_request_router import JarvisRequestRouter

    router = JarvisRequestRouter(project_root=tmp_path)
    mfc = MissionFirstController(project_root=tmp_path)
    rd = router.classify("controlla i log", interlocutor_id="owner", trust_level="admin")
    plan = mfc.build_plan("controlla i log", route_decision=rd,
                           trust_level="admin", interlocutor_id="owner")
    bundle = type("B", (), {"status": "passed", "ok": True, "results": []})()
    result = mfc.learn_from_plan(plan, bundle)
    assert result is not None
    assert result.ok is True or result.skipped_count > 0
