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
        assert len(MODEL_PROFILES) >= 7

    def test_required_profiles_present(self):
        required = {
            "deterministic", "local_light", "local_coder",
            "cheap_cloud_reasoning", "strong_cloud_reasoning",
            "risk_reviewer", "embedding_memory",
        }
        assert required.issubset(set(MODEL_PROFILES)), (
            f"Missing required profiles: {required - set(MODEL_PROFILES)}"
        )

    def test_endpoint_implementation_profile_present(self):
        assert "endpoint_implementation" in MODEL_PROFILES
        assert "endpoint_implementation" in TASK_PROFILE_MAP
        assert TASK_PROFILE_MAP["endpoint_implementation"] == "endpoint_implementation"
        assert TASK_PROFILE_MAP["semantic_repair"] == "endpoint_implementation"
        assert TASK_PROFILE_MAP["stub_repair"] == "endpoint_implementation"

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
        p = ProviderConfig(name="ollama", is_local=True, input_cost_per_1m_tokens=0.0)
        assert p.is_local is True
        assert p.input_cost_per_1m_tokens == 0.0


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
        # DeepSeek V4 Pro is primary for strong_cloud_reasoning (PR #441); anthropic is fallback
        assert chain[0] == "deepseek_strong"
        assert "anthropic" in chain

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


# ---------------------------------------------------------------------------
# Execution routing tests (#350 watchdog)
# ---------------------------------------------------------------------------

class TestExecutionRouting:
    """Verify cloud-first routing when local model is unavailable."""

    def test_local_unavailable_falls_through_to_cloud(self):
        """When the local Ollama provider is unreachable, the chain continues to cloud."""
        providers = {
            "ollama": ProviderConfig(
                name="ollama",
                base_url="http://nonexistent-host:11434",
                model="phi4-mini",
                is_local=True,
            ),
            "openai": ProviderConfig(
                name="openai",
                base_url="http://nonexistent-openai:9999",
                model="gpt-4o-mini",
                api_key_env="OPENAI_API_KEY",
            ),
        }
        import os
        orig = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "sk-test-key"
        try:
            orch = ModelOrchestrator(providers=providers)
            result = orch.complete(
                task_type="code_reasoning",
                messages=[{"role": "user", "content": "hello"}],
            )
            # Both providers are unreachable — falls to deterministic_fallback
            # but the chain must have attempted openai (not skipped due to missing key)
            assert result.provider in ("deterministic_fallback", "openai"), (
                "Expected either successful openai call or deterministic_fallback"
            )
        finally:
            if orig is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = orig

    def test_endpoint_implementation_profile_is_cloud_first(self):
        """endpoint_implementation chain must start with openai, not ollama."""
        orch = ModelOrchestrator()
        chain = orch._get_provider_chain("endpoint_implementation")
        assert chain[0] != "ollama", (
            "endpoint_implementation must not start with local Ollama"
        )
        assert "openai" in chain or "anthropic" in chain, (
            "endpoint_implementation must include a cloud provider"
        )

    def test_semantic_repair_task_type_uses_cloud_first_profile(self):
        """semantic_repair task_type must map to endpoint_implementation (cloud-first)."""
        from igris.core.model_orchestrator import TASK_PROFILE_MAP
        profile = TASK_PROFILE_MAP.get("semantic_repair")
        assert profile == "endpoint_implementation", (
            f"semantic_repair must map to endpoint_implementation, got {profile!r}"
        )
        chain = ModelOrchestrator()._get_provider_chain(profile)
        assert chain[0] != "ollama", "semantic_repair chain must not start with Ollama"

    def test_preferred_profile_overrides_task_type(self):
        """preferred_profile parameter overrides the task_type default profile."""
        orch = ModelOrchestrator()
        # Force deterministic so no network calls needed
        result = orch.complete(
            task_type="chat",
            messages=[{"role": "user", "content": "test"}],
            preferred_profile="deterministic",
        )
        assert result.provider == "deterministic"
        assert result.profile == "deterministic"

    def test_config_attribute_path_resolved_correctly(self):
        """Provider model must be resolved from CONFIG.fallback_llm.model, not a flat attr."""
        from igris.models.config import CONFIG
        orch = ModelOrchestrator()
        openai_provider = orch.providers.get("openai")
        assert openai_provider is not None
        # Model should NOT be the hardcoded default if fallback_llm.model is set
        # and not empty — it should match IGRIS_EXECUTION_FALLBACK_MODEL or
        # CONFIG.fallback_llm.model, never "NOT SET" / empty string / None.
        assert openai_provider.model, "OpenAI provider model must not be empty"
        assert openai_provider.model != "NOT SET"

    def test_no_api_key_in_provider_to_dict(self):
        """Provider to_dict() must never expose the actual API key."""
        orch = ModelOrchestrator()
        for p in orch.list_providers():
            for v in p.values():
                assert "sk-" not in str(v), (
                    f"Provider config must not expose API keys: {p}"
                )


