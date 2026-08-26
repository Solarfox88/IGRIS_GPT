"""Tests for trace context (#1324 Phase 1)."""
import time

import pytest

from igris.core.trace_context import (
    TraceContext,
    TraceSpan,
    trace_span,
    get_trace_context,
    clear_trace_context,
)


class TestTraceContext:
    """Unit tests for TraceContext."""

    def setup_method(self) -> None:
        """Clear trace context before each test."""
        clear_trace_context()

    def test_trace_context_has_unique_ids(self) -> None:
        """Each TraceContext should have unique trace_id and request_id."""
        ctx1 = TraceContext()
        ctx2 = TraceContext()
        assert ctx1.trace_id != ctx2.trace_id
        assert ctx1.request_id != ctx2.request_id

    def test_current_returns_singleton(self) -> None:
        """TraceContext.current() should return the same context within a call."""
        ctx1 = TraceContext.current()
        ctx2 = TraceContext.current()
        assert ctx1 is ctx2

    def test_set_mission_id(self) -> None:
        """set_mission_id should update the context."""
        ctx = TraceContext()
        ctx.set_mission_id("m123")
        assert ctx.mission_id == "m123"

    def test_set_session_id(self) -> None:
        """set_session_id should update the context."""
        ctx = TraceContext()
        ctx.set_session_id("s456")
        assert ctx.session_id == "s456"

    def test_start_and_end_span(self) -> None:
        """start_span and end_span should track spans."""
        ctx = TraceContext()
        span = ctx.start_span("test_operation")
        assert span.name == "test_operation"
        assert span.trace_id == ctx.trace_id
        assert span.end_time == 0.0  # not finished
        ctx.end_span(span)
        assert span.end_time > 0.0  # finished

    def test_span_duration(self) -> None:
        """Span duration should be measurable."""
        ctx = TraceContext()
        span = ctx.start_span("timed_op")
        time.sleep(0.01)
        ctx.end_span(span)
        assert span.duration_ms > 0

    def test_span_attributes(self) -> None:
        """Span attributes should be settable."""
        ctx = TraceContext()
        span = ctx.start_span("attr_op")
        span.set_attribute("model", "llama3.2")
        span.set_attribute("tokens", 100)
        assert span.attributes["model"] == "llama3.2"
        assert span.attributes["tokens"] == 100

    def test_span_error_status(self) -> None:
        """Span should support error status."""
        ctx = TraceContext()
        span = ctx.start_span("error_op")
        span.set_status("error", "Something went wrong")
        assert span.status == "error"
        assert span.error == "Something went wrong"

    def test_to_dict(self) -> None:
        """to_dict should serialize the context."""
        ctx = TraceContext()
        ctx.set_mission_id("m123")
        ctx.start_span("op1")
        d = ctx.to_dict()
        assert d["trace_id"] == ctx.trace_id
        assert d["mission_id"] == "m123"
        assert d["span_count"] == 1
        assert len(d["spans"]) == 1

    def test_to_headers(self) -> None:
        """to_headers should export propagation headers."""
        ctx = TraceContext()
        ctx.set_session_id("s123")
        ctx.set_mission_id("m456")
        headers = ctx.to_headers()
        assert "X-Trace-Id" in headers
        assert "X-Request-Id" in headers
        assert headers["X-Session-Id"] == "s123"
        assert headers["X-Mission-Id"] == "m456"

    def test_from_headers(self) -> None:
        """from_headers should create context from headers."""
        headers = {
            "X-Trace-Id": "trace-abc123",
            "X-Request-Id": "req-def456",
            "X-Session-Id": "s789",
            "X-Mission-Id": "m000",
        }
        ctx = TraceContext.from_headers(headers)
        assert ctx.trace_id == "trace-abc123"
        assert ctx.request_id == "req-def456"
        assert ctx.session_id == "s789"
        assert ctx.mission_id == "m000"

    def test_from_headers_generates_missing_ids(self) -> None:
        """from_headers should generate missing IDs."""
        ctx = TraceContext.from_headers({})
        assert ctx.trace_id.startswith("trace-")
        assert ctx.request_id.startswith("req-")


class TestTraceSpanContextManager:
    """Tests for the trace_span context manager."""

    def setup_method(self) -> None:
        clear_trace_context()

    def test_trace_span_creates_span(self) -> None:
        """trace_span should create and end a span."""
        with trace_span("test_op") as span:
            assert span.name == "test_op"
            assert span.end_time == 0.0
        assert span.end_time > 0.0

    def test_trace_span_sets_attributes(self) -> None:
        """trace_span should set attributes from kwargs."""
        with trace_span("test_op", model="llama3.2", step=1) as span:
            pass
        assert span.attributes["model"] == "llama3.2"
        assert span.attributes["step"] == 1

    def test_trace_span_error_status_on_exception(self) -> None:
        """trace_span should set error status on exception."""
        with pytest.raises(ValueError):
            with trace_span("error_op") as span:
                raise ValueError("test error")
        assert span.status == "error"
        assert "test error" in span.error

    def test_trace_span_sets_mission_id(self) -> None:
        """trace_span should set mission_id on the context."""
        with trace_span("mission_op", mission_id="m123") as span:
            ctx = get_trace_context()
            assert ctx.mission_id == "m123"

    def test_trace_span_nested(self) -> None:
        """Nested trace_spans should have parent span IDs."""
        with trace_span("parent_op") as parent:
            with trace_span("child_op") as child:
                pass
        assert child.parent_span_id == parent.span_id


class TestTraceContextIntegration:
    """Integration tests for trace context."""

    def setup_method(self) -> None:
        clear_trace_context()

    def test_get_trace_context(self) -> None:
        """get_trace_context should return the current context."""
        ctx = get_trace_context()
        assert isinstance(ctx, TraceContext)

    def test_clear_trace_context(self) -> None:
        """clear_trace_context should clear the current context."""
        ctx1 = TraceContext.current()
        ctx1.set_mission_id("m123")
        clear_trace_context()
        ctx2 = TraceContext.current()
        assert ctx2 is not ctx1
        assert ctx2.mission_id == ""

    def test_span_to_dict(self) -> None:
        """Span to_dict should include all fields."""
        span = TraceSpan(name="test", trace_id="trace-123")
        span.set_attribute("key", "value")
        time.sleep(0.001)
        span.finish()
        d = span.to_dict()
        assert d["name"] == "test"
        assert d["trace_id"] == "trace-123"
        assert d["attributes"]["key"] == "value"
        assert d["duration_ms"] >= 0
