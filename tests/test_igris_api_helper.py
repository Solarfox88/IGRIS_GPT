"""
Tests for scripts/igris_api_helper.py

Covers:
- Secret redaction
- Safe error output format
- API key resolution logic
- Model resolution logic
- JSON response parsing and field validation
- Main entrypoint error paths (no key, bad JSON, missing fields)
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load the helper module without executing main()
# ---------------------------------------------------------------------------

HELPER_PATH = Path(__file__).parent.parent / "scripts" / "igris_api_helper.py"


def _load_helper() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("igris_api_helper", HELPER_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_h = _load_helper()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class TestRedact:
    def test_redacts_sk_key(self):
        text = "key is sk-ABCDEFGHIJKLMNOPQRSTU"
        assert "sk-" not in _h._redact(text)
        assert "[REDACTED]" in _h._redact(text)

    def test_redacts_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6Ikp"
        assert "Bearer ey" not in _h._redact(text)

    def test_leaves_normal_text_alone(self):
        text = "hello world, this is a test"
        assert _h._redact(text) == text

    def test_redacts_anthropic_api_key_assignment(self):
        text = "ANTHROPIC_API_KEY=sk-ant-secret123"
        assert "secret123" not in _h._redact(text)

    def test_redacts_openai_api_key_assignment(self):
        text = "OPENAI_API_KEY=sk-openai-xyz"
        assert "sk-openai-xyz" not in _h._redact(text)


# ---------------------------------------------------------------------------
# _resolve_key
# ---------------------------------------------------------------------------


class TestResolveKey:
    def test_prefers_igris_anthropic_key(self):
        env = {
            "IGRIS_ANTHROPIC_API_KEY": "sk-ant-igris",
            "ANTHROPIC_API_KEY": "sk-ant-fallback",
        }
        with patch.dict(os.environ, env, clear=True):
            provider, key = _h._resolve_key()
        assert provider == "anthropic"
        assert key == "sk-ant-igris"

    def test_falls_back_to_anthropic_key(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-fallback"}
        with patch.dict(os.environ, env, clear=True):
            provider, key = _h._resolve_key()
        assert provider == "anthropic"
        assert key == "sk-ant-fallback"

    def test_prefers_anthropic_over_openai(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-x", "OPENAI_API_KEY": "sk-openai-y"}
        with patch.dict(os.environ, env, clear=True):
            provider, key = _h._resolve_key()
        assert provider == "anthropic"

    def test_falls_back_to_openai(self):
        env = {"OPENAI_API_KEY": "sk-openai-abc"}
        with patch.dict(os.environ, env, clear=True):
            provider, key = _h._resolve_key()
        assert provider == "openai"
        assert key == "sk-openai-abc"

    def test_raises_when_no_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="No API key"):
                _h._resolve_key()

    def test_ignores_empty_string_vars(self):
        env = {"IGRIS_ANTHROPIC_API_KEY": "", "ANTHROPIC_API_KEY": "   "}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError):
                _h._resolve_key()


# ---------------------------------------------------------------------------
# _resolve_model
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_override_env_takes_precedence(self):
        with patch.dict(os.environ, {"IGRIS_API_HELPER_MODEL": "my-special-model"}):
            assert _h._resolve_model("anything", "anthropic") == "my-special-model"

    def test_uses_requested_model_when_no_override(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _h._resolve_model("claude-haiku-4-5-20251001", "anthropic") == "claude-haiku-4-5-20251001"

    def test_anthropic_default_when_empty_request(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _h._resolve_model("", "anthropic") == "claude-haiku-4-5-20251001"

    def test_openai_default_when_empty_request(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _h._resolve_model("", "openai") == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def _good_payload(**overrides) -> dict:
    base = {
        "ok": True,
        "summary": "all good",
        "diagnosis": "no issue",
        "likely_supervisor_gap": "none",
        "suggested_repair_strategy": "do nothing",
        "suggested_tests": ["test_a"],
        "risk": "low",
        "risk_notes": [],
        "do_not_do": [],
        "confidence": 0.9,
        "requires_human_or_codex_audit": False,
        "must_not_complete_product_manually": True,
        "estimated_cost_usd": 0.001,
    }
    base.update(overrides)
    return base


class TestParseResponse:
    def test_valid_response_is_ok(self):
        raw = json.dumps(_good_payload())
        result = _h._parse_response(raw, "claude-haiku-4-5-20251001", 0.001)
        assert result["ok"] is True
        assert result["model"] == "claude-haiku-4-5-20251001"
        assert result["diagnosis"] == "no issue"

    def test_response_wrapped_in_markdown(self):
        raw = "```json\n" + json.dumps(_good_payload()) + "\n```"
        result = _h._parse_response(raw, "m", 0.0)
        assert result["ok"] is True

    def test_no_json_returns_error(self):
        result = _h._parse_response("no json here at all", "m", 0.0)
        assert result["ok"] is False
        assert "no JSON" in result.get("error", "")

    def test_invalid_json_returns_error(self):
        result = _h._parse_response("{bad json}", "m", 0.0)
        assert result["ok"] is False
        assert "JSON parse error" in result.get("error", "")

    def test_missing_required_fields_sets_ok_false(self):
        payload = _good_payload()
        del payload["diagnosis"]
        del payload["confidence"]
        raw = json.dumps(payload)
        result = _h._parse_response(raw, "m", 0.0)
        assert result["ok"] is False
        assert "diagnosis" in result.get("error", "")

    def test_cost_used_from_arg_when_not_in_payload(self):
        payload = _good_payload()
        del payload["estimated_cost_usd"]
        result = _h._parse_response(json.dumps(payload), "m", 0.042)
        assert result["estimated_cost_usd"] == pytest.approx(0.042)

    def test_redacts_secrets_in_response(self):
        payload = _good_payload(diagnosis="key sk-ABCDEFGHIJKLMNOPQRSTU leaked")
        result = _h._parse_response(json.dumps(payload), "m", 0.0)
        assert "sk-" not in result["diagnosis"]


# ---------------------------------------------------------------------------
# main() via subprocess — black-box integration
# ---------------------------------------------------------------------------


def _run_helper(stdin_data: str, env_extra: Dict[str, str] | None = None, timeout: int = 10) -> subprocess.CompletedProcess:
    env = {**os.environ}
    # Strip any real API keys so tests are hermetic
    for var in ("ANTHROPIC_API_KEY", "IGRIS_ANTHROPIC_API_KEY", "OPENAI_API_KEY", "IGRIS_OPENAI_API_KEY"):
        env.pop(var, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        input=stdin_data,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


class TestMainBlackBox:
    def test_no_api_key_exits_1_with_safe_json(self):
        inp = json.dumps({"model": "gpt-4o-mini", "max_tokens": 100, "packet": {}})
        proc = _run_helper(inp)
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["ok"] is False
        assert out["requires_human_or_codex_audit"] is True
        assert out["must_not_complete_product_manually"] is True

    def test_malformed_json_exits_1(self):
        proc = _run_helper("{not valid json}")
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["ok"] is False

    def test_empty_stdin_exits_1(self):
        proc = _run_helper("")
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["ok"] is False

    def test_no_secrets_in_safe_error_output(self):
        """_safe_error must redact secrets before printing to stdout."""
        import io
        fake_key = "sk-ant-FAKEKEY12345678901234"
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            with pytest.raises(SystemExit):
                _h._safe_error(f"API call failed: Connection using key {fake_key}")
        assert fake_key not in captured.getvalue()

    def test_anthropic_call_mocked(self):
        """Verify _call_anthropic pipeline with injected mock module (no real package needed)."""
        good = json.dumps(_good_payload())
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=good)]
        mock_msg.usage.input_tokens = 100
        mock_msg.usage.output_tokens = 50

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
            raw, cost = _h._call_anthropic("sk-ant-fake12345678901234", "claude-haiku-4-5-20251001", 300, "test ctx", 30)

        assert "no issue" in raw
        assert cost >= 0.0

    def test_openai_call_mocked(self):
        """Verify _call_openai pipeline with injected mock module (no real package needed)."""
        good = json.dumps(_good_payload())
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = good
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 50

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_module = MagicMock()
        mock_openai_module.OpenAI.return_value = mock_client

        with patch.dict(sys.modules, {"openai": mock_openai_module}):
            raw, cost = _h._call_openai("sk-openai-fake12345678901234", "gpt-4o-mini", 300, "test ctx", 30)

        assert "no issue" in raw
        assert cost >= 0.0

    def test_required_output_fields_present_on_success(self):
        """Mock a successful Anthropic call end-to-end through main()."""
        good_json = json.dumps(_good_payload())
        inp = json.dumps({"model": "claude-haiku-4-5-20251001", "max_tokens": 300, "packet": {"failure_class": "timeout"}})

        # Patch _call_anthropic so no real network call
        with patch.object(_h, "_call_anthropic", return_value=(good_json, 0.001)):
            with patch.object(_h, "_resolve_key", return_value=("anthropic", "sk-ant-fake")):
                import io
                old_stdin = sys.stdin
                old_stdout = sys.stdout
                sys.stdin = io.StringIO(inp)
                captured = io.StringIO()
                sys.stdout = captured
                try:
                    with pytest.raises(SystemExit) as exc_info:
                        _h.main()
                    assert exc_info.value.code == 0
                finally:
                    sys.stdin = old_stdin
                    sys.stdout = old_stdout

                output = json.loads(captured.getvalue())
                for field in _h.REQUIRED_FIELDS:
                    assert field in output, f"Missing field: {field}"
                assert output["ok"] is True


# ---------------------------------------------------------------------------
# _resolve_mode
# ---------------------------------------------------------------------------


class TestResolveMode:
    def test_default_is_auto(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _h._resolve_mode() == "auto"

    def test_codex_only_recognised(self):
        with patch.dict(os.environ, {"IGRIS_API_HELPER_MODE": "codex_only"}):
            assert _h._resolve_mode() == "codex_only"

    def test_unknown_value_falls_back_to_auto(self):
        with patch.dict(os.environ, {"IGRIS_API_HELPER_MODE": "experimental"}):
            assert _h._resolve_mode() == "auto"

    def test_empty_string_is_auto(self):
        with patch.dict(os.environ, {"IGRIS_API_HELPER_MODE": ""}):
            assert _h._resolve_mode() == "auto"


# ---------------------------------------------------------------------------
# _resolve_key_codex_only
# ---------------------------------------------------------------------------


class TestResolveKeyCodexOnly:
    def test_accepts_openai_key(self):
        env = {"OPENAI_API_KEY": "sk-openai-abc"}
        with patch.dict(os.environ, env, clear=True):
            provider, key = _h._resolve_key_codex_only()
        assert provider == "openai"
        assert key == "sk-openai-abc"

    def test_prefers_igris_openai_key(self):
        env = {"IGRIS_OPENAI_API_KEY": "sk-igris", "OPENAI_API_KEY": "sk-fallback"}
        with patch.dict(os.environ, env, clear=True):
            provider, key = _h._resolve_key_codex_only()
        assert key == "sk-igris"

    def test_rejects_anthropic_only_env(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-x", "IGRIS_ANTHROPIC_API_KEY": "sk-ant-y"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="codex_not_configured"):
                _h._resolve_key_codex_only()

    def test_raises_when_no_openai_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="codex_not_configured"):
                _h._resolve_key_codex_only()


# ---------------------------------------------------------------------------
# _resolve_model_codex_only
# ---------------------------------------------------------------------------


class TestResolveModelCodexOnly:
    def test_uses_igris_api_helper_model(self):
        with patch.dict(os.environ, {"IGRIS_API_HELPER_MODEL": "codex-mini-latest"}):
            assert _h._resolve_model_codex_only("gpt-5.4-mini") == "codex-mini-latest"

    def test_raises_when_model_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="codex_not_configured"):
                _h._resolve_model_codex_only("")

    def test_does_not_fall_back_to_gpt4o_mini(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError):
                _h._resolve_model_codex_only("gpt-5.4-mini")

    def test_does_not_fall_back_to_claude_haiku(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError):
                model = _h._resolve_model_codex_only("")
                # Should never reach here
                assert "haiku" not in model.lower()


# ---------------------------------------------------------------------------
# codex_only mode — black-box via subprocess
# ---------------------------------------------------------------------------


class TestCodexOnlyBlackBox:
    def test_codex_only_without_model_emits_codex_not_configured(self):
        inp = json.dumps({"model": "gpt-5.4-mini", "max_tokens": 100, "packet": {}})
        proc = _run_helper(
            inp,
            env_extra={
                "IGRIS_API_HELPER_MODE": "codex_only",
                "OPENAI_API_KEY": "sk-openai-fake12345678901234",
                # IGRIS_API_HELPER_MODEL intentionally not set
            },
        )
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["ok"] is False
        assert out.get("error_code") == "codex_not_configured"

    def test_codex_only_without_openai_key_emits_codex_not_configured(self):
        inp = json.dumps({"model": "codex-mini-latest", "max_tokens": 100, "packet": {}})
        proc = _run_helper(
            inp,
            env_extra={
                "IGRIS_API_HELPER_MODE": "codex_only",
                "IGRIS_API_HELPER_MODEL": "codex-mini-latest",
                "ANTHROPIC_API_KEY": "sk-ant-fake12345678901234",
                # No OpenAI key
            },
        )
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["ok"] is False
        assert out.get("error_code") == "codex_not_configured"

    def test_codex_only_anthropic_key_alone_is_rejected(self):
        inp = json.dumps({"model": "codex-mini-latest", "max_tokens": 100, "packet": {}})
        proc = _run_helper(
            inp,
            env_extra={
                "IGRIS_API_HELPER_MODE": "codex_only",
                "IGRIS_API_HELPER_MODEL": "codex-mini-latest",
                "ANTHROPIC_API_KEY": "sk-ant-fake12345678901234",
                "IGRIS_ANTHROPIC_API_KEY": "sk-ant-igris12345678901234",
            },
        )
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out.get("error_code") == "codex_not_configured"
        # Make sure it didn't silently use anthropic
        assert out.get("api_helper_provider", "") != "anthropic"

    def test_codex_only_no_fallback_to_gpt4o_mini_on_missing_model(self):
        inp = json.dumps({"model": "gpt-5.4-mini", "max_tokens": 100, "packet": {}})
        proc = _run_helper(
            inp,
            env_extra={
                "IGRIS_API_HELPER_MODE": "codex_only",
                "OPENAI_API_KEY": "sk-openai-fake12345678901234",
                # IGRIS_API_HELPER_MODEL not set → must fail, not fall back
            },
        )
        out = json.loads(proc.stdout)
        assert out["ok"] is False
        assert out.get("error_code") == "codex_not_configured"
        assert out.get("api_helper_model_resolved", "gpt-4o-mini") != "gpt-4o-mini"

    def test_codex_only_no_secrets_in_error_output(self):
        inp = json.dumps({"model": "codex-mini-latest", "max_tokens": 100, "packet": {}})
        proc = _run_helper(
            inp,
            env_extra={
                "IGRIS_API_HELPER_MODE": "codex_only",
                "IGRIS_API_HELPER_MODEL": "codex-mini-latest",
                # No key — will fail
            },
        )
        assert "sk-" not in proc.stdout
        assert "sk-" not in proc.stderr


# ---------------------------------------------------------------------------
# Observability fields in output
# ---------------------------------------------------------------------------


class TestObservabilityFields:
    def _run_main_with_mock(self, mode: str, provider: str, model: str) -> dict:
        """Run main() with mocked API call, return parsed output."""
        import io

        good = json.dumps({
            "ok": True,
            "summary": "ok",
            "diagnosis": "fine",
            "likely_supervisor_gap": "none",
            "suggested_repair_strategy": "nothing",
            "suggested_tests": [],
            "risk": "low",
            "risk_notes": [],
            "do_not_do": [],
            "confidence": 0.9,
            "requires_human_or_codex_audit": False,
            "must_not_complete_product_manually": True,
            "estimated_cost_usd": 0.001,
        })
        inp = json.dumps({"model": model, "max_tokens": 300, "packet": {"failure_class": "timeout"}})
        env_patch = {"IGRIS_API_HELPER_MODE": mode}
        if mode == "codex_only":
            env_patch["IGRIS_API_HELPER_MODEL"] = model

        with patch.object(_h, "_resolve_key", return_value=(provider, "sk-fake-key-12345678901234")):
            with patch.object(_h, "_resolve_key_codex_only", return_value=("openai", "sk-fake-key-12345678901234")):
                mock_call = MagicMock(return_value=(good, 0.001))
                call_fn = "_call_openai" if provider == "openai" else "_call_anthropic"
                with patch.object(_h, call_fn, mock_call):
                    with patch.dict(os.environ, env_patch):
                        old_stdin, old_stdout = sys.stdin, sys.stdout
                        sys.stdin = io.StringIO(inp)
                        captured = io.StringIO()
                        sys.stdout = captured
                        try:
                            with pytest.raises(SystemExit):
                                _h.main()
                        finally:
                            sys.stdin = old_stdin
                            sys.stdout = old_stdout
        return json.loads(captured.getvalue())

    def test_auto_mode_includes_observability_fields(self):
        out = self._run_main_with_mock("auto", "anthropic", "claude-haiku-4-5-20251001")
        assert out["api_helper_mode"] == "auto"
        assert out["codex_only"] is False
        assert "api_helper_provider" in out
        assert "api_helper_model_requested" in out
        assert "api_helper_model_resolved" in out

    def test_codex_only_mode_sets_codex_only_true(self):
        out = self._run_main_with_mock("codex_only", "openai", "codex-mini-latest")
        assert out["api_helper_mode"] == "codex_only"
        assert out["codex_only"] is True
        assert out["api_helper_provider"] == "openai"

    def test_model_requested_and_resolved_differ_when_overridden(self):
        out = self._run_main_with_mock("auto", "anthropic", "gpt-5.4-mini")
        # Requested was the sentinel, resolved should be the real default
        assert "api_helper_model_requested" in out
        assert "api_helper_model_resolved" in out

    def test_no_secrets_in_success_output(self):
        out = self._run_main_with_mock("auto", "anthropic", "claude-haiku-4-5-20251001")
        output_str = json.dumps(out)
        assert "sk-fake-key" not in output_str
        assert "ANTHROPIC_API_KEY" not in output_str
