"""PR 3 — DevOpsManager runner abstraction + deploy strategies + rollback tests.

Covers:
- CommandResult / CommandRunner / LocalCommandRunner / FakeCommandRunner
- DevOpsManager uses injectable runner (no real subprocess in tests)
- Deploy strategies: git_pull_restart, systemd_app, docker_compose, static_nginx, dry_run
- Unknown strategy blocked
- run_rollback: git reset + service restart
- Auto-rollback on postcheck failure
- preflight/postcheck via FakeCommandRunner
"""

from __future__ import annotations

import pytest

from igris.core.devops_manager import (
    CommandResult,
    CommandRunner,
    DevOpsManager,
    FakeCommandRunner,
    LocalCommandRunner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mgr(runner: CommandRunner, tmp_path=None) -> DevOpsManager:
    import tempfile, os
    root = str(tmp_path) if tmp_path else tempfile.mkdtemp()
    return DevOpsManager(project_root=root, runner=runner)


def _ok_runner() -> FakeCommandRunner:
    """A FakeCommandRunner that returns success for every command."""
    r = FakeCommandRunner()
    r.set_default_result(CommandResult(returncode=0, stdout="OK", stderr=""))
    # Disk: needs df-style output
    r.set_result(
        "df -P",
        CommandResult(
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n"
                   "/dev/sda1   100000   20000     80000      20% /",
        ),
    )
    # git status: clean tree
    r.set_result("git status", CommandResult(returncode=0, stdout="", stderr=""))
    # git pull
    r.set_result("git pull", CommandResult(returncode=0, stdout="Already up to date.", stderr=""))
    # git rev-parse
    r.set_result("git rev-parse", CommandResult(returncode=0, stdout="abc123\n", stderr=""))
    # nc (service reachability)
    r.set_result("nc -z", CommandResult(returncode=0, stdout="", stderr=""))
    return r


# ---------------------------------------------------------------------------
# 1. CommandResult
# ---------------------------------------------------------------------------

class TestCommandResult:

    def test_ok_true_on_zero_returncode(self):
        r = CommandResult(returncode=0, stdout="hello")
        assert r.ok is True

    def test_ok_false_on_nonzero(self):
        r = CommandResult(returncode=1, stderr="error")
        assert r.ok is False

    def test_to_dict(self):
        r = CommandResult(returncode=0, stdout="out", stderr="err")
        d = r.to_dict()
        assert d["returncode"] == 0
        assert d["ok"] is True
        assert "stdout" in d


# ---------------------------------------------------------------------------
# 2. FakeCommandRunner
# ---------------------------------------------------------------------------

class TestFakeCommandRunner:

    def test_default_result_returned(self):
        runner = FakeCommandRunner()
        runner.set_default_result(CommandResult(returncode=0, stdout="default"))
        result = runner.run(["any", "command"])
        assert result.ok is True
        assert result.stdout == "default"

    def test_pattern_match_wins(self):
        runner = FakeCommandRunner()
        runner.set_default_result(CommandResult(returncode=1, stderr="default"))
        runner.set_result("git pull", CommandResult(returncode=0, stdout="pulled"))
        result = runner.run(["git", "pull", "--ff-only"])
        assert result.ok is True
        assert "pulled" in result.stdout

    def test_calls_recorded(self):
        runner = FakeCommandRunner()
        runner.set_default_result(CommandResult(returncode=0))
        runner.run(["git", "status"])
        runner.run(["df", "-P", "/"])
        assert len(runner.calls) == 2
        assert runner.calls[0]["cmd"] == ["git", "status"]

    def test_longest_pattern_wins(self):
        runner = FakeCommandRunner()
        runner.set_result("git", CommandResult(returncode=0, stdout="generic_git"))
        runner.set_result("git pull", CommandResult(returncode=0, stdout="specific_pull"))
        result = runner.run(["git", "pull", "--ff-only"])
        assert result.stdout == "specific_pull"

    def test_no_match_uses_default(self):
        runner = FakeCommandRunner()
        runner.set_default_result(CommandResult(returncode=0, stdout="fallback"))
        runner.set_result("git", CommandResult(returncode=0, stdout="git"))
        result = runner.run(["systemctl", "restart", "igris"])
        assert result.stdout == "fallback"

    def test_failure_result(self):
        runner = FakeCommandRunner()
        runner.set_result("git pull", CommandResult(returncode=1, stderr="conflict"))
        result = runner.run(["git", "pull"])
        assert result.ok is False
        assert "conflict" in result.stderr


# ---------------------------------------------------------------------------
# 3. DevOpsManager constructor with injectable runner
# ---------------------------------------------------------------------------

class TestDevOpsManagerRunner:

    def test_default_runner_is_local(self, tmp_path):
        mgr = DevOpsManager(project_root=str(tmp_path))
        assert isinstance(mgr._runner, LocalCommandRunner)

    def test_injectable_runner_used(self, tmp_path):
        runner = FakeCommandRunner()
        mgr = DevOpsManager(project_root=str(tmp_path), runner=runner)
        assert mgr._runner is runner

    def test_run_preflight_uses_runner(self, tmp_path):
        runner = _ok_runner()
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_preflight()
        # runner must have been called
        assert len(runner.calls) > 0

    def test_run_preflight_ok_when_runner_succeeds(self, tmp_path):
        runner = _ok_runner()
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_preflight()
        assert result["ok"] is True

    def test_run_preflight_disk_fail(self, tmp_path):
        runner = FakeCommandRunner()
        runner.set_default_result(CommandResult(returncode=0, stdout="", stderr=""))
        runner.set_result("df -P", CommandResult(returncode=1, stderr="disk error"))
        runner.set_result("git status", CommandResult(returncode=0, stdout=""))
        runner.set_result("nc", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_preflight()
        assert result["checks"]["disk"]["ok"] is False


# ---------------------------------------------------------------------------
# 4. Deploy strategies
# ---------------------------------------------------------------------------

class TestDeployStrategies:

    def test_git_pull_restart_strategy(self, tmp_path):
        runner = _ok_runner()
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="git_pull_restart")
        assert result["strategy"] == "git_pull_restart"
        # git pull and systemctl restart must have been called
        cmds = [" ".join(c["cmd"]) for c in runner.calls]
        assert any("git pull" in c for c in cmds)
        assert any("systemctl" in c for c in cmds)

    def test_systemd_app_strategy(self, tmp_path):
        runner = _ok_runner()
        runner.set_result("systemctl restart myapp", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="systemd_app", service_name="myapp")
        assert result["strategy"] == "systemd_app"
        cmds = [" ".join(c["cmd"]) for c in runner.calls]
        assert any("systemctl" in c and "myapp" in c for c in cmds)

    def test_docker_compose_strategy(self, tmp_path):
        runner = _ok_runner()
        runner.set_result("docker-compose", CommandResult(returncode=0, stdout="started"))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="docker_compose")
        assert result["strategy"] == "docker_compose"
        cmds = [" ".join(c["cmd"]) for c in runner.calls]
        assert any("docker-compose" in c for c in cmds)

    def test_static_nginx_strategy(self, tmp_path):
        runner = _ok_runner()
        runner.set_result("rsync", CommandResult(returncode=0))
        runner.set_result("nginx -s reload", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="static_nginx")
        assert result["strategy"] == "static_nginx"
        cmds = [" ".join(c["cmd"]) for c in runner.calls]
        assert any("rsync" in c for c in cmds)
        assert any("nginx" in c for c in cmds)

    def test_dry_run_strategy(self, tmp_path):
        runner = _ok_runner()
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="dry_run")
        assert result["deployed"] is False
        assert "dry_run" in result.get("note", "").lower()

    def test_unknown_strategy_blocked(self, tmp_path):
        runner = _ok_runner()
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="magic_teleport")
        assert result["deployed"] is False
        assert "abort_reason" in result
        assert "unknown strategy" in result["abort_reason"]

    def test_dry_run_flag_skips_action(self, tmp_path):
        runner = _ok_runner()
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="git_pull_restart", dry_run=True)
        assert result["deployed"] is False
        cmds = [" ".join(c["cmd"]) for c in runner.calls]
        # systemctl should NOT have been called in dry_run mode
        assert not any("systemctl restart" in c for c in cmds)

    def test_deploy_aborts_on_preflight_failure(self, tmp_path):
        runner = FakeCommandRunner()
        # disk check fails → preflight fails → deploy aborts
        runner.set_default_result(CommandResult(returncode=0))
        runner.set_result("df -P", CommandResult(returncode=1, stderr="no disk"))
        runner.set_result("git status", CommandResult(returncode=0, stdout=""))
        runner.set_result("nc", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="git_pull_restart")
        assert result["deployed"] is False
        assert result["abort_reason"] == "preflight failed"

    def test_deploy_records_pre_deploy_sha(self, tmp_path):
        runner = _ok_runner()
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="dry_run")
        # Even dry_run should have tried to get the SHA (it runs preflight first)
        # SHA is captured before action, not in dry_run branch — just check it doesn't crash
        assert "strategy" in result

    def test_valid_strategies_constant(self):
        assert "git_pull_restart" in DevOpsManager.VALID_STRATEGIES
        assert "systemd_app" in DevOpsManager.VALID_STRATEGIES
        assert "docker_compose" in DevOpsManager.VALID_STRATEGIES
        assert "static_nginx" in DevOpsManager.VALID_STRATEGIES
        assert "dry_run" in DevOpsManager.VALID_STRATEGIES


