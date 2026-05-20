"""Integration tests for API helper A/B shadow mode — Epic #445."""
from __future__ import annotations
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from igris.core.self_repair_supervisor import LocalSupervisorBackend, CommandResult

def _make_backend():
    return LocalSupervisorBackend(project_root=Path("/tmp"))

def _codex_response(**overrides):
    base = {"ok": True, "model": "gpt-5.3-codex", "api_helper_mode": "codex_only", "api_helper_provider": "openai", "api_helper_model_requested": "gpt-5.3-codex", "api_helper_model_resolved": "gpt-5.3-codex", "codex_only": True, "summary": "Route missing.", "diagnosis": "igris/web/routes/__init__.py line 45 missing include_router(users_router)", "likely_supervisor_gap": "supervisor skipped router registration", "suggested_repair_strategy": "add include_router", "execution_plan": ["open routes/__init__.py", "add include_router(users_router)", "run pytest tests/test_users.py"], "acceptance_matrix": [{"test": "tests/test_users.py::test_get_user", "assertion": "status_code == 200"}], "suggested_tests": ["tests/test_users.py::test_get_user"], "risk": "low", "risk_notes": [], "do_not_do": ["skip"], "confidence": 0.85, "requires_human_or_codex_audit": False, "must_not_complete_product_manually": True, "estimated_cost_usd": 0.0012}
    base.update(overrides)
    return json.dumps(base)

def _deepseek_response(**overrides):
    base = {"ok": True, "model": "deepseek-v4-pro", "api_helper_mode": "auto", "api_helper_provider": "deepseek", "api_helper_model_requested": "deepseek-v4-pro", "api_helper_model_resolved": "deepseek-v4-pro", "codex_only": False, "summary": "Missing router.", "diagnosis": "include_router missing in routes/__init__.py", "likely_supervisor_gap": "router include skipped", "suggested_repair_strategy": "add include_router", "execution_plan": ["edit routes/__init__.py", "run pytest"], "acceptance_matrix": [{"test": "tests/test_users.py::test_get_user", "assertion": "status_code == 200"}], "suggested_tests": ["tests/test_users.py::test_get_user"], "risk": "low", "risk_notes": [], "do_not_do": ["hardcode"], "confidence": 0.80, "requires_human_or_codex_audit": False, "must_not_complete_product_manually": True, "estimated_cost_usd": 0.0005}
    base.update(overrides)
    return json.dumps(base)

