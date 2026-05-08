from fastapi.testclient import TestClient

from igris.core.self_repair_supervisor import (
    CommandResult,
    RankSupervisorConfig,
    SelfRepairSupervisor,
    classify_failure,
)
from igris.web.server import create_app


class FakeBackend:
    def __init__(self):
        self.status = CommandResult(True, "")
        self.baseline = CommandResult(True, "baseline ok")
        self.smoke_result = CommandResult(True, "smoke ok")
        self.full_tests = [CommandResult(True, "full ok")]
        self.targeted = CommandResult(True, "targeted ok")
        self.reasoning_results = [{
            "status": "finished",
            "stop_reason": "finish",
            "files_modified": ["igris/web/server.py", "tests/test_rank_status.py"],
            "final_summary": "done",
            "loop_id": "loop-1",
            "goal": "rank task with tests",
        }]
        self.diff_stat = CommandResult(True, " igris/web/server.py | 2 ++")
        self.diff = CommandResult(True, "+safe")
        self.commands = []

    def git_status(self):
        self.commands.append("git_status")
        return self.status

    def git_log_head(self):
        return CommandResult(True, "abc123 head")

    def create_branch(self, branch):
        self.commands.append(f"branch:{branch}")
        return CommandResult(True, branch)

    def run_reasoning(self, goal, max_steps, initial_context):
        self.commands.append(f"reasoning:{initial_context}")
        if self.reasoning_results:
            return self.reasoning_results.pop(0)
        return {
            "status": "finished",
            "stop_reason": "finish",
            "files_modified": ["igris/core/fix.py"],
            "final_summary": "repair",
            "goal": goal,
        }

    def git_diff_stat(self):
        return self.diff_stat

    def git_diff(self):
        return self.diff

    def run_tests(self, targets=None):
        self.commands.append(f"tests:{targets or 'full'}")
        if targets:
            return self.targeted
        if self.full_tests:
            return self.full_tests.pop(0)
        return CommandResult(True, "full ok")

    def smoke(self, endpoints, restart_command=""):
        self.commands.append(f"smoke:{endpoints}")
        return self.smoke_result

    def commit(self, message, files=None):
        self.commands.append("commit")
        return CommandResult(True, "commit")

    def push_branch(self, branch):
        self.commands.append("push")
        return CommandResult(True, "push")

    def open_pr(self, branch, title, body):
        self.commands.append("pr")
        return CommandResult(True, "https://example.test/pr/1")

    def wait_ci(self):
        self.commands.append("ci")
        return CommandResult(True, "ci ok")

    def merge_pr(self):
        self.commands.append("merge")
        return CommandResult(True, "merged")

    def pull_main(self):
        self.commands.append("pull")
        return CommandResult(True, "pulled")

    def create_issue(self, title, body):
        self.commands.append("issue")
        return CommandResult(True, "issue")

    def restore_dangerous_diff(self):
        self.commands.append("restore")
        return CommandResult(False, "", "not enabled")


def _config(**overrides):
    data = {
        "goal": "Rank A controlled task with tests",
        "rank_id": "A",
        "max_rank_attempts": 2,
        "max_repair_cycles": 1,
        "required_smoke_endpoints": ["http://127.0.0.1:7778/api/health"],
        "targeted_tests": ["tests/test_rank_status.py"],
        "dry_run": True,
    }
    data.update(overrides)
    return RankSupervisorConfig.from_dict(data)


def test_failure_classifier_detects_max_steps_as_repairable_infrastructure_failure():
    failure = classify_failure({"status": "stopped", "stop_reason": "max_steps", "files_modified": []})
    assert failure == "max_steps"


def test_failure_classifier_detects_pytest_failure():
    failure = classify_failure(full_tests=CommandResult(False, "FAILED tests/test_x.py", "", 1))
    assert failure == "pytest_failure"


def test_failure_classifier_detects_destructive_diff():
    failure = classify_failure(diff="-def create_app():\n+def removed():\n")
    assert failure == "destructive_diff"


def test_supervisor_does_not_proceed_when_workspace_dirty():
    backend = FakeBackend()
    backend.status = CommandResult(True, " M igris/web/server.py\n")
    run = SelfRepairSupervisor("/tmp/project", backend=backend).run(_config())

    assert run.status == "blocked"
    assert run.failure_class == "workspace_dirty"
    assert not any(cmd.startswith("branch:") for cmd in backend.commands)


def test_supervisor_blocks_merge_when_full_pytest_fails():
    backend = FakeBackend()
    backend.full_tests = [
        CommandResult(True, "baseline ok"),
        CommandResult(False, "1 failed", "", 1),
    ]
    run = SelfRepairSupervisor("/tmp/project", backend=backend).run(_config(dry_run=False, allow_github_pr=True, allow_merge_if_green=True, max_repair_cycles=0))

    assert run.status == "blocked"
    assert run.failure_class == "pytest_failure"
    assert "merge" not in backend.commands


def test_supervisor_produces_blocked_report_after_repair_budget_exhausted():
    backend = FakeBackend()
    backend.reasoning_results = [{
        "status": "stopped",
        "stop_reason": "max_steps",
        "files_modified": [],
        "final_summary": "stopped",
        "goal": "rank task with tests",
    }]
    run = SelfRepairSupervisor("/tmp/project", backend=backend).run(_config(max_repair_cycles=0))

    assert run.status == "blocked"
    assert run.failure_class == "max_steps"
    assert run.report["blocked_reason"]


def test_supervisor_passes_after_one_repair_cycle():
    backend = FakeBackend()
    backend.reasoning_results = [
        {
            "status": "stopped",
            "stop_reason": "max_steps",
            "files_modified": [],
            "final_summary": "stopped",
            "goal": "rank task with tests",
        },
        {
            "status": "finished",
            "stop_reason": "finish",
            "files_modified": ["igris/core/fix.py"],
            "final_summary": "repair ok",
            "goal": "repair",
        },
        {
            "status": "finished",
            "stop_reason": "finish",
            "files_modified": ["igris/web/server.py", "tests/test_rank_status.py"],
            "final_summary": "rank ok",
            "goal": "rank task with tests",
        },
    ]
    run = SelfRepairSupervisor("/tmp/project", backend=backend).run(_config(max_rank_attempts=2, max_repair_cycles=1))

    assert run.status == "completed"
    assert run.repair_cycles_used == 1
    assert any(event.phase == "repair_reasoning" for event in run.events)


def test_rank_supervisor_api_dry_run_blocks_dirty_repo(monkeypatch):
    class DirtySupervisor:
        def run(self, config):
            backend = FakeBackend()
            backend.status = CommandResult(True, " M file.py\n")
            return SelfRepairSupervisor("/tmp/project", backend=backend).run(config)

    import igris.core.self_repair_supervisor as mod

    def fake_start(data, project_root):
        run = DirtySupervisor().run(RankSupervisorConfig.from_dict(data))
        mod.RUN_STORE[run.run_id] = run
        return run

    monkeypatch.setattr(mod, "start_supervised_rank", fake_start)
    client = TestClient(create_app())
    resp = client.post("/api/rank/run-supervised", json={"goal": "rank", "dry_run": True})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    detail = client.get(f"/api/rank/runs/{data['run_id']}")
    assert detail.status_code == 200
    listed = client.get("/api/rank/runs")
    assert listed.status_code == 200
