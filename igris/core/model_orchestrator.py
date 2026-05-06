"""Model Orchestrator for IGRIS_GPT — Epic #58.

All LLM usage must go through this orchestrator. No component should
call OpenAI, DeepSeek, Anthropic, Ollama or any provider directly.

The orchestrator:
- Selects model/provider based on task type, role, risk, budget, context size
- Uses local models when sufficient
- Uses cheap cloud providers when convenient
- Uses strong models for hard debugging, architecture, security review
- Degrades honestly when no suitable model is available
- Records cost, latency, provider, fallback, outcome
- Supports any OpenAI-compatible provider

Profiles:
    deterministic          — no LLM, safety/policy/routing
    local_light            — chat, synthesis, simple classification (Ollama)
    local_coder            — code reasoning if hardware allows
    cheap_cloud_reasoning  — coding/reasoning economical (DeepSeek API etc.)
    strong_cloud_reasoning — hard debugging, architecture, critical review
    risk_reviewer          — risk analysis for medium/high/unknown commands
    embedding_memory       — semantic retrieval (future)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from igris.core.safety import redact_secrets
from igris.models.config import CONFIG


# ---------------------------------------------------------------------------
# Model profiles
# ---------------------------------------------------------------------------

MODEL_PROFILES = (
    "deterministic",
    "local_light",
    "local_coder",
    "cheap_cloud_reasoning",
    "strong_cloud_reasoning",
    "risk_reviewer",
    "embedding_memory",
)

# Task type → recommended profile mapping
TASK_PROFILE_MAP: Dict[str, str] = {
    "chat": "local_light",
    "classification": "local_light",
    "synthesis": "local_light",
    "code_reasoning": "cheap_cloud_reasoning",
    "code_generation": "cheap_cloud_reasoning",
    "patch_generation": "cheap_cloud_reasoning",
    "plan_generation": "cheap_cloud_reasoning",
    "risk_review": "risk_reviewer",
    "architecture_review": "strong_cloud_reasoning",
    "security_review": "strong_cloud_reasoning",
    "hard_debugging": "strong_cloud_reasoning",
    "embedding": "embedding_memory",
    "safety_check": "deterministic",
    "policy_check": "deterministic",
    "routing": "deterministic",
}


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""
    name: str = ""
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""  # env var name, never the actual key
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_context: int = 4096
    supports_json_mode: bool = False
    is_local: bool = False
    available: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "max_context": self.max_context,
            "supports_json_mode": self.supports_json_mode,
            "is_local": self.is_local,
            "available": self.available,
        }


# Default provider configurations
def _build_default_providers() -> Dict[str, ProviderConfig]:
    """Build default provider configs from environment."""
    providers: Dict[str, ProviderConfig] = {}

    # Ollama (local)
    ollama_url = getattr(CONFIG, "local_llm_base_url", "http://127.0.0.1:11434")
    ollama_model = getattr(CONFIG, "local_llm_model", "phi4-mini")
    providers["ollama"] = ProviderConfig(
        name="ollama",
        base_url=str(ollama_url),
        model=str(ollama_model),
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context=4096,
        is_local=True,
    )

    # OpenAI (fallback cloud)
    providers["openai"] = ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        model=str(getattr(CONFIG, "fallback_llm_model", "gpt-4o-mini")),
        api_key_env="OPENAI_API_KEY",
        cost_per_1k_input=0.15,
        cost_per_1k_output=0.60,
        max_context=128000,
        supports_json_mode=True,
    )

    # DeepSeek (cheap cloud reasoning)
    providers["deepseek"] = ProviderConfig(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        cost_per_1k_input=0.014,
        cost_per_1k_output=0.028,
        max_context=64000,
        supports_json_mode=True,
    )

    # Anthropic (strong cloud)
    providers["anthropic"] = ProviderConfig(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-sonnet-4-20250514",
        api_key_env="ANTHROPIC_API_KEY",
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        max_context=200000,
        supports_json_mode=True,
    )

    return providers


# ---------------------------------------------------------------------------
# Orchestrator result
# ---------------------------------------------------------------------------

@dataclass
class OrchestratorResult:
    """Result from Model Orchestrator."""
    text: str = ""
    provider: str = ""
    model: str = ""
    profile: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    success: bool = False
    error: str = ""
    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4().hex[:8]}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": redact_secrets(self.text) if self.text else "",
            "provider": self.provider,
            "model": self.model,
            "profile": self.profile,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "success": self.success,
            "error": self.error,
            "request_id": self.request_id,
        }


# ---------------------------------------------------------------------------
# Model Orchestrator
# ---------------------------------------------------------------------------

class ModelOrchestrator:
    """Central orchestrator for all LLM interactions.

    Usage:
        orchestrator = ModelOrchestrator()
        result = orchestrator.complete(
            task_type="code_reasoning",
            messages=[{"role": "user", "content": "..."}],
            system_prompt="...",
        )
    """

    def __init__(self, providers: Optional[Dict[str, ProviderConfig]] = None):
        self.providers = providers or _build_default_providers()
        self._history: List[Dict[str, Any]] = []
        self._total_cost: float = 0.0
        self._call_count: int = 0

    def complete(
        self,
        task_type: str,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        preferred_profile: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        json_mode: bool = False,
        timeout: float = 30.0,
    ) -> OrchestratorResult:
        """Send a completion request through the orchestrator.

        Selects the best provider based on task_type, availability, and budget.
        Falls back through provider chain on failure.
        """
        profile = preferred_profile or TASK_PROFILE_MAP.get(task_type, "local_light")

        # Deterministic profile — no LLM needed
        if profile == "deterministic":
            result = OrchestratorResult(
                text="",
                provider="deterministic",
                model="none",
                profile="deterministic",
                success=True,
            )
            self._record_call(result, task_type)
            return result

        # Build provider priority chain
        chain = self._get_provider_chain(profile)

        t0 = time.monotonic()
        last_error = ""
        fallback_used = False

        for i, provider_name in enumerate(chain):
            provider = self.providers.get(provider_name)
            if not provider or not provider.available:
                continue

            if not self._check_provider_available(provider):
                continue

            try:
                result = self._call_provider(
                    provider, messages, system_prompt,
                    max_tokens, temperature, json_mode, timeout,
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                result.profile = profile
                result.latency_ms = elapsed
                result.fallback_used = i > 0
                if i > 0:
                    result.fallback_reason = last_error or "primary unavailable"

                self._record_call(result, task_type)
                return result

            except Exception as e:
                last_error = str(e)
                fallback_used = True
                continue

        # All providers failed — deterministic fallback
        elapsed = int((time.monotonic() - t0) * 1000)
        result = OrchestratorResult(
            text="",
            provider="deterministic_fallback",
            model="none",
            profile=profile,
            fallback_used=True,
            fallback_reason=last_error or "no provider available",
            latency_ms=elapsed,
            success=False,
            error="All providers unavailable",
        )
        self._record_call(result, task_type)
        return result

    def _get_provider_chain(self, profile: str) -> List[str]:
        """Get ordered provider chain for a profile."""
        chains: Dict[str, List[str]] = {
            "local_light": ["ollama", "deepseek", "openai"],
            "local_coder": ["ollama", "deepseek", "openai"],
            "cheap_cloud_reasoning": ["deepseek", "openai", "ollama"],
            "strong_cloud_reasoning": ["anthropic", "openai", "deepseek"],
            "risk_reviewer": ["deepseek", "openai", "ollama"],
            "embedding_memory": ["ollama", "openai"],
        }
        return chains.get(profile, ["ollama", "openai"])

    def _check_provider_available(self, provider: ProviderConfig) -> bool:
        """Check if a provider is configured and reachable."""
        import os

        if provider.is_local:
            return True  # Will fail at call time if not running

        if provider.api_key_env:
            key = os.environ.get(provider.api_key_env, "")
            if not key:
                return False

        return True

    def _call_provider(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout: float,
    ) -> OrchestratorResult:
        """Call a specific provider."""
        if provider.is_local and provider.name == "ollama":
            return self._call_ollama(provider, messages, system_prompt, timeout)
        else:
            return self._call_openai_compatible(
                provider, messages, system_prompt,
                max_tokens, temperature, json_mode, timeout,
            )

    def _call_ollama(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        timeout: float,
    ) -> OrchestratorResult:
        """Call Ollama API."""
        import urllib.request
        import urllib.error

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        url = f"{provider.base_url.rstrip('/')}/api/chat"
        payload = json.dumps({
            "model": provider.model,
            "messages": full_messages,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data.get("message", {}).get("content", "")
                return OrchestratorResult(
                    text=content,
                    provider="ollama",
                    model=provider.model,
                    success=bool(content),
                )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                ValueError, TimeoutError, ConnectionError) as e:
            raise RuntimeError(f"Ollama call failed: {e}") from e

    def _call_openai_compatible(
        self,
        provider: ProviderConfig,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout: float,
    ) -> OrchestratorResult:
        """Call an OpenAI-compatible API (OpenAI, DeepSeek, etc.)."""
        import os
        import urllib.request
        import urllib.error

        api_key = os.environ.get(provider.api_key_env, "")
        if not api_key:
            raise RuntimeError(f"No API key for {provider.name}")

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        body: Dict[str, Any] = {
            "model": provider.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode and provider.supports_json_mode:
            body["response_format"] = {"type": "json_object"}

        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                content = choices[0]["message"]["content"] if choices else ""
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                cost = (
                    (input_tokens / 1000) * provider.cost_per_1k_input +
                    (output_tokens / 1000) * provider.cost_per_1k_output
                )
                return OrchestratorResult(
                    text=content,
                    provider=provider.name,
                    model=provider.model,
                    success=bool(content),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost=round(cost, 6),
                )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                ValueError, TimeoutError, ConnectionError) as e:
            raise RuntimeError(f"{provider.name} call failed: {e}") from e

    def _record_call(self, result: OrchestratorResult, task_type: str) -> None:
        """Record a call in history for cost tracking."""
        self._call_count += 1
        self._total_cost += result.estimated_cost
        self._history.append({
            "request_id": result.request_id,
            "task_type": task_type,
            "provider": result.provider,
            "model": result.model,
            "profile": result.profile,
            "success": result.success,
            "latency_ms": result.latency_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "estimated_cost": result.estimated_cost,
            "fallback_used": result.fallback_used,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    # -- Public accessors --

    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cost tracking summary."""
        return {
            "total_cost": round(self._total_cost, 6),
            "call_count": self._call_count,
            "history_count": len(self._history),
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent call history."""
        return list(reversed(self._history[-limit:]))

    def list_providers(self) -> List[Dict[str, Any]]:
        """List all configured providers (no secrets)."""
        return [p.to_dict() for p in self.providers.values()]

    def get_profiles(self) -> Dict[str, str]:
        """Get task type → profile mapping."""
        return dict(TASK_PROFILE_MAP)
