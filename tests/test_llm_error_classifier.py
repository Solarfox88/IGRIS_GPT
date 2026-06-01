from __future__ import annotations

from igris.core.llm_error_classifier import classify_llm_provider_error


def test_timeout_classification() -> None:
    c = classify_llm_provider_error(message="request timed out")
    assert c.category == "timeout"
    assert c.retryable is True


def test_rate_limit_classification() -> None:
    c = classify_llm_provider_error(message="HTTP Error 429: Too Many Requests")
    assert c.category == "rate_limit"
    assert c.retryable is True
    assert c.provider_switch_allowed is True


def test_auth_error_classification() -> None:
    c = classify_llm_provider_error(message="HTTP Error 401 unauthorized")
    assert c.category == "auth_error"
    assert c.retryable is False


def test_quota_exceeded_classification() -> None:
    c = classify_llm_provider_error(message="insufficient_quota")
    assert c.category == "quota_exceeded"
    assert c.provider_switch_allowed is True


def test_context_length_classification() -> None:
    c = classify_llm_provider_error(message="maximum context length exceeded")
    assert c.category == "context_length"


def test_malformed_response_classification() -> None:
    c = classify_llm_provider_error(message="json decode error")
    assert c.category == "malformed_response"


def test_tool_call_invalid_classification() -> None:
    c = classify_llm_provider_error(message="tool call arguments schema mismatch")
    assert c.category == "tool_call_invalid"


def test_secret_redacted_in_reason() -> None:
    c = classify_llm_provider_error(message="invalid api key sk-test-secret")
    assert "sk-test-secret" not in c.reason