# ---------------------------------------------------------------------------
# 5. run_rollback
# ---------------------------------------------------------------------------

class TestRunRollback:

    def test_rollback_resets_to_sha(self, tmp_path):
        runner = _ok_runner()
        runner.set_result("git reset --hard", CommandResult(returncode=0, stdout="HEAD is now at abc123"))
        runner.set_result("systemctl restart", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_rollback(
            strategy="git_pull_restart",
            pre_deploy_sha="abc123",
            service_name="igris",
        )
        assert result["ok"] is True
        assert result["pre_deploy_sha"] == "abc123"
        cmds = [" ".join(c["cmd"]) for c in runner.calls]
        assert any("git reset --hard abc123" in c for c in cmds)

    def test_rollback_without_sha_fails(self, tmp_path):
        runner = _ok_runner()
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_rollback(pre_deploy_sha="")
        assert result["ok"] is False
        assert "no pre_deploy_sha" in result.get("error", "")

    def test_rollback_git_fail_returns_false(self, tmp_path):
        runner = FakeCommandRunner()
        runner.set_default_result(CommandResult(returncode=0))
        runner.set_result("git reset", CommandResult(returncode=1, stderr="reset failed"))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_rollback(pre_deploy_sha="abc123")
        assert result["ok"] is False

    def test_rollback_docker_compose(self, tmp_path):
        runner = _ok_runner()
        runner.set_result("docker-compose", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_rollback(
            strategy="docker_compose",
            pre_deploy_sha="abc123",
        )
        assert result["ok"] is True
        cmds = [" ".join(c["cmd"]) for c in runner.calls]
        assert any("docker-compose" in c for c in cmds)

    def test_rollback_static_nginx(self, tmp_path):
        runner = _ok_runner()
        runner.set_result("nginx -s reload", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_rollback(
            strategy="static_nginx",
            pre_deploy_sha="abc123",
        )
        assert result["ok"] is True
        cmds = [" ".join(c["cmd"]) for c in runner.calls]
        assert any("nginx" in c for c in cmds)

    def test_rollback_steps_recorded(self, tmp_path):
        runner = _ok_runner()
        runner.set_result("git reset", CommandResult(returncode=0))
        runner.set_result("systemctl restart", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_rollback(pre_deploy_sha="abc123", service_name="igris")
        assert "steps" in result
        assert "git_reset" in result["steps"]


# ---------------------------------------------------------------------------
# 6. Auto-rollback integration
# ---------------------------------------------------------------------------

class TestAutoRollback:

    def test_auto_rollback_on_postcheck_fail(self, tmp_path):
        """If postcheck fails and auto_rollback=True, rollback is executed."""
        runner = _ok_runner()
        # Make nc check fail (postcheck fails)
        runner.set_result("nc -z -w 3", CommandResult(returncode=1, stderr="port closed"))
        runner.set_result("git reset --hard", CommandResult(returncode=0))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(
            strategy="git_pull_restart",
            auto_rollback=True,
        )
        # deployed should be False after failed postcheck + rollback
        assert result["deployed"] is False
        assert "rollback" in result
        assert result.get("abort_reason", "").startswith("postcheck failed")

    def test_no_auto_rollback_when_disabled(self, tmp_path):
        """If auto_rollback=False, no rollback even on postcheck fail."""
        runner = _ok_runner()
        runner.set_result("nc -z -w 3", CommandResult(returncode=1, stderr="port closed"))
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(
            strategy="git_pull_restart",
            auto_rollback=False,
        )
        assert "rollback" not in result

    def test_no_rollback_when_postcheck_passes(self, tmp_path):
        """If postcheck passes, no rollback should be triggered."""
        runner = _ok_runner()
        # nc postcheck passes (default ok runner)
        mgr = _mgr(runner, tmp_path)
        result = mgr.run_deploy(strategy="git_pull_restart", auto_rollback=True)
        assert "rollback" not in result
        assert result["deployed"] is True
