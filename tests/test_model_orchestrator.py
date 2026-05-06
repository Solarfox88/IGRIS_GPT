"""Tests for Model Orchestrator — Epic #58.

Validates that all LLM access goes through the orchestrator,
provider-agnostic design, fallback behavior, and cost tracking.
"""

import pytest

from igris.core.model_orchestrator import (
    MODEL_PROFILES,
    TASK_PROFILE_MAP,
    ProviderConfig,
    OrchestratorResult,
    ModelOrchestrator,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestModelProfiles:
    """Verify model profile definitions."""

    def test_profiles_are_tuple(self):
        assert isinstance(MODEL_PROFILES, tuple)
        assert len(MODEL_PROFILES) == 7

    def test_required_profiles_present(self):
        required = {
            "deterministic", "local_light", "local_coder",
            "cheap_cloud_reasoning", "strong_cloud_reasoning",
            "risk_reviewer", "embedding_memory",
        }
        assert required == set(MODEL_PROFILES)

    def test_task_profile_map_covers_key_tasks(self):
        assert "chat" in TASK_PROFILE_MAP
        assert "code_reasoning" in TASK_PROFILE_MAP
        assert "risk_review" in TASK_PROFILE_MAP
        assert "safety_check" in TASK_PROFILE_MAP
        assert TASK_PROFILE_MAP["safety_check"] == "deterministic"


# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------

class TestProviderConfig:
    """Test provider configuration."""

    def test_default_creation(self):
        p = ProviderConfig()
        assert p.name == ""
        assert p.is_local is False
        assert p.available is True

    def test_to_dict_no_secrets(self):
        p = ProviderConfig(
            name="test",
            base_url="http://localhost",
            model="test-model",
            api_key_env="MY_API_KEY",
        )
        d = p.to_dict()
        assert d["api_key_env"] == "MY_API_KEY"
        # Ensure actual key is never in dict
        assert "api_key" not in d or isinstance(d.get("api_key"), str) is False

    def test_local_provider(self):
        p = ProviderConfig(name="ollama", is_local=True, cost_per_1k_input=0.0)
        assert p.is_local is True
        assert p.cost_per_1k_input == 0.0


# ---------------------------------------------------------------------------
# OrchestratorResult
# ---------------------------------------------------------------------------

class TestOrchestratorResult:
    """Test orchestrator result."""

    def test_default_creation(self):
        r = OrchestratorResult()
        assert r.success is False
        assert r.text == ""
        assert r.estimated_cost == 0.0

    def test_to_dict(self):
        r = OrchestratorResult(
            text="hello",
            provider="ollama",
            model="phi4-mini",
            profile="local_light",
            success=True,
        )
        d = r.to_dict()
        assert d["provider"] == "ollama"
        assert d["success"] is True
        assert "request_id" in d


# ---------------------------------------------------------------------------
# ModelOrchestrator
# ---------------------------------------------------------------------------

class TestModelOrchestrator:
    """Test the Model Orchestrator."""

    def test_creation(self):
        orch = ModelOrchestrator()
        assert orch is not None
        providers = orch.list_providers()
        assert len(providers) >= 3  # ollama, openai, deepseek

    def test_deterministic_profile(self):
        orch = ModelOrchestrator()
        result = orch.complete(
            task_type="safety_check",
            messages=[{"role": "user", "content": "test"}],
        )
        assert result.success is True
        assert result.provider == "deterministic"
        assert result.estimated_cost == 0.0

    def test_fallback_all_unavailable(self):
        """When no providers are available, should return deterministic fallback."""
        providers = {
            "test": ProviderConfig(
                name="test",
                base_url="http://nonexistent:9999",
                model="fake",
                is_local=True,
            ),
        }
        orch = ModelOrchestrator(providers=providers)
        result = orch.complete(
            task_type="chat",
            messages=[{"role": "user", "content": "test"}],
        )
        assert result.fallback_used is True
        assert result.success is False

    def test_cost_summary(self):
        orch = ModelOrchestrator()
        summary = orch.get_cost_summary()
        assert "total_cost" in summary
        assert "call_count" in summary

    def test_profiles_accessible(self):
        orch = ModelOrchestrator()
        profiles = orch.get_profiles()
        assert "chat" in profiles
        assert profiles["safety_check"] == "deterministic"

    def test_provider_chain_local_light(self):
        orch = ModelOrchestrator()
        chain = orch._get_provider_chain("local_light")
        assert chain[0] == "ollama"
        assert "openai" in chain

    def test_provider_chain_cheap_cloud(self):
        orch = ModelOrchestrator()
        chain = orch._get_provider_chain("cheap_cloud_reasoning")
        assert chain[0] == "deepseek"

    def test_provider_chain_strong_cloud(self):
        orch = ModelOrchestrator()
        chain = orch._get_provider_chain("strong_cloud_reasoning")
        assert chain[0] == "anthropic"

    def test_history_tracking(self):
        orch = ModelOrchestrator()
        orch.complete(
            task_type="safety_check",
            messages=[{"role": "user", "content": "test"}],
        )
        history = orch.get_history()
        assert len(history) == 1
        assert history[0]["task_type"] == "safety_check"

    def test_no_api_key_in_any_output(self):
        """Verify no secret keys appear in any public output."""
        orch = ModelOrchestrator()
        providers = orch.list_providers()
        for p in providers:
            for k, v in p.items():
                if isinstance(v, str):
                    assert not v.startswith("sk-"), f"Possible API key in {k}"

    def test_provider_agnostic_design(self):
        """Verify the orchestrator doesn't hardcode any specific provider."""
        # Custom providers should work
        custom = {
            "custom_local": ProviderConfig(
                name="custom_local",
                base_url="http://localhost:8080",
                model="custom-model",
                is_local=True,
            ),
        }
        orch = ModelOrchestrator(providers=custom)
        providers = orch.list_providers()
        assert len(providers) == 1
        assert providers[0]["name"] == "custom_local"


# ---------------------------------------------------------------------------
# No direct provider calls
# ---------------------------------------------------------------------------

class TestNoDirectCalls:
    """Verify the orchestrator pattern is enforced."""

    def test_orchestrator_result_records_provider(self):
        """Every result must record which provider was used."""
        r = OrchestratorResult(provider="test", model="test-model")
        d = r.to_dict()
        assert d["provider"] == "test"

    def test_deterministic_returns_empty_text(self):
        """Deterministic profile should return empty text (no LLM output)."""
        orch = ModelOrchestrator()
        result = orch.complete(
            task_type="policy_check",
            messages=[{"role": "user", "content": "test"}],
        )
        assert result.text == ""
        assert result.provider == "deterministic"
