"""Tests for igris.core.mission_controller — Epic #40 Mission Controller."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from igris.core.mission_controller import (
    MISSION_STATUSES,
    ControlledMission,
    MissionArtifact,
    MissionController,
    delete_controlled_mission,
    list_controlled_missions,
    load_controlled_mission,
    save_controlled_mission,
)


# ---------------------------------------------------------------------------
# MissionArtifact model
# ---------------------------------------------------------------------------


class TestMissionArtifact:
    def test_to_dict(self):
        a = MissionArtifact(type="file", path="/tmp/x.py", description="test file")
        d = a.to_dict()
        assert d["type"] == "file"
        assert d["id"].startswith("art-")

    def test_from_dict(self):
        data = {"type": "patch", "path": "/tmp/p.diff", "description": "fix"}
        a = MissionArtifact.from_dict(data)
        assert a.type == "patch"

    def test_secret_redacted(self):
        a = MissionArtifact(path="key=sk-1234567890abcdef1234567890abcdef")
        d = a.to_dict()
        assert "sk-" not in d["path"]


# ---------------------------------------------------------------------------
# ControlledMission model
# ---------------------------------------------------------------------------


class TestControlledMission:
    def test_to_dict_structure(self):
        m = ControlledMission(title="Test", goal="Do something")
        d = m.to_dict()
        assert d["title"] == "Test"
        assert d["goal"] == "Do something"
        assert d["id"].startswith("mission-")
        assert d["trace_id"].startswith("trace-")
        assert d["status"] == "created"

    def test_from_dict_roundtrip(self):
        m = ControlledMission(title="RT", goal="Roundtrip test", risk_level="high")
        d = m.to_dict()
        m2 = ControlledMission.from_dict(d)
        assert m2.title == "RT"
        assert m2.risk_level == "high"
        assert m2.id == m.id

    def test_explain_state_created(self):
        m = ControlledMission(title="X", goal="Y")
        state = m.explain_state()
        assert state["status"] == "created"
        assert "planning" in state["next_action_explanation"].lower() or "plan" in state["next_action_explanation"].lower()

    def test_explain_state_done(self):
        m = ControlledMission(status="done")
        state = m.explain_state()
        assert "completed" in state["next_action_explanation"].lower()

    def test_explain_state_paused(self):
        m = ControlledMission(status="paused")
        state = m.explain_state()
        assert "paused" in state["next_action_explanation"].lower()

    def test_explain_state_blocked(self):
        m = ControlledMission(status="blocked", blocked_reason="timeout")
        state = m.explain_state()
        assert "timeout" in state["next_action_explanation"]

    def test_explain_state_with_tasks(self):
        m = ControlledMission(
            status="executing",
            tasks=[
                {"id": "1", "title": "Step A", "status": "done"},
                {"id": "2", "title": "Step B", "status": "pending"},
            ],
            current_step=1,
            total_steps=2,
        )
        state = m.explain_state()
        assert state["completed"] == 1
        assert "Step B" in state["next_action_explanation"]

    def test_execution_log_capped(self):
        m = ControlledMission()
        m.execution_log = [{"event": f"e{i}"} for i in range(100)]
        d = m.to_dict()
        assert len(d["execution_log"]) == 50


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        m = ControlledMission(title="Persist", goal="Test persistence")
        save_controlled_mission(m, str(tmp_path))
        loaded = load_controlled_mission(m.id, str(tmp_path))
        assert loaded is not None
        assert loaded.title == "Persist"

    def test_load_nonexistent(self, tmp_path):
        result = load_controlled_mission("nonexistent-id", str(tmp_path))
        assert result is None

    def test_list_missions(self, tmp_path):
        m1 = ControlledMission(title="A")
        m2 = ControlledMission(title="B")
        save_controlled_mission(m1, str(tmp_path))
        save_controlled_mission(m2, str(tmp_path))
        missions = list_controlled_missions(str(tmp_path))
        assert len(missions) == 2

    def test_delete_mission(self, tmp_path):
        m = ControlledMission(title="Delete me")
        save_controlled_mission(m, str(tmp_path))
        assert delete_controlled_mission(m.id, str(tmp_path)) is True
        assert load_controlled_mission(m.id, str(tmp_path)) is None

    def test_delete_nonexistent(self, tmp_path):
        assert delete_controlled_mission("nope", str(tmp_path)) is False


# ---------------------------------------------------------------------------
# MissionController — lifecycle
# ---------------------------------------------------------------------------


class TestMissionControllerCreate:
    def test_create_mission(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Test", goal="Build a feature")
        assert m.status == "created"
        assert m.title == "Test"
        assert len(m.execution_log) == 1
        assert m.execution_log[0]["event"] == "created"

    def test_create_with_all_fields(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(
            title="Full",
            goal="Deploy site",
            workspace="/tmp/ws",
            target_hosts=["host1"],
            constraints=["no force push"],
            success_criteria=["tests pass"],
            risk_level="high",
            rollback_plan="revert commit",
        )
        assert m.workspace == "/tmp/ws"
        assert m.risk_level == "high"
        assert m.target_hosts == ["host1"]
        assert m.rollback_plan == "revert commit"

    def test_persisted_after_create(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="P", goal="persist")
        loaded = load_controlled_mission(m.id, str(tmp_path))
        assert loaded is not None


class TestMissionControllerPlan:
    def test_plan_generates_steps(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Fix bug", goal="Fix the login bug")
        planned = ctrl.plan_mission(m.id)
        assert planned is not None
        assert planned.status == "planned"
        assert len(planned.tasks) > 0
        assert planned.total_steps > 0

    def test_plan_nonexistent(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        result = ctrl.plan_mission("nonexistent")
        assert result is None

    def test_plan_creates_log_entry(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Log", goal="Check logging")
        planned = ctrl.plan_mission(m.id)
        events = [e["event"] for e in planned.execution_log]
        assert "planned" in events


class TestMissionControllerExecute:
    def _setup_planned_mission(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Exec", goal="Test execution")
        ctrl.plan_mission(m.id)
        return ctrl, m

    def test_execute_next_step(self, tmp_path):
        ctrl, m = self._setup_planned_mission(tmp_path)
        result = ctrl.execute_next_step(m.id)
        assert result is not None
        assert result["status"] == "executing"
        assert "task" in result
        assert result["trace_id"] == m.trace_id

    def test_execute_nonexistent(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        result = ctrl.execute_next_step("nope")
        assert result is None

    def test_execute_paused_rejected(self, tmp_path):
        ctrl, m = self._setup_planned_mission(tmp_path)
        ctrl.pause_mission(m.id)
        result = ctrl.execute_next_step(m.id)
        assert "error" in result
        assert "paused" in result["error"].lower()

    def test_execute_done_rejected(self, tmp_path):
        ctrl, m = self._setup_planned_mission(tmp_path)
        mission = load_controlled_mission(m.id, str(tmp_path))
        mission.status = "done"
        save_controlled_mission(mission, str(tmp_path))
        result = ctrl.execute_next_step(m.id)
        assert "error" in result

    def test_execute_no_tasks_error(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="No tasks", goal="Empty")
        result = ctrl.execute_next_step(m.id)
        assert "error" in result
        assert "plan" in result["error"].lower() or "task" in result["error"].lower()

    def test_duplicate_execution_guard(self, tmp_path):
        ctrl, m = self._setup_planned_mission(tmp_path)
        ctrl.execute_next_step(m.id)
        # Manually set current_step back to force duplicate check
        mission = load_controlled_mission(m.id, str(tmp_path))
        # The task at step 0 is already "executing"
        mission.current_step = 0
        save_controlled_mission(mission, str(tmp_path))
        result = ctrl.execute_next_step(m.id)
        assert "warning" in result


class TestMissionControllerOutcome:
    def _setup_executing(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Outcome", goal="Test outcomes")
        ctrl.plan_mission(m.id)
        ctrl.execute_next_step(m.id)
        return ctrl, m

    def test_report_success(self, tmp_path):
        ctrl, m = self._setup_executing(tmp_path)
        updated = ctrl.report_step_outcome(m.id, 0, "success", "Step completed")
        assert updated.tasks[0]["status"] == "done"
        assert updated.current_step == 1

    def test_report_failure(self, tmp_path):
        ctrl, m = self._setup_executing(tmp_path)
        updated = ctrl.report_step_outcome(m.id, 0, "failure", "Error occurred")
        assert updated.tasks[0]["status"] == "failed"

    def test_three_consecutive_failures_block(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Fail", goal="Test blocking")
        ctrl.plan_mission(m.id)
        # We need at least 3 tasks
        mission = load_controlled_mission(m.id, str(tmp_path))
        while len(mission.tasks) < 4:
            mission.tasks.append({
                "id": f"extra-{len(mission.tasks)}",
                "title": f"Extra step {len(mission.tasks)}",
                "status": "pending",
                "family": "test",
            })
            mission.total_steps = len(mission.tasks)
        save_controlled_mission(mission, str(tmp_path))

        ctrl.execute_next_step(m.id)
        ctrl.report_step_outcome(m.id, 0, "failure", "fail 1")
        ctrl.execute_next_step(m.id)
        ctrl.report_step_outcome(m.id, 1, "failure", "fail 2")
        ctrl.execute_next_step(m.id)
        result = ctrl.report_step_outcome(m.id, 2, "failure", "fail 3")
        assert result.status == "blocked"

    def test_report_skipped(self, tmp_path):
        ctrl, m = self._setup_executing(tmp_path)
        updated = ctrl.report_step_outcome(m.id, 0, "skipped", "Not applicable")
        assert updated.tasks[0]["status"] == "skipped"


class TestMissionControllerPauseResume:
    def test_pause_and_resume(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="PR", goal="Test pause/resume")
        ctrl.plan_mission(m.id)
        ctrl.execute_next_step(m.id)

        paused = ctrl.pause_mission(m.id)
        assert paused.status == "paused"
        assert paused.paused_at is not None

        resumed = ctrl.resume_mission(m.id)
        assert resumed.status == "executing"
        assert resumed.paused_at is None

    def test_resume_non_paused(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="NP", goal="Not paused")
        result = ctrl.resume_mission(m.id)
        assert result.status == "created"  # Unchanged


class TestMissionControllerBlockUnblock:
    def test_block_and_unblock(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="BU", goal="Block test")

        blocked = ctrl.block_mission(m.id, "waiting for approval")
        assert blocked.status == "blocked"
        assert blocked.blocked_reason == "waiting for approval"

        unblocked = ctrl.unblock_mission(m.id)
        assert unblocked.status == "executing"
        assert unblocked.blocked_reason is None


class TestMissionControllerVerify:
    def test_verify_all_success(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="V", goal="Verify")
        ctrl.plan_mission(m.id)

        # Mark all tasks as done
        mission = load_controlled_mission(m.id, str(tmp_path))
        for t in mission.tasks:
            t["status"] = "done"
        save_controlled_mission(mission, str(tmp_path))

        result = ctrl.verify_mission(m.id)
        assert result["criteria_met"] is True
        assert result["final_status"] == "done"

    def test_verify_with_failures(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="VF", goal="Verify fail")
        ctrl.plan_mission(m.id)

        mission = load_controlled_mission(m.id, str(tmp_path))
        for t in mission.tasks:
            t["status"] = "failed"
        save_controlled_mission(mission, str(tmp_path))

        result = ctrl.verify_mission(m.id)
        assert result["criteria_met"] is False
        assert result["final_status"] == "failed"


class TestMissionControllerReport:
    def test_generate_report(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Report", goal="Test report")
        ctrl.plan_mission(m.id)

        report = ctrl.generate_final_report(m.id)
        assert report is not None
        assert report["mission_id"] == m.id
        assert report["title"] == "Report"
        assert "execution_summary" in report
        assert "total_tasks" in report

    def test_report_nonexistent(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        result = ctrl.generate_final_report("nope")
        assert result is None


class TestMissionControllerArtifact:
    def test_add_artifact(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Art", goal="Test artifacts")
        updated = ctrl.add_artifact(m.id, "file", "/tmp/out.txt", "output file")
        assert len(updated.artifacts) == 1
        assert updated.artifacts[0].type == "file"


class TestMissionControllerContext:
    def test_reconstruct_context(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Ctx", goal="Context test")
        ctrl.plan_mission(m.id)

        ctx = ctrl.reconstruct_context(m.id)
        assert ctx is not None
        assert ctx["mission_id"] == m.id
        assert ctx["can_resume"] is True
        assert "state_explanation" in ctx

    def test_context_detects_interrupted(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Int", goal="Interrupt test")
        ctrl.plan_mission(m.id)
        ctrl.execute_next_step(m.id)

        ctx = ctrl.reconstruct_context(m.id)
        assert ctx["interrupted"] is True
        assert ctx["needs_replan"] is True

    def test_context_nonexistent(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        result = ctrl.reconstruct_context("nope")
        assert result is None


# ---------------------------------------------------------------------------
# Full lifecycle E2E
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    def test_create_plan_execute_verify_report(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))

        # Create
        m = ctrl.create_mission(
            title="Add logging feature",
            goal="Add a simple logging feature to the project",
            success_criteria=["Feature implemented", "Tests pass"],
        )
        assert m.status == "created"

        # Plan
        planned = ctrl.plan_mission(m.id)
        assert planned.status == "planned"
        assert planned.total_steps > 0

        # Execute all steps
        for i in range(planned.total_steps):
            step = ctrl.execute_next_step(m.id)
            assert step is not None
            if "error" in step:
                break
            ctrl.report_step_outcome(m.id, i, "success", f"Step {i} done")

        # Verify
        result = ctrl.verify_mission(m.id)
        assert result["criteria_met"] is True

        # Report
        report = ctrl.generate_final_report(m.id)
        assert report["status"] == "done"
        assert report["success_rate"] == 1.0

    def test_lifecycle_with_failure_and_recovery(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="Recovery", goal="Test recovery flow")
        ctrl.plan_mission(m.id)

        # Execute first step, fail
        ctrl.execute_next_step(m.id)
        ctrl.report_step_outcome(m.id, 0, "failure", "Error in step 0")

        # Continue with next step, succeed
        step = ctrl.execute_next_step(m.id)
        if step and "error" not in step:
            ctrl.report_step_outcome(m.id, 1, "success", "Step 1 ok")

        # Check context
        ctx = ctrl.reconstruct_context(m.id)
        assert ctx is not None

    def test_pause_resume_continue(self, tmp_path):
        ctrl = MissionController(project_root=str(tmp_path))
        m = ctrl.create_mission(title="PRC", goal="Pause resume continue")
        ctrl.plan_mission(m.id)
        ctrl.execute_next_step(m.id)
        ctrl.report_step_outcome(m.id, 0, "success")

        # Pause
        ctrl.pause_mission(m.id, "lunch break")
        ctx = ctrl.reconstruct_context(m.id)
        assert ctx["status"] == "paused"

        # Resume
        ctrl.resume_mission(m.id)
        step = ctrl.execute_next_step(m.id)
        assert step is not None


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


class TestMissionControllerAPI:
    @pytest.fixture
    def client(self):
        from igris.web.server import create_app
        from fastapi.testclient import TestClient
        app = create_app()
        return TestClient(app)

    def test_create_mission(self, client):
        resp = client.post("/api/controller/missions", json={
            "title": "API Test",
            "goal": "Test the API",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "API Test"
        assert data["id"].startswith("mission-")

    def test_create_missing_fields(self, client):
        resp = client.post("/api/controller/missions", json={"title": "No goal"})
        assert resp.status_code == 400

    def test_list_missions(self, client):
        client.post("/api/controller/missions", json={"title": "L1", "goal": "list test"})
        resp = client.get("/api/controller/missions")
        assert resp.status_code == 200
        assert "missions" in resp.json()

    def test_get_mission(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Get", "goal": "get test",
        })
        mid = create_resp.json()["id"]
        resp = client.get(f"/api/controller/missions/{mid}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Get"

    def test_get_nonexistent(self, client):
        resp = client.get("/api/controller/missions/nonexistent")
        assert resp.status_code == 404

    def test_plan_mission(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Plan", "goal": "Fix a bug in the login module",
        })
        mid = create_resp.json()["id"]
        resp = client.post(f"/api/controller/missions/{mid}/plan")
        assert resp.status_code == 200
        assert resp.json()["status"] == "planned"
        assert resp.json()["total_steps"] > 0

    def test_explain_state(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Explain", "goal": "explain test",
        })
        mid = create_resp.json()["id"]
        resp = client.get(f"/api/controller/missions/{mid}/explain")
        assert resp.status_code == 200
        assert "next_action_explanation" in resp.json()

    def test_execute_next(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Exec", "goal": "Test execution via API",
        })
        mid = create_resp.json()["id"]
        client.post(f"/api/controller/missions/{mid}/plan")
        resp = client.post(f"/api/controller/missions/{mid}/execute-next")
        assert resp.status_code == 200
        assert resp.json()["status"] == "executing"

    def test_report_outcome(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Out", "goal": "Test outcome reporting",
        })
        mid = create_resp.json()["id"]
        client.post(f"/api/controller/missions/{mid}/plan")
        client.post(f"/api/controller/missions/{mid}/execute-next")
        resp = client.post(f"/api/controller/missions/{mid}/report-outcome", json={
            "step_index": 0,
            "outcome": "success",
            "detail": "All good",
        })
        assert resp.status_code == 200

    def test_pause_resume(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "PR", "goal": "Pause resume",
        })
        mid = create_resp.json()["id"]
        resp = client.post(f"/api/controller/missions/{mid}/pause", json={"reason": "break"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        resp = client.post(f"/api/controller/missions/{mid}/resume")
        assert resp.status_code == 200

    def test_verify_mission(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Ver", "goal": "Verify test",
        })
        mid = create_resp.json()["id"]
        client.post(f"/api/controller/missions/{mid}/plan")
        resp = client.post(f"/api/controller/missions/{mid}/verify")
        assert resp.status_code == 200
        assert "criteria_met" in resp.json()

    def test_final_report(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Rep", "goal": "Report test",
        })
        mid = create_resp.json()["id"]
        client.post(f"/api/controller/missions/{mid}/plan")
        resp = client.get(f"/api/controller/missions/{mid}/report")
        assert resp.status_code == 200
        assert "execution_summary" in resp.json()

    def test_context_reconstruction(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Ctx", "goal": "Context test",
        })
        mid = create_resp.json()["id"]
        client.post(f"/api/controller/missions/{mid}/plan")
        resp = client.get(f"/api/controller/missions/{mid}/context")
        assert resp.status_code == 200
        assert "can_resume" in resp.json()

    def test_add_artifact(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "Art", "goal": "Artifact test",
        })
        mid = create_resp.json()["id"]
        resp = client.post(f"/api/controller/missions/{mid}/artifacts", json={
            "type": "file",
            "path": "/tmp/out.txt",
            "description": "output",
        })
        assert resp.status_code == 200
        assert len(resp.json()["artifacts"]) == 1

    def test_block_unblock(self, client):
        create_resp = client.post("/api/controller/missions", json={
            "title": "BU", "goal": "Block test",
        })
        mid = create_resp.json()["id"]
        resp = client.post(f"/api/controller/missions/{mid}/block", json={"reason": "waiting"})
        assert resp.json()["status"] == "blocked"

        resp = client.post(f"/api/controller/missions/{mid}/unblock")
        assert resp.json()["status"] == "executing"