class TestBothCallersOnlyWhenEnabled:
    def test_both_called_when_ab_enabled(self):
        backend = _make_backend()
        call_count = {"n": 0}
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_count["n"] += 1
            return CommandResult(success=True, output=_codex_response() if call_count["n"]==1 else _deepseek_response(), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "true", "IGRIS_HELPER_AB_SHADOW_MODE": "true", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro", "IGRIS_API_HELPER_ALT_PROVIDER": "deepseek", "IGRIS_HELPER_AB_RESULTS_PATH": "/tmp/test_ab_both.json"}):
            backend.call_api_helper(packet={"goal": "test", "failure_class": "pytest_failure"}, model="gpt-5.3-codex", max_tokens=600)
        assert call_count["n"] == 2, f"Expected 2 calls, got {call_count['n']}"

    def test_only_primary_called_when_ab_disabled(self):
        backend = _make_backend()
        call_count = {"n": 0}
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_count["n"] += 1
            return CommandResult(success=True, output=_codex_response(), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "false", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro"}):
            backend.call_api_helper(packet={"goal": "test"}, model="gpt-5.3-codex", max_tokens=600)
        assert call_count["n"] == 1, f"Expected 1 call, got {call_count['n']}"

class TestPrimaryAuthoritative:
    def test_primary_output_not_overwritten_by_shadow(self):
        backend = _make_backend()
        call_count = {"n": 0}
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_count["n"] += 1
            return CommandResult(success=True, output=_codex_response(confidence=0.85) if call_count["n"]==1 else _deepseek_response(confidence=0.20), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "true", "IGRIS_HELPER_AB_SHADOW_MODE": "true", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro", "IGRIS_HELPER_AB_RESULTS_PATH": "/tmp/test_ab_primary.json"}):
            result = backend.call_api_helper(packet={"goal": "test authority", "failure_class": "missing_tests"}, model="gpt-5.3-codex", max_tokens=600)
        assert json.loads(result.output)["confidence"] == 0.85
        assert result.helper_model == "gpt-5.3-codex"

    def test_helper_model_is_primary_not_alt(self):
        backend = _make_backend()
        call_count = {"n": 0}
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_count["n"] += 1
            return CommandResult(success=True, output=_codex_response() if call_count["n"]==1 else _deepseek_response(), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "true", "IGRIS_HELPER_AB_SHADOW_MODE": "true", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro", "IGRIS_HELPER_AB_RESULTS_PATH": "/tmp/test_ab_model.json"}):
            result = backend.call_api_helper(packet={"goal": "test", "failure_class": "pytest_failure"}, model="gpt-5.3-codex", max_tokens=600)
        assert result.helper_model == "gpt-5.3-codex"

class TestReportIncludes:
    def test_shadow_mode_fields_populated(self):
        backend = _make_backend()
        call_count = {"n": 0}
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_count["n"] += 1
            return CommandResult(success=True, output=_codex_response() if call_count["n"]==1 else _deepseek_response(), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "true", "IGRIS_HELPER_AB_SHADOW_MODE": "true", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro", "IGRIS_HELPER_AB_RESULTS_PATH": "/tmp/test_ab_report.json"}):
            result = backend.call_api_helper(packet={"goal": "test report", "failure_class": "pytest_failure"}, model="gpt-5.3-codex", max_tokens=600)
        assert result.helper_ab_shadow_mode is True
        assert result.helper_ab_active is True
        assert result.helper_ab_alt_model == "deepseek-v4-pro"
        assert hasattr(result, "helper_primary_score")
        assert hasattr(result, "helper_alt_score")
        assert hasattr(result, "helper_switch_recommendation")

class TestNoSecretsPersisted:
    def test_secrets_not_written_to_ab_results(self, tmp_path):
        backend = _make_backend()
        ab_path = str(tmp_path / "ab_no_secrets.json")
        call_count = {"n": 0}
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_count["n"] += 1
            out = _codex_response(diagnosis="use OPENAI_KEY=sk-proj-realkey12345678901234567 to debug") if call_count["n"]==1 else _deepseek_response()
            return CommandResult(success=True, output=out, returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "true", "IGRIS_HELPER_AB_SHADOW_MODE": "true", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro", "IGRIS_HELPER_AB_RESULTS_PATH": ab_path}):
            backend.call_api_helper(packet={"goal": "test secrets", "failure_class": "pytest_failure"}, model="gpt-5.3-codex", max_tokens=600)
        if os.path.exists(ab_path):
            assert "sk-proj-realkey" not in open(ab_path).read()

class TestAltModelEnv:
    def test_shadow_call_uses_alt_provider_env(self):
        backend = _make_backend()
        call_envs = []
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_envs.append(dict(extra_env or {}))
            return CommandResult(success=True, output=_codex_response(), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "true", "IGRIS_HELPER_AB_SHADOW_MODE": "true", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro", "IGRIS_API_HELPER_ALT_PROVIDER": "deepseek", "IGRIS_HELPER_AB_RESULTS_PATH": "/tmp/test_ab_env.json"}):
            backend.call_api_helper(packet={"goal": "test env", "failure_class": "pytest_failure"}, model="gpt-5.3-codex", max_tokens=600)
        assert len(call_envs) == 2
        assert call_envs[1].get("IGRIS_API_HELPER_PROVIDER") == "deepseek"
        assert call_envs[1].get("IGRIS_HELPER_AB_ARM") == "alt"

    def test_primary_call_uses_codex_mode(self):
        backend = _make_backend()
        call_envs = []
        def fake_run(cmd, timeout=45, input_text=None, extra_env=None, **kw):
            call_envs.append(dict(extra_env or {}))
            return CommandResult(success=True, output=_codex_response(), returncode=0)
        backend._run = fake_run
        with patch.dict(os.environ, {"IGRIS_API_HELPER_COMMAND": "echo", "IGRIS_ENABLE_HELPER_AB_TEST": "true", "IGRIS_HELPER_AB_SHADOW_MODE": "true", "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro", "IGRIS_HELPER_AB_RESULTS_PATH": "/tmp/test_ab_mode.json"}):
            backend.call_api_helper(packet={"goal": "test mode", "failure_class": "pytest_failure"}, model="gpt-5.3-codex", max_tokens=600, mode="codex_only")
        assert call_envs[0].get("IGRIS_API_HELPER_MODE") == "codex_only"
        assert "IGRIS_HELPER_AB_ARM" not in call_envs[0]
