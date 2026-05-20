"""Tests for model policy: DeepSeek V4 Flash/Pro as execution models,
Codex helper unchanged, A/B test flag, cost rates per 1M tokens.
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from igris.core.assignment_router import AssignmentRequest, AssignmentRouter
from igris.core.model_orchestrator import _build_default_providers, ModelOrchestrator


# ---------------------------------------------------------------------------
# 1. default execution (mini_execution) uses DeepSeek V4 Flash
# ---------------------------------------------------------------------------

def test_default_execution_uses_deepseek_v4_flash(tmp_path):
    """mini_execution profile primary model must be deepseek-v4-flash."""
    router = AssignmentRouter(outcomes_path=str(tmp_path / "outcomes.json"))
    req = AssignmentRequest(
        goal_text="Implementa GET /api/users con test",
        required_tests=["tests/test_users.py"],
        risk_level="medium",
        budget_remaining_usd=10.0,
    )
    decision = router.decide(req)
    # mini_execution candidates must prefer deepseek-v4-flash, not gpt-4o-mini
    if decision.preferred_profile == "mini_execution":
        assert decision.preferred_model == "deepseek-v4-flash", (
            f"mini_execution should use deepseek-v4-flash, got {decision.preferred_model}"
        )


def test_mini_execution_fallback_is_openai(tmp_path):
    """mini_execution fallback path must include gpt-4o-mini (OpenAI) not deepseek."""
    router = AssignmentRouter(outcomes_path=str(tmp_path / "outcomes.json"))
    req = AssignmentRequest(
        goal_text="Aggiungi test unitari per il modulo auth",
        risk_level="low",
        budget_remaining_usd=10.0,
    )
    decision = router.decide(req)
    if decision.preferred_profile == "mini_execution":
        assert "gpt-4o-mini" in decision.fallback_model_path or "gpt-4o" in decision.fallback_model_path


# ---------------------------------------------------------------------------
# 2. strong execution uses DeepSeek V4 Pro
# ---------------------------------------------------------------------------

def test_strong_execution_uses_deepseek_v4_pro(tmp_path):
    """strong_execution profile primary model must be deepseek-v4-pro."""
    router = AssignmentRouter(outcomes_path=str(tmp_path / "outcomes.json"))
    req = AssignmentRequest(
        goal_text="Implementa endpoint con logica reale",
        failure_class="semantic_incomplete",
        capability_signals={"stub_detected": 2},
        is_repair=True,
        prior_attempts=1,
        risk_level="medium",
        budget_remaining_usd=10.0,
    )
    decision = router.decide(req)
    assert decision.preferred_profile == "strong_execution"
    assert decision.preferred_model == "deepseek-v4-pro", (
        f"strong_execution should use deepseek-v4-pro, got {decision.preferred_model}"
    )
    assert "gpt-4o" in decision.fallback_model_path


# ---------------------------------------------------------------------------
# 3. Codex helper model unchanged
# ---------------------------------------------------------------------------

def test_codex_helper_model_env_unchanged():
    """IGRIS_API_HELPER_MODEL env var is still Codex (not overridden by DeepSeek)."""
    # The .env sets IGRIS_API_HELPER_MODEL=gpt-5.3-codex.
    # DeepSeek should only be configured as IGRIS_API_HELPER_ALT_MODEL, never as primary.
    alt_model = os.environ.get("IGRIS_API_HELPER_ALT_MODEL", "deepseek-v4-pro")
    primary_model = os.environ.get("IGRIS_API_HELPER_MODEL", "")
    # Alt model should not equal the primary helper model
    if primary_model:
        assert alt_model != primary_model, (
            "Alt helper model must differ from primary Codex helper model"
        )


def test_codex_helper_stays_codex():
    """A/B test flag must be false by default — Codex remains the only advice helper."""
    ab_flag = os.environ.get("IGRIS_ENABLE_HELPER_AB_TEST", "false").lower()
    assert ab_flag == "false", (
        "IGRIS_ENABLE_HELPER_AB_TEST must default to false — "
        "no DeepSeek as helper without explicit A/B flag"
    )


# ---------------------------------------------------------------------------
# 4. A/B test helper: alt model not called when flag is false
# ---------------------------------------------------------------------------

def test_helper_ab_not_triggered_when_disabled():
    """When IGRIS_ENABLE_HELPER_AB_TEST=false, call_api_helper always uses primary model."""
    from igris.core.self_repair_supervisor import LocalSupervisorBackend
    from pathlib import Path

    backend = LocalSupervisorBackend(project_root=Path("/tmp"))

    called_models = []

    def fake_run(cmd, timeout=30, input_text=None, extra_env=None, **kw):
        from igris.core.self_repair_supervisor import CommandResult
        import json
        payload = json.loads(input_text or "{}")
        called_models.append(payload.get("model", ""))
        return CommandResult(success=False, output="", error="not configured", returncode=2)

    backend._run = fake_run

    with patch.dict(os.environ, {
        "IGRIS_API_HELPER_COMMAND": "echo",
        "IGRIS_ENABLE_HELPER_AB_TEST": "false",
        "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro",
    }):
        result = backend.call_api_helper(
            packet={"goal": "test"},
            model="gpt-5.3-codex",
            max_tokens=600,
        )

    assert not result.helper_ab_active
    assert result.helper_ab_alt_model == ""
    if called_models:
        assert called_models[0] == "gpt-5.3-codex"


def test_helper_ab_uses_alt_model_when_enabled():
    """When IGRIS_ENABLE_HELPER_AB_TEST=true and split=1.0, alt model is always used."""
    from igris.core.self_repair_supervisor import LocalSupervisorBackend
    from pathlib import Path

    backend = LocalSupervisorBackend(project_root=Path("/tmp"))

    called_models = []

    def fake_run(cmd, timeout=30, input_text=None, extra_env=None, **kw):
        from igris.core.self_repair_supervisor import CommandResult
        import json
        payload = json.loads(input_text or "{}")
        called_models.append(payload.get("model", ""))
        return CommandResult(success=False, output="", error="not configured", returncode=2)

    backend._run = fake_run

    with patch.dict(os.environ, {
        "IGRIS_API_HELPER_COMMAND": "echo",
        "IGRIS_ENABLE_HELPER_AB_TEST": "true",
        "IGRIS_API_HELPER_ALT_MODEL": "deepseek-v4-pro",
        "IGRIS_HELPER_AB_SPLIT": "1.0",  # always route to alt
    }):
        result = backend.call_api_helper(
            packet={"goal": "test"},
            model="gpt-5.3-codex",
            max_tokens=600,
        )

    assert result.helper_ab_active
    assert result.helper_ab_alt_model == "deepseek-v4-pro"
    assert result.helper_model == "deepseek-v4-pro"
    if called_models:
        assert called_models[0] == "deepseek-v4-pro"


# ---------------------------------------------------------------------------
# 5. Cost calculation per 1M tokens (not per 1K)
# ---------------------------------------------------------------------------

def test_cost_rates_are_per_1m_tokens():
    """Provider cost rates must be in $/1M tokens, not $/1K."""
    providers = _build_default_providers()

    # DeepSeek V4 Flash: $0.14/$0.28 per 1M
    ds = providers["deepseek"]
    assert 0.10 <= ds.input_cost_per_1m_tokens <= 0.20, (
        f"deepseek input cost should be ~$0.14/1M, got {ds.input_cost_per_1m_tokens}"
    )
    assert 0.20 <= ds.output_cost_per_1m_tokens <= 0.40, (
        f"deepseek output cost should be ~$0.28/1M, got {ds.output_cost_per_1m_tokens}"
    )

    # DeepSeek V4 Pro: $0.435/$0.87 per 1M (discounted)
    dsp = providers["deepseek_strong"]
    assert 0.30 <= dsp.input_cost_per_1m_tokens <= 2.00, (
        f"deepseek_strong input cost should be ~$0.435/1M, got {dsp.input_cost_per_1m_tokens}"
    )
    assert 0.60 <= dsp.output_cost_per_1m_tokens <= 2.00, (
        f"deepseek_strong output cost should be ~$0.87/1M, got {dsp.output_cost_per_1m_tokens}"
    )

    # OpenAI gpt-4o-mini: $0.15/$0.60 per 1M (not $0.00015/$0.0006 which would be per 1K)
    openai = providers["openai"]
    assert openai.input_cost_per_1m_tokens >= 0.10, (
        f"openai input cost suspiciously low — may be per 1K not 1M: {openai.input_cost_per_1m_tokens}"
    )
    assert openai.output_cost_per_1m_tokens >= 0.20, (
        f"openai output cost suspiciously low — may be per 1K not 1M: {openai.output_cost_per_1m_tokens}"
    )

    # gpt-4o strong: $2.50/$10.00 per 1M
    openai_strong = providers["openai_strong"]
    assert openai_strong.input_cost_per_1m_tokens >= 1.0, (
        f"openai_strong input cost suspiciously low: {openai_strong.input_cost_per_1m_tokens}"
    )
    assert openai_strong.output_cost_per_1m_tokens >= 5.0, (
        f"openai_strong output cost suspiciously low: {openai_strong.output_cost_per_1m_tokens}"
    )


def test_deepseek_context_window_is_1m():
    """DeepSeek V4 Flash and Pro must have 1M token context window."""
    providers = _build_default_providers()
    assert providers["deepseek"].max_context >= 900_000, (
        "deepseek (V4 Flash) should have 1M context"
    )
    assert providers["deepseek_strong"].max_context >= 900_000, (
        "deepseek_strong (V4 Pro) should have 1M context"
    )
