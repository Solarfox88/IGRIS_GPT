"""Tests for Epic #46 — Teacher/Governor Anti-Loop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from igris.core.teacher_governor import (
    GovernorDecision,
    TaskFingerprint,
    TeacherGovernor,
    TASK_FAMILIES,
    STRATEGY_SHIFTS,
)


# ===========================================================================
# TaskFingerprint
# ===========================================================================


class TestTaskFingerprint:
    def test_compute_hash(self):
        fp = TaskFingerprint(family="code_patch", intent="fix bug", file_target="main.py")
        h = fp.compute_hash()
        assert len(h) == 16
        # Same input → same hash
        fp2 = TaskFingerprint(family="code_patch", intent="fix bug", file_target="main.py")
        assert fp2.compute_hash() == h

    def test_different_inputs(self):
        fp1 = TaskFingerprint(family="code_patch", intent="fix bug")
        fp2 = TaskFingerprint(family="code_patch", intent="add feature")
        assert fp1.compute_hash() != fp2.compute_hash()

    def test_to_dict(self):
        fp = TaskFingerprint(family="test_repair", intent="fix tests")
        d = fp.to_dict()
        assert d["family"] == "test_repair"
        assert "hash" in d


# ===========================================================================
# GovernorDecision
# ===========================================================================


class TestGovernorDecision:
    def test_to_dict(self):
        d = GovernorDecision(action="approve", family="code_patch", reason="OK")
        result = d.to_dict()
        assert result["action"] == "approve"
        assert result["escalation"] is False

    def test_secret_redacted(self):
        d = GovernorDecision(reason="token=sk-1234567890abcdef1234567890abcdef")
        result = d.to_dict()
        assert "sk-" not in result["reason"]


# ===========================================================================
# TeacherGovernor — History
# ===========================================================================


class TestGovernorHistory:
    def test_record_task(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        gov.record_task("fix the bug", "code_patch")
        assert len(gov.get_history()) == 1

    def test_family_counts(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        gov.record_task("test A")
        gov.record_task("test B")
        gov.record_task("edit file")
        counts = gov.get_family_counts()
        assert counts.get("testing", 0) == 2


# ===========================================================================
# TeacherGovernor — Saturation
# ===========================================================================


class TestGovernorSaturation:
    def test_not_saturated(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        gov.record_task("test once")
        assert not gov.is_family_saturated("testing")

    def test_saturated_at_threshold(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        for i in range(3):
            gov.record_task(f"run test {i}")
        assert gov.is_family_saturated("testing")

    def test_get_saturated_families(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        for i in range(4):
            gov.record_task(f"edit file {i}")
        saturated = gov.get_saturated_families()
        assert "editing" in saturated


# ===========================================================================
# TeacherGovernor — Evaluate task
# ===========================================================================


class TestGovernorEvaluate:
    def test_approve_normal(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        decision = gov.evaluate_task(
            description="write docs",
            family="documentation",
            success_criteria=["docs updated"],
        )
        assert decision.action == "approve"

    def test_reject_no_success_criteria(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        decision = gov.evaluate_task(
            description="do something",
            family="other",
        )
        assert decision.action == "reject"
        assert "success_criteria" in decision.reason

    def test_reject_blocked_family(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        gov.block_family("code_patch", "too many failures")
        decision = gov.evaluate_task(
            description="fix bug",
            family="code_patch",
            success_criteria=["bug fixed"],
        )
        assert decision.action == "reject"
        assert "blocked" in decision.reason

    def test_reject_semantic_duplicate(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        gov.record_task("fix the login bug in auth.py")
        decision = gov.evaluate_task(
            description="fix the login bug in auth.py",
            family="code_patch",
            success_criteria=["bug fixed"],
        )
        assert decision.action == "reject"
        assert "duplicate" in decision.reason.lower()

    def test_shift_on_saturation(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        for i in range(3):
            gov.record_task(f"run test {i}")
        decision = gov.evaluate_task(
            description="run another test",
            family="testing",
            success_criteria=["tests pass"],
        )
        # "testing" maps to "other" via classify_task_family, but explicit family is tested
        assert decision.action in ("shift", "escalate", "reject")

    def test_approve_with_differentiator(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        for i in range(3):
            gov.record_task(f"edit file number {i}")
        decision = gov.evaluate_task(
            description="edit new file",
            family="editing",
            differentiator="This targets a completely different module (auth vs. payments)",
            success_criteria=["file updated"],
        )
        assert decision.action == "approve"

    def test_reject_short_differentiator(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        for i in range(3):
            gov.record_task(f"edit file number {i}")
        decision = gov.evaluate_task(
            description="edit another file",
            family="editing",
            differentiator="ok",  # too short
            success_criteria=["done"],
        )
        assert decision.action != "approve"

    def test_escalate_all_saturated(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path), threshold=2)
        # Saturate "other" and its alternatives ("observation", "code_patch")
        # plus any second-level alternatives
        target_families = {"other", "observation", "code_patch", "synthesis",
                           "documentation", "test_repair", "review_gate",
                           "stabilization_audit", "grading_diagnosis",
                           "security_audit", "branch_pr_plan"}
        for fam_name in target_families:
            for i in range(2):
                gov.record_task(f"{fam_name} task {i}", family=fam_name)
        # Block any remaining unsaturated alternatives
        for fam in TASK_FAMILIES:
            if fam not in target_families:
                gov.block_family(fam)
        decision = gov.evaluate_task(
            description="do something new",
            family="other",
            success_criteria=["done"],
        )
        assert decision.action == "escalate"
        assert decision.escalation is True

    def test_fingerprint_duplicate_rejected(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        fp = TaskFingerprint(family="code_patch", intent="fix bug", file_target="main.py")
        gov.register_fingerprint("task-1", fp)
        decision = gov.evaluate_task(
            description="fix a different bug",
            family="code_patch",
            success_criteria=["fixed"],
            fingerprint=TaskFingerprint(family="code_patch", intent="fix bug", file_target="main.py"),
        )
        assert decision.action == "reject"
        assert "fingerprint" in decision.reason.lower()


# ===========================================================================
# TeacherGovernor — Hard powers
# ===========================================================================


class TestGovernorHardPowers:
    def test_block_family(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        result = gov.block_family("code_patch", "repeated failures")
        assert "code_patch" in result.blocked_families

    def test_unblock_family(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        gov.block_family("code_patch")
        gov.unblock_family("code_patch")
        decision = gov.evaluate_task("fix bug", "code_patch", success_criteria=["fixed"])
        assert decision.action == "approve"

    def test_materialize_alternative(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        for i in range(3):
            gov.record_task(f"edit file {i}")
        decision = gov.materialize_alternative("editing", mission_id="m1")
        assert decision.action == "materialize"
        assert decision.alternative_task is not None
        assert decision.alternative_task["family"] != "editing"

    def test_escalation_report(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        report = gov.generate_escalation_report()
        assert "report_id" in report
        assert "recommendation" in report


# ===========================================================================
# TeacherGovernor — Persistence
# ===========================================================================


class TestGovernorPersistence:
    def test_save_and_load(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        gov.record_task("test something")
        gov.block_family("code_patch")
        gov.save_state()

        gov2 = TeacherGovernor(project_root=str(tmp_path))
        assert gov2.load_state() is True
        assert len(gov2.get_history()) == 1
        assert "code_patch" in gov2._blocked_families

    def test_load_nonexistent(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        assert gov.load_state() is False


# ===========================================================================
# Strategy shifts
# ===========================================================================


class TestStrategyShifts:
    def test_all_families_have_shifts(self):
        for family in TASK_FAMILIES:
            assert family in STRATEGY_SHIFTS, f"No shift mapping for {family}"

    def test_shift_targets_are_valid(self):
        for family, targets in STRATEGY_SHIFTS.items():
            for t in targets:
                assert t in TASK_FAMILIES, f"Invalid shift target '{t}' for family '{family}'"


# ===========================================================================
# Full lifecycle
# ===========================================================================


class TestGovernorLifecycle:
    def test_approve_shift_escalate(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))

        # Step 1: approve a normal task
        d1 = gov.evaluate_task("write docs", "documentation", success_criteria=["done"])
        assert d1.action == "approve"
        gov.record_task("write docs", "documentation")

        # Step 2: saturate documentation
        gov.record_task("update readme", "documentation")
        gov.record_task("add changelog", "documentation")

        # Step 3: try another doc task → should shift
        d2 = gov.evaluate_task("more docs", "documentation", success_criteria=["done"])
        assert d2.action in ("shift", "escalate")

    def test_forced_strategy_count(self, tmp_path):
        gov = TeacherGovernor(project_root=str(tmp_path))
        for i in range(3):
            gov.record_task(f"edit file {i}")
        gov.evaluate_task("edit again", "editing", success_criteria=["done"])
        assert gov._forced_shifts >= 1 or len(gov._escalation_log) >= 1


# ===========================================================================
# API integration
# ===========================================================================


class TestGovernorAPI:
    @pytest.fixture
    def client(self):
        from igris.web.server import create_app
        from fastapi.testclient import TestClient
        app = create_app()
        return TestClient(app)

    def test_evaluate_approve(self, client):
        resp = client.post("/api/governor/evaluate", json={
            "description": "write unit tests",
            "family": "test_repair",
            "success_criteria": ["tests pass"],
        })
        assert resp.status_code == 200
        assert resp.json()["action"] == "approve"

    def test_evaluate_reject_no_criteria(self, client):
        resp = client.post("/api/governor/evaluate", json={
            "description": "do thing",
            "family": "other",
        })
        assert resp.json()["action"] == "reject"

    def test_summary(self, client):
        resp = client.get("/api/governor/summary")
        assert resp.status_code == 200
        assert "threshold" in resp.json()

    def test_saturated(self, client):
        resp = client.get("/api/governor/saturated")
        assert resp.status_code == 200
        assert "saturated" in resp.json()

    def test_block_family(self, client):
        resp = client.post("/api/governor/block-family", json={
            "family": "code_patch",
            "reason": "test block",
        })
        assert resp.status_code == 200
        assert "code_patch" in resp.json()["blocked_families"]

    def test_materialize_alternative(self, client):
        resp = client.post("/api/governor/materialize-alternative", json={
            "family": "editing",
        })
        assert resp.status_code == 200
        assert resp.json()["action"] == "materialize"

    def test_escalation_report(self, client):
        resp = client.get("/api/governor/escalation-report")
        assert resp.status_code == 200
        assert "report_id" in resp.json()

    def test_record_task(self, client):
        resp = client.post("/api/governor/record-task", json={
            "description": "test task",
            "family": "testing",
        })
        assert resp.status_code == 200
        assert resp.json()["recorded"] is True
