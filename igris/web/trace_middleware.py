"""Trace context middleware for FastAPI (#1324 Phase 2).

Automatically creates or propagates trace_id for every HTTP request.
Adds X-Trace-Id and X-Request-Id response headers.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from igris.core.trace_context import TraceContext, clear_trace_context

_log = logging.getLogger(__name__)


class TraceMiddleware(BaseHTTPMiddleware):
    """Middleware that injects trace context into every request.

    - Creates or propagates trace_id from X-Trace-Id header
    - Creates or propagates request_id from X-Request-Id header
    - Stores TraceContext in request.state.trace
    - Adds X-Trace-Id and X-Request-Id to response headers
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Clear any previous trace context (thread-safety for contextvars)
        clear_trace_context()

        # Build trace context from incoming headers
        headers = {k: v for k, v in request.headers.items()}
        ctx = TraceContext.from_headers(headers)

        # Store in request state for downstream handlers
        request.state.trace = ctx

        # Set as current context for logging
        TraceContext.set_current(ctx)

        # Process request
        response = await call_next(request)

        # Add trace headers to response
        response.headers["X-Trace-Id"] = ctx.trace_id
        response.headers["X-Request-Id"] = ctx.request_id

        return response


def apply_trace_middleware(app: FastAPI) -> None:
    """Apply the trace middleware to a FastAPI app."""
    app.add_middleware(TraceMiddleware)
    _log.info("trace_middleware: enabled — X-Trace-Id and X-Request-Id headers active")