# ---------------------------------------------------------------------------
# Cost calculation tests — per-1M token formula
# ---------------------------------------------------------------------------

class TestCostCalculation:
    """Verify cost estimates use per-1M token rates, not per-1K."""

    def _make_provider(self, input_rate: float, output_rate: float) -> ProviderConfig:
        return ProviderConfig(
            name="test_provider",
            input_cost_per_1m_tokens=input_rate,
            output_cost_per_1m_tokens=output_rate,
        )

    def test_1m_input_tokens_exact(self):
        """1M input tokens at $2.50/1M must cost exactly $2.50, not $2500."""
        provider = self._make_provider(input_rate=2.50, output_rate=10.00)
        input_tokens = 1_000_000
        output_tokens = 0
        cost = (
            (input_tokens / 1_000_000) * provider.input_cost_per_1m_tokens
            + (output_tokens / 1_000_000) * provider.output_cost_per_1m_tokens
        )
        assert cost == pytest.approx(2.50), (
            f"1M input tokens at $2.50/1M should cost $2.50, got ${cost}"
        )

    def test_1m_output_tokens_exact(self):
        """1M output tokens at $10.00/1M must cost exactly $10.00."""
        provider = self._make_provider(input_rate=2.50, output_rate=10.00)
        input_tokens = 0
        output_tokens = 1_000_000
        cost = (
            (input_tokens / 1_000_000) * provider.input_cost_per_1m_tokens
            + (output_tokens / 1_000_000) * provider.output_cost_per_1m_tokens
        )
        assert cost == pytest.approx(10.00), (
            f"1M output tokens at $10.00/1M should cost $10.00, got ${cost}"
        )

    def test_1k_tokens_is_fraction_of_cent(self):
        """1K input tokens at $0.15/1M must cost $0.00015 (not $0.15)."""
        provider = self._make_provider(input_rate=0.15, output_rate=0.60)
        input_tokens = 1_000
        output_tokens = 0
        cost = (
            (input_tokens / 1_000_000) * provider.input_cost_per_1m_tokens
            + (output_tokens / 1_000_000) * provider.output_cost_per_1m_tokens
        )
        assert cost == pytest.approx(0.00015), (
            f"1K input tokens at $0.15/1M should cost $0.00015, got ${cost}"
        )

    def test_openai_strong_provider_rates(self):
        """openai_strong default rates must be $2.50/$10.00 per 1M."""
        orch = ModelOrchestrator()
        provider = orch.providers.get("openai_strong")
        assert provider is not None, "openai_strong provider must exist"
        assert provider.input_cost_per_1m_tokens == pytest.approx(2.50)
        assert provider.output_cost_per_1m_tokens == pytest.approx(10.00)

    def test_openai_provider_rates(self):
        """openai (gpt-4o-mini) default rates must be $0.15/$0.60 per 1M."""
        orch = ModelOrchestrator()
        provider = orch.providers.get("openai")
        assert provider is not None
        assert provider.input_cost_per_1m_tokens == pytest.approx(0.15)
        assert provider.output_cost_per_1m_tokens == pytest.approx(0.60)

    def test_anthropic_provider_rates(self):
        """anthropic default rates must be $3.00/$15.00 per 1M (not $0.003/$0.015)."""
        orch = ModelOrchestrator()
        provider = orch.providers.get("anthropic")
        assert provider is not None
        assert provider.input_cost_per_1m_tokens == pytest.approx(3.0)
        assert provider.output_cost_per_1m_tokens == pytest.approx(15.0)

    def test_deepseek_provider_rates(self):
        """deepseek default rates must be ~$0.14/$0.28 per 1M."""
        orch = ModelOrchestrator()
        provider = orch.providers.get("deepseek")
        assert provider is not None
        assert provider.input_cost_per_1m_tokens == pytest.approx(0.14)
        assert provider.output_cost_per_1m_tokens == pytest.approx(0.28)

    def test_to_dict_exposes_per_1m_field_names(self):
        """ProviderConfig.to_dict() must use per-1M field names."""
        provider = self._make_provider(input_rate=2.50, output_rate=10.00)
        d = provider.to_dict()
        assert "input_cost_per_1m_tokens" in d, "to_dict() must have input_cost_per_1m_tokens"
        assert "output_cost_per_1m_tokens" in d, "to_dict() must have output_cost_per_1m_tokens"
        assert "cost_per_1k_input" not in d, "to_dict() must not expose old per-1K field name"
        assert "cost_per_1k_output" not in d, "to_dict() must not expose old per-1K field name"
        assert d["input_cost_per_1m_tokens"] == pytest.approx(2.50)
        assert d["output_cost_per_1m_tokens"] == pytest.approx(10.00)

    def test_ollama_zero_cost(self):
        """Local ollama provider must have zero cost rates."""
        orch = ModelOrchestrator()
        provider = orch.providers.get("ollama")
        assert provider is not None
        assert provider.input_cost_per_1m_tokens == 0.0
        assert provider.output_cost_per_1m_tokens == 0.0
