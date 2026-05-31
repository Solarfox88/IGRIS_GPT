"""PR 2 — Command Risk Engine hardening tests.

Covers:
- bash -c / python -c / sh -c detection (inline exec → CRITICAL)
- xargs rm detection (→ HIGH or CRITICAL with sudo/wildcard)
- find -delete / find -exec rm detection (→ HIGH or CRITICAL with sudo/abs_path)
- Template param injection validation
- RollbackPlan structured output
- HostAwarePolicy environment inference
"""

from __future__ import annotations

import pytest

from igris.core.command_risk_engine import (
    CommandRiskEngine,
    HostAwarePolicy,
    ParsedCommand,
    RiskReviewResult,
    RollbackPlan,
    SafetyEvent,
    classify_command_risk,
    parse_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _engine(environment: str = "dev") -> CommandRiskEngine:
    return CommandRiskEngine(environment=environment, use_llm_reviewer=False)


def _classify(cmd: str) -> str:
    return classify_command_risk(parse_command(cmd))


# ---------------------------------------------------------------------------
# 1. Inline exec detection (bash -c, sh -c, python -c)
# ---------------------------------------------------------------------------

class TestInlineExecDetection:

    def test_bash_c_is_parsed(self):
        p = parse_command('bash -c "echo hello"')
        assert p.has_inline_exec is True

    def test_sh_c_is_parsed(self):
        p = parse_command("sh -c 'rm -rf /tmp/test'")
        assert p.has_inline_exec is True

    def test_zsh_c_is_parsed(self):
        p = parse_command("zsh -c 'ls'")
        assert p.has_inline_exec is True

    def test_python_c_is_parsed(self):
        p = parse_command('python3 -c "import os; os.system(\'rm -rf /\')"')
        assert p.has_inline_exec is True

    def test_python2_c_is_parsed(self):
        p = parse_command("python -c 'print(1)'")
        assert p.has_inline_exec is True

    def test_bash_c_classifies_as_critical(self):
        assert _classify('bash -c "echo hello"') == "critical"

    def test_sh_c_classifies_as_critical(self):
        assert _classify("sh -c 'whoami'") == "critical"

    def test_python_c_classifies_as_critical(self):
        assert _classify('python3 -c "import os; os.getenv()"') == "critical"

    def test_evaluate_bash_c_blocked(self):
        engine = _engine()
        event, _ = engine.evaluate_command('bash -c "ls"')
        assert event.decision == "blocked"
        assert event.final_risk == "critical"

    def test_plain_bash_without_c_flag_not_inline(self):
        p = parse_command("bash myscript.sh")
        assert p.has_inline_exec is False

    def test_python_without_c_flag_not_inline(self):
        p = parse_command("python3 manage.py migrate")
        assert p.has_inline_exec is False


# ---------------------------------------------------------------------------
# 2. xargs rm detection
# ---------------------------------------------------------------------------

class TestXargsRmDetection:

    def test_xargs_rm_is_parsed(self):
        p = parse_command("find . -name '*.pyc' | xargs rm")
        assert p.has_xargs_rm is True

    def test_xargs_rm_rf_is_parsed(self):
        p = parse_command("find /tmp -mtime +7 | xargs rm -rf")
        assert p.has_xargs_rm is True

    def test_xargs_rm_classifies_as_high(self):
        # '*.pyc' contains wildcard → critical (correct: xargs rm + wildcard = critical)
        # Use a non-wildcard path to get pure HIGH classification
        assert _classify("find /tmp -type f | xargs rm") == "high"

    def test_xargs_rm_with_sudo_is_critical(self):
        assert _classify("sudo find /etc | xargs rm") == "critical"

    def test_xargs_rm_with_wildcard_is_critical(self):
        assert _classify("find . -name '*' | xargs rm") == "critical"

    def test_evaluate_xargs_rm_needs_approval(self):
        engine = _engine()
        # No wildcard → HIGH → needs_approval
        event, _ = engine.evaluate_command("find /tmp -type f | xargs rm")
        assert event.decision in ("needs_approval", "blocked")
        assert event.final_risk in ("high", "critical")

    def test_plain_xargs_without_rm_not_detected(self):
        p = parse_command("find . -name '*.txt' | xargs grep pattern")
        assert p.has_xargs_rm is False


# ---------------------------------------------------------------------------
# 3. find -delete detection
# ---------------------------------------------------------------------------

class TestFindDeleteDetection:

    def test_find_delete_flag_is_parsed(self):
        p = parse_command("find /tmp -mtime +7 -delete")
        assert p.has_find_delete is True

    def test_find_exec_rm_is_parsed(self):
        p = parse_command("find . -name '*.pyc' -exec rm {} \\;")
        assert p.has_find_delete is True

    def test_find_exec_unlink_is_parsed(self):
        p = parse_command("find . -name '*.log' -exec unlink {} \\;")
        assert p.has_find_delete is True

    def test_find_delete_classifies_as_high(self):
        assert _classify("find . -name '*.pyc' -delete") == "high"

    def test_find_delete_with_sudo_is_critical(self):
        assert _classify("sudo find /etc -name '*.bak' -delete") == "critical"

    def test_find_delete_with_abs_path_is_critical(self):
        assert _classify("find /var/log -name '*.log' -delete") == "critical"

    def test_plain_find_without_delete_not_detected(self):
        p = parse_command("find . -name '*.py' -type f")
        assert p.has_find_delete is False


# ---------------------------------------------------------------------------
# 4. Template param injection validation
# ---------------------------------------------------------------------------

class TestTemplateParamValidation:

    def test_safe_params_allowed(self):
        engine = _engine()
        event, review = engine.evaluate_template(
            "pytest_run", {"path": "tests/test_foo.py"}
        )
        # Should not be blocked due to param injection
        assert "template param injection" not in event.reason

    def test_semicolon_in_param_blocked(self):
        engine = _engine()
        event, review = engine.evaluate_template(
            "pytest_run", {"path": "tests/test_foo.py; rm -rf /"}
        )
        assert event.decision == "blocked"
        assert "template param injection" in event.reason
        assert event.final_risk == "critical"

    def test_pipe_in_param_blocked(self):
        engine = _engine()
        event, review = engine.evaluate_template(
            "cat_file", {"path": "/etc/passwd | cat"}
        )
        assert event.decision == "blocked"
        assert "template param injection" in event.reason

    def test_backtick_in_param_blocked(self):
        engine = _engine()
        event, review = engine.evaluate_template(
            "ls_dir", {"path": "`whoami`"}
        )
        assert event.decision == "blocked"
        assert "template param injection" in event.reason

    def test_dollar_subshell_in_param_blocked(self):
        engine = _engine()
        event, review = engine.evaluate_template(
            "ls_dir", {"path": "$(cat /etc/passwd)"}
        )
        assert event.decision == "blocked"
        assert "template param injection" in event.reason

    def test_ampersand_in_param_blocked(self):
        engine = _engine()
        event, review = engine.evaluate_template(
            "cat_file", {"path": "file.txt && rm -rf /"}
        )
        assert event.decision == "blocked"
        assert "template param injection" in event.reason

    def test_newline_in_param_blocked(self):
        engine = _engine()
        event, review = engine.evaluate_template(
            "cat_file", {"path": "file.txt\nrm -rf /"}
        )
        assert event.decision == "blocked"

    def test_safe_package_name_allowed(self):
        engine = _engine()
        event, _ = engine.evaluate_template(
            "pip_install", {"package": "requests==2.31.0"}
        )
        assert "template param injection" not in event.reason

    def test_path_with_slash_and_dash_allowed(self):
        engine = _engine()
        event, _ = engine.evaluate_template(
            "ls_dir", {"path": "/home/user/my-project"}
        )
        assert "template param injection" not in event.reason

    def test_validate_template_params_static_method(self):
        from igris.core.command_risk_engine import _UNSAFE_PARAM_CHARS_RE
        # Direct test of the validator
        engine = CommandRiskEngine.__new__(CommandRiskEngine)
        result = engine._validate_template_params({"path": "safe/path.py"})
        assert result is None
        result = engine._validate_template_params({"path": "safe; rm -rf /"})
        assert result is not None
        assert "path" in result


# ---------------------------------------------------------------------------
# 5. RollbackPlan structured output
# ---------------------------------------------------------------------------

class TestRollbackPlan:

    def _make_event(self, risk: str) -> SafetyEvent:
        return SafetyEvent(
            command="test",
            final_risk=risk,
            decision="blocked",
        )

    def test_rollback_plan_is_dataclass(self):
        plan = RollbackPlan(command="rm -rf /tmp", risk_level="high")
        assert plan.command == "rm -rf /tmp"
        assert plan.risk_level == "high"
        assert isinstance(plan.steps, list)

    def test_build_rollback_plan_for_rm(self):
        engine = _engine()
        event = self._make_event("high")
        event.command = "rm -rf /tmp/old"
        plan = engine.build_rollback_plan("rm -rf /tmp/old", event)
        assert isinstance(plan, RollbackPlan)
        assert len(plan.steps) > 0
        assert plan.backup_cmd != ""
        assert plan.restore_cmd != ""

    def test_build_rollback_plan_for_git_reset(self):
        engine = _engine()
        event = self._make_event("high")
        plan = engine.build_rollback_plan("git reset --hard HEAD~1", event)
        assert "reflog" in " ".join(plan.steps).lower() or "SHA" in " ".join(plan.steps)
        assert plan.restore_cmd != ""

    def test_build_rollback_plan_for_db_drop(self):
        engine = _engine()
        event = self._make_event("critical")
        plan = engine.build_rollback_plan("DROP TABLE users", event)
        assert "pg_dump" in plan.backup_cmd or "backup" in " ".join(plan.steps).lower()
        assert plan.automated is False

    def test_build_rollback_plan_for_bash_c(self):
        engine = _engine()
        event = self._make_event("critical")
        plan = engine.build_rollback_plan('bash -c "rm -rf /tmp"', event)
        assert len(plan.steps) > 0
        assert plan.automated is False

    def test_build_rollback_plan_for_dd(self):
        engine = _engine()
        event = self._make_event("critical")
        plan = engine.build_rollback_plan("dd if=/dev/zero of=/dev/sda", event)
        assert "irreversible" in plan.notes.lower() or "backup" in plan.notes.lower()

    def test_build_rollback_plan_to_dict(self):
        plan = RollbackPlan(
            command="rm -rf /",
            risk_level="critical",
            steps=["step1"],
            automated=False,
        )
        d = plan.to_dict()
        assert d["command"] == "rm -rf /"
        assert d["risk_level"] == "critical"
        assert d["steps"] == ["step1"]
        assert d["automated"] is False

    def test_get_rollback_suggestion_still_works(self):
        """Backwards compat: get_rollback_suggestion() should return a string."""
        engine = _engine()
        event = self._make_event("high")
        result = engine.get_rollback_suggestion("rm -rf /tmp", event)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 6. HostAwarePolicy
# ---------------------------------------------------------------------------

class TestHostAwarePolicy:

    def test_production_hostname_inferred(self):
        assert HostAwarePolicy.infer_environment("web-prod-01") == "production"

    def test_production_hostname_prd(self):
        assert HostAwarePolicy.infer_environment("igris-prd-worker") == "production"

    def test_staging_hostname_inferred(self):
        assert HostAwarePolicy.infer_environment("igris-staging-01") == "staging"

    def test_staging_hostname_stg(self):
        assert HostAwarePolicy.infer_environment("worker-stg-02") == "staging"

    def test_dev_hostname_inferred(self):
        assert HostAwarePolicy.infer_environment("my-laptop") == "dev"

    def test_dev_hostname_inferred_when_empty(self):
        # Should not raise; falls through to dev
        result = HostAwarePolicy.infer_environment("localhost")
        assert result == "dev"

    def test_from_hostname_returns_engine(self):
        engine = HostAwarePolicy.from_hostname("web-prod-01")
        assert isinstance(engine, CommandRiskEngine)
        assert engine.environment == "production"

    def test_from_hostname_dev(self):
        engine = HostAwarePolicy.from_hostname("my-laptop")
        assert engine.environment == "dev"

    def test_production_engine_blocks_high_risk(self):
        """Production engine must block HIGH-risk commands."""
        engine = HostAwarePolicy.from_hostname("web-prod-01")
        engine.use_llm_reviewer = False
        event, _ = engine.evaluate_command("rm -rf /tmp/old")
        assert event.decision == "blocked"

    def test_dev_engine_allows_medium_risk(self):
        """Dev engine allows medium-risk commands (just logs)."""
        engine = HostAwarePolicy.from_hostname("localhost")
        engine.use_llm_reviewer = False
        event, _ = engine.evaluate_command("pip install requests")
        assert event.decision == "allowed"


# ---------------------------------------------------------------------------
# 7. Full evaluate_command integration
# ---------------------------------------------------------------------------

class TestEvaluateCommandIntegration:

    def test_bash_c_always_blocked(self):
        for env in ("dev", "staging", "production"):
            engine = _engine(env)
            event, _ = engine.evaluate_command('bash -c "whoami"')
            assert event.decision == "blocked", f"env={env} should block bash -c"

    def test_find_delete_dev_needs_approval(self):
        engine = _engine("dev")
        event, _ = engine.evaluate_command("find . -name '*.pyc' -delete")
        assert event.decision in ("needs_approval", "blocked")

    def test_find_delete_production_blocked(self):
        engine = _engine("production")
        # find -delete in production: destructive → critical → blocked
        event, _ = engine.evaluate_command("find /tmp -mtime +7 -delete")
        assert event.decision == "blocked"

    def test_xargs_rm_production_blocked(self):
        engine = _engine("production")
        event, _ = engine.evaluate_command("find . -name '*.tmp' | xargs rm")
        assert event.decision == "blocked"

    def test_safe_ls_still_allowed(self):
        engine = _engine()
        event, _ = engine.evaluate_command("ls -la /tmp")
        assert event.final_risk == "low"
        assert event.decision == "allowed"
