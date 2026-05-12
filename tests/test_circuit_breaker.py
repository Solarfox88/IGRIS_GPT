"""Tests for circuit breaker and retry in Model Orchestrator (#330 Fase 1)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from igris.core.model_orchestrator import (
    CircuitBreakerRegistry,
    CircuitBreakerState,
    ModelOrchestrator,
    OrchestratorResult,
    ProviderConfig,
    _CB_CLOSED,
    _CB_HALF_OPEN,
    _CB_OPEN,
    _CB_FAILURE_THRESHOLD,
    _CB_RECOVERY_TIMEOUT,
    _CB_SUCCESS_THRESHOLD,
    _RETRY_BASE_DELAY,
    _RETRY_MAX_ATTEMPTS,
)


# ---------------------------------------------------------------------------
# CircuitBreakerState unit tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerState:
    def test_initial_state_closed(self):
        cb = CircuitBreakerState()
        assert cb.state == _CB_CLOSED
        assert cb.failure_count == 0
        assert cb.is_available()

    def test_stays_closed_on_success(self):
        cb = CircuitBreakerState()
        cb.record_success()
        assert cb.state == _CB_CLOSED
        assert cb.failure_count == 0

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreakerState(failure_threshold=3)
        cb.record_failure("err1")
        cb.record_failure("err2")
        assert cb.state == _CB_CLOSED
        assert cb.failure_count == 2
        assert cb.is_available()

    def test_opens_at_threshold(self):
        cb = CircuitBreakerState(failure_threshold=3)
        cb.record_failure("err1")
        cb.record_failure("err2")
        cb.record_failure("err3")
        assert cb.state == _CB_OPEN
        assert cb.failure_count == 3
        assert not cb.is_available()

    def test_success_resets_failure_count(self):
        cb = CircuitBreakerState(failure_threshold=3)
        cb.record_failure("err1")
        cb.record_failure("err2")
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == _CB_CLOSED

    def test_recovery_after_timeout(self):
        cb = CircuitBreakerState(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure("err")
        assert cb.state == _CB_OPEN
        assert not cb.is_available()
        time.sleep(0.15)
        assert cb.is_available()
        assert cb.state == _CB_HALF_OPEN

    def test_half_open_success_closes(self):
        cb = CircuitBreakerState(failure_threshold=1, recovery_timeout=0.01,
                                 success_threshold=1)
        cb.record_failure("err")
        time.sleep(0.02)
        assert cb.is_available()  # transitions to half_open
        cb.record_success()
        assert cb.state == _CB_CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_reopens(self):
        cb = CircuitBreakerState(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure("err1")
        time.sleep(0.02)
        cb.is_available()  # transitions to half_open
        cb.record_failure("err2")
        assert cb.state == _CB_OPEN

    def test_last_error_tracked(self):
        cb = CircuitBreakerState()
        cb.record_failure("connection refused")
        assert cb.last_error == "connection refused"

    def test_to_dict(self):
        cb = CircuitBreakerState()
        d = cb.to_dict()
        assert d["state"] == _CB_CLOSED
        assert d["failure_count"] == 0
        assert d["available"] is True


# ---------------------------------------------------------------------------
# CircuitBreakerRegistry unit tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerRegistry:
    def test_get_creates_default(self):
        reg = CircuitBreakerRegistry()
        cb = reg.get("ollama")
        assert cb.state == _CB_CLOSED

    def test_is_available_new_provider(self):
        reg = CircuitBreakerRegistry()
        assert reg.is_available("ollama")

    def test_record_failure_and_trip(self):
        reg = CircuitBreakerRegistry(failure_threshold=2)
        reg.record_failure("ollama", "timeout")
        assert reg.is_available("ollama")
        reg.record_failure("ollama", "timeout")
        assert not reg.is_available("ollama")

    def test_record_success_resets(self):
        reg = CircuitBreakerRegistry(failure_threshold=3)
        reg.record_failure("ollama", "err")
        reg.record_failure("ollama", "err")
        reg.record_success("ollama")
        cb = reg.get("ollama")
        assert cb.failure_count == 0

    def test_reset_single(self):
        reg = CircuitBreakerRegistry(failure_threshold=1)
        reg.record_failure("ollama", "err")
        assert not reg.is_available("ollama")
        reg.reset("ollama")
        assert reg.is_available("ollama")

    def test_reset_all(self):
        reg = CircuitBreakerRegistry(failure_threshold=1)
        reg.record_failure("ollama", "err")
        reg.record_failure("openai", "err")
        reg.reset_all()
        assert reg.is_available("ollama")
        assert reg.is_available("openai")

    def test_status_report(self):
        reg = CircuitBreakerRegistry()
        reg.record_failure("ollama", "err")
        status = reg.status()
        assert "ollama" in status
        assert status["ollama"]["failure_count"] == 1

    def test_custom_thresholds(self):
        reg = CircuitBreakerRegistry(
            failure_threshold=5,
            recovery_timeout=60.0,
            success_threshold=2,
        )
        cb = reg.get("test")
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60.0
        assert cb.success_threshold == 2


# ---------------------------------------------------------------------------
# Orchestrator retry integration tests
# ---------------------------------------------------------------------------


def _make_failing_orchestrator(
    fail_count: int = 10,
    retry_max: int = _RETRY_MAX_ATTEMPTS,
    retry_delay: float = 0.01,
    cb_threshold: int = _CB_FAILURE_THRESHOLD,
    cb_recovery: float = _CB_RECOVERY_TIMEOUT,
) -> tuple:
    """Create an orchestrator with a provider that fails N times then succeeds."""
    call_counter = {"count": 0}

    class FakeOrchestrator(ModelOrchestrator):
        def _call_provider(self, provider, messages, system_prompt,
                           max_tokens, temperature, json_mode, timeout):
            call_counter["count"] += 1
            if call_counter["count"] <= fail_count:
                raise RuntimeError(f"fail #{call_counter['count']}")
            return OrchestratorResult(
                text="ok",
                provider=provider.name,
                model=provider.model,
                success=True,
            )

        def _get_provider_chain(self, profile):
            return ["test_provider"]

    providers = {
        "test_provider": ProviderConfig(
            name="test_provider",
            base_url="http://localhost:1234",
            model="test-model",
            is_local=True,
            available=True,
        ),
    }
    cb = CircuitBreakerRegistry(
        failure_threshold=cb_threshold,
        recovery_timeout=cb_recovery,
    )
    orch = FakeOrchestrator(
        providers=providers,
        circuit_breaker=cb,
        retry_max_attempts=retry_max,
        retry_base_delay=retry_delay,
    )
    return orch, call_counter


class TestOrchestratorRetry:
    def test_succeeds_on_first_try(self):
        orch, counter = _make_failing_orchestrator(fail_count=0)
        result = orch.complete(
            task_type="chat",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result.success
        assert counter["count"] == 1

    def test_retries_and_succeeds(self):
        # Fails once, succeeds on retry (max_attempts=2 means 3 total tries)
        orch, counter = _make_failing_orchestrator(fail_count=1, retry_max=2)
        result = orch.complete(
            task_type="chat",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result.success
        assert counter["count"] == 2  # 1 fail + 1 success

    def test_retries_twice_and_succeeds(self):
        orch, counter = _make_failing_orchestrator(fail_count=2, retry_max=2)
        result = orch.complete(
            task_type="chat",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result.success
        assert counter["count"] == 3  # 2 fails + 1 success

    def test_exhausts_retries_falls_to_deterministic(self):
        # 3 retries (max_attempts=2 → 3 total), all fail, circuit trips
        orch, counter = _make_failing_orchestrator(
            fail_count=10, retry_max=2, cb_threshold=3,
        )
        result = orch.complete(
            task_type="chat",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert not result.success
        assert result.provider == "deterministic_fallback"
        assert counter["count"] == 3  # initial + 2 retries

    def test_circuit_breaker_trips_after_failures(self):
        orch, counter = _make_failing_orchestrator(
            fail_count=10, retry_max=0, cb_threshold=3,
        )
        # Call 3 times — each exhausts retries (0 retries = 1 attempt)
        for _ in range(3):
            orch.complete(task_type="chat",
                          messages=[{"role": "user", "content": "hi"}])
        # Now circuit breaker should be open
        status = orch.get_circuit_breaker_status()
        assert "test_provider" in status
        assert status["test_provider"]["state"] == _CB_OPEN

    def test_circuit_breaker_skips_open_provider(self):
        orch, counter = _make_failing_orchestrator(
            fail_count=10, retry_max=0, cb_threshold=1,
        )
        # First call trips the breaker
        orch.complete(task_type="chat",
                      messages=[{"role": "user", "content": "hi"}])
        assert counter["count"] == 1
        # Second call should NOT even try the provider (breaker open)
        orch.complete(task_type="chat",
                      messages=[{"role": "user", "content": "hi"}])
        assert counter["count"] == 1  # still 1, provider was skipped

    def test_circuit_breaker_recovers(self):
        orch, counter = _make_failing_orchestrator(
            fail_count=1, retry_max=0, cb_threshold=1, cb_recovery=0.05,
        )
        # First call fails and trips breaker
        result = orch.complete(task_type="chat",
                               messages=[{"role": "user", "content": "hi"}])
        assert not result.success
        # Wait for recovery
        time.sleep(0.06)
        # Now the provider recovers (fail_count=1, already used)
        result = orch.complete(task_type="chat",
                               messages=[{"role": "user", "content": "hi"}])
        assert result.success

    def test_reset_circuit_breaker(self):
        orch, _ = _make_failing_orchestrator(
            fail_count=10, retry_max=0, cb_threshold=1,
        )
        orch.complete(task_type="chat",
                      messages=[{"role": "user", "content": "hi"}])
        status = orch.get_circuit_breaker_status()
        assert status["test_provider"]["state"] == _CB_OPEN
        orch.reset_circuit_breaker("test_provider")
        status = orch.get_circuit_breaker_status()
        assert status["test_provider"]["state"] == _CB_CLOSED
        assert status["test_provider"]["failure_count"] == 0

    def test_reset_all_circuit_breakers(self):
        orch, _ = _make_failing_orchestrator(
            fail_count=10, retry_max=0, cb_threshold=1,
        )
        orch.complete(task_type="chat",
                      messages=[{"role": "user", "content": "hi"}])
        orch.reset_circuit_breaker()  # reset all
        assert orch.get_circuit_breaker_status() == {}


# ---------------------------------------------------------------------------
# Multi-provider fallback with circuit breaker
# ---------------------------------------------------------------------------


class TestMultiProviderFallback:
    def test_falls_through_to_second_provider(self):
        """If first provider is circuit-broken, uses second."""
        call_log = []

        class MultiOrch(ModelOrchestrator):
            def _call_provider(self, provider, messages, system_prompt,
                               max_tokens, temperature, json_mode, timeout):
                call_log.append(provider.name)
                if provider.name == "primary":
                    raise RuntimeError("primary down")
                return OrchestratorResult(
                    text="from secondary",
                    provider=provider.name,
                    model=provider.model,
                    success=True,
                )

            def _get_provider_chain(self, profile):
                return ["primary", "secondary"]

        providers = {
            "primary": ProviderConfig(
                name="primary", base_url="http://p:1", model="m1",
                is_local=True, available=True,
            ),
            "secondary": ProviderConfig(
                name="secondary", base_url="http://s:2", model="m2",
                is_local=True, available=True,
            ),
        }
        cb = CircuitBreakerRegistry(failure_threshold=3)
        orch = MultiOrch(
            providers=providers,
            circuit_breaker=cb,
            retry_max_attempts=0,
            retry_base_delay=0.01,
        )
        result = orch.complete(task_type="chat",
                               messages=[{"role": "user", "content": "hi"}])
        assert result.success
        assert result.provider == "secondary"
        assert result.fallback_used
        assert "primary" in call_log
        assert "secondary" in call_log

    def test_skips_circuit_broken_provider(self):
        """Tripped primary is skipped entirely, secondary tried directly."""
        call_log = []

        class MultiOrch(ModelOrchestrator):
            def _call_provider(self, provider, messages, system_prompt,
                               max_tokens, temperature, json_mode, timeout):
                call_log.append(provider.name)
                if provider.name == "primary":
                    raise RuntimeError("primary down")
                return OrchestratorResult(
                    text="from secondary",
                    provider=provider.name,
                    model=provider.model,
                    success=True,
                )

            def _get_provider_chain(self, profile):
                return ["primary", "secondary"]

        providers = {
            "primary": ProviderConfig(
                name="primary", base_url="http://p:1", model="m1",
                is_local=True, available=True,
            ),
            "secondary": ProviderConfig(
                name="secondary", base_url="http://s:2", model="m2",
                is_local=True, available=True,
            ),
        }
        cb = CircuitBreakerRegistry(failure_threshold=1)
        orch = MultiOrch(
            providers=providers,
            circuit_breaker=cb,
            retry_max_attempts=0,
            retry_base_delay=0.01,
        )
        # Trip the primary
        orch.complete(task_type="chat",
                      messages=[{"role": "user", "content": "hi"}])
        call_log.clear()
        # Next call should skip primary
        result = orch.complete(task_type="chat",
                               messages=[{"role": "user", "content": "hi"}])
        assert result.success
        assert "primary" not in call_log
        assert "secondary" in call_log


# ---------------------------------------------------------------------------
# Defaults validation
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_constants(self):
        assert _CB_FAILURE_THRESHOLD == 3
        assert _CB_RECOVERY_TIMEOUT == 30.0
        assert _CB_SUCCESS_THRESHOLD == 1
        assert _RETRY_MAX_ATTEMPTS == 2
        assert _RETRY_BASE_DELAY == 0.5

    def test_orchestrator_default_init(self):
        orch = ModelOrchestrator()
        assert orch._retry_max_attempts == _RETRY_MAX_ATTEMPTS
        assert orch._retry_base_delay == _RETRY_BASE_DELAY
        assert orch.get_circuit_breaker_status() == {}
