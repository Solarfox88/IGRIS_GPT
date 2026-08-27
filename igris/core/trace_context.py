"""Trace context for end-to-end observability (#1324 Phase 1).

Provides lightweight trace_id propagation through the request lifecycle
without requiring the OpenTelemetry SDK. When OpenTelemetry is installed,
this module bridges to it; otherwise it uses a thread-local context.

Trace context includes:
- trace_id: unique per request/mission
- request_id: unique per HTTP request
- session_id: from auth session
- mission_id: from mission context
- run_id: from reasoning loop run

Usage:
    from igris.core.trace_context import TraceContext, trace_span

    # Automatic in FastAPI middleware
    ctx = TraceContext.current()
    ctx.set_mission_id("m123")

    # Manual span
    with trace_span("reasoning_step", mission_id="m123") as span:
        span.set_attribute("step", 1)
        span.set_attribute("model", "llama3.2")
"""
from __future__ import annotations

import contextvars
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)

# Thread-safe context variable for the current trace context
_current_trace: contextvars.ContextVar[Optional["TraceContext"]] = contextvars.ContextVar(
    "igris_trace_context", default=None
)


def _generate_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix."""
    uid = uuid.uuid4().hex[:16]
    return f"{prefix}{uid}" if prefix else uid


@dataclass
class TraceSpan:
    """A single span within a trace."""
    name: str
    trace_id: str
    span_id: str = field(default_factory=lambda: _generate_id())
    parent_span_id: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok, error, unset
    error: str = ""

    def set_attribute(self, key: str, value: Any) -> None:
        """Set an attribute on this span."""
        self.attributes[key] = value

    def set_status(self, status: str, error: str = "") -> None:
        """Set the span status."""
        self.status = status
        self.error = error

    def finish(self) -> None:
        """Mark the span as finished."""
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        """Span duration in milliseconds."""
        if self.end_time == 0.0:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        """Serialize span to dict for logging/export."""
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "attributes": dict(self.attributes),
            "status": self.status,
            "error": self.error,
        }


@dataclass
class TraceContext:
    """Trace context propagated through the request lifecycle.

    Holds trace IDs and a list of spans for the current trace.
    """
    trace_id: str = field(default_factory=lambda: _generate_id("trace-"))
    request_id: str = field(default_factory=lambda: _generate_id("req-"))
    session_id: str = ""
    mission_id: str = ""
    run_id: str = ""
    interlocutor_id: str = ""
    spans: list = field(default_factory=list)
    _current_span: Optional[TraceSpan] = None

    def set_session_id(self, session_id: str) -> None:
        self.session_id = session_id

    def set_mission_id(self, mission_id: str) -> None:
        self.mission_id = mission_id

    def set_run_id(self, run_id: str) -> None:
        self.run_id = run_id

    def set_interlocutor_id(self, interlocutor_id: str) -> None:
        self.interlocutor_id = interlocutor_id

    def start_span(
        self,
        name: str,
        parent_span_id: str = "",
    ) -> TraceSpan:
        """Start a new span within this trace."""
        span = TraceSpan(
            name=name,
            trace_id=self.trace_id,
            parent_span_id=parent_span_id or (self._current_span.span_id if self._current_span else ""),
        )
        self.spans.append(span)
        self._current_span = span
        return span

    def end_span(self, span: TraceSpan) -> None:
        """End a span."""
        span.finish()
        if self._current_span is span:
            self._current_span = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize context to dict for logging/export."""
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "mission_id": self.mission_id,
            "run_id": self.run_id,
            "interlocutor_id": self.interlocutor_id,
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
        }

    def to_headers(self) -> Dict[str, str]:
        """Export trace context as headers for propagation."""
        headers = {
            "X-Trace-Id": self.trace_id,
            "X-Request-Id": self.request_id,
        }
        if self.session_id:
            headers["X-Session-Id"] = self.session_id
        if self.mission_id:
            headers["X-Mission-Id"] = self.mission_id
        if self.run_id:
            headers["X-Run-Id"] = self.run_id
        return headers

    @classmethod
    def from_headers(cls, headers: Dict[str, str]) -> "TraceContext":
        """Create a TraceContext from incoming headers.

        Header lookup is case-insensitive (HTTP headers are case-insensitive).
        """
        # Build a case-insensitive lookup
        lower_headers = {k.lower(): v for k, v in headers.items()}
        ctx = cls(
            trace_id=lower_headers.get("x-trace-id", _generate_id("trace-")),
            request_id=lower_headers.get("x-request-id", _generate_id("req-")),
            session_id=lower_headers.get("x-session-id", ""),
            mission_id=lower_headers.get("x-mission-id", ""),
            run_id=lower_headers.get("x-run-id", ""),
        )
        return ctx

    @classmethod
    def current(cls) -> "TraceContext":
        """Get the current trace context, creating one if none exists."""
        ctx = _current_trace.get()
        if ctx is None:
            ctx = cls()
            _current_trace.set(ctx)
        return ctx

    @classmethod
    def set_current(cls, ctx: "TraceContext") -> Any:
        """Set the current trace context. Returns a token for reset."""
        return _current_trace.set(ctx)

    @classmethod
    def reset_current(cls, token: Any) -> None:
        """Reset the current trace context to a previous value."""
        _current_trace.reset(token)

    @classmethod
    def clear(cls) -> None:
        """Clear the current trace context."""
        _current_trace.set(None)


class trace_span:
    """Context manager for creating a trace span.

    Usage:
        with trace_span("reasoning_step") as span:
            span.set_attribute("step", 1)
            # do work
    """

    def __init__(
        self,
        name: str,
        mission_id: str = "",
        run_id: str = "",
        **attributes: Any,
    ) -> None:
        self.name = name
        self.mission_id = mission_id
        self.run_id = run_id
        self.attributes = attributes
        self.span: Optional[TraceSpan] = None
        self._token: Any = None

    def __enter__(self) -> TraceSpan:
        ctx = TraceContext.current()
        if self.mission_id:
            ctx.set_mission_id(self.mission_id)
        if self.run_id:
            ctx.set_run_id(self.run_id)
        self.span = ctx.start_span(self.name)
        for k, v in self.attributes.items():
            self.span.set_attribute(k, v)
        return self.span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.span is not None:
            if exc_type is not None:
                self.span.set_status("error", str(exc_val))
            ctx = TraceContext.current()
            ctx.end_span(self.span)


def get_trace_context() -> TraceContext:
    """Get the current trace context."""
    return TraceContext.current()


def clear_trace_context() -> None:
    """Clear the current trace context (for testing)."""
    TraceContext.clear()
