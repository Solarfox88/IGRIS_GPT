"""Tests for trace middleware (#1324 Phase 2)."""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from igris.web.trace_middleware import apply_trace_middleware


def _create_app() -> FastAPI:
    """Create a test app with trace middleware."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint(request: Request) -> dict:
        trace = getattr(request.state, "trace", None)
        if trace is not None:
            return {"trace_id": trace.trace_id, "request_id": trace.request_id}
        return {"trace_id": "missing", "request_id": "missing"}

    @app.get("/headers")
    async def headers_endpoint(request: Request) -> dict:
        trace = request.state.trace
        return {
            "trace_id": trace.trace_id,
            "x_trace_id_header": request.headers.get("X-Trace-Id", ""),
        }

    apply_trace_middleware(app)
    return app


class TestTraceMiddleware:
    """Tests for trace middleware."""

    def test_response_has_trace_headers(self) -> None:
        """Response should include X-Trace-Id and X-Request-Id headers."""
        app = _create_app()
        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert "X-Trace-Id" in response.headers
        assert "X-Request-Id" in response.headers
        assert response.headers["X-Trace-Id"].startswith("trace-")
        assert response.headers["X-Request-Id"].startswith("req-")

    def test_trace_context_in_request_state(self) -> None:
        """TraceContext should be available in request.state."""
        app = _create_app()
        client = TestClient(app)
        response = client.get("/test")
        data = response.json()
        assert data["trace_id"].startswith("trace-")
        assert data["request_id"].startswith("req-")

    def test_trace_id_propagation_from_header(self) -> None:
        """Incoming X-Trace-Id should be propagated."""
        app = _create_app()
        client = TestClient(app)
        response = client.get("/test", headers={"X-Trace-Id": "trace-incoming-123"})
        assert response.headers["X-Trace-Id"] == "trace-incoming-123"

    def test_request_id_propagation_from_header(self) -> None:
        """Incoming X-Request-Id should be propagated."""
        app = _create_app()
        client = TestClient(app)
        response = client.get("/test", headers={"X-Request-Id": "req-incoming-456"})
        assert response.headers["X-Request-Id"] == "req-incoming-456"

    def test_unique_trace_ids_per_request(self) -> None:
        """Each request should get a unique trace_id when no header is provided."""
        app = _create_app()
        client = TestClient(app)
        r1 = client.get("/test")
        r2 = client.get("/test")
        assert r1.headers["X-Trace-Id"] != r2.headers["X-Trace-Id"]

    def test_trace_id_consistent_in_response_and_state(self) -> None:
        """Trace ID in response header should match the one in request state."""
        app = _create_app()
        client = TestClient(app)
        response = client.get("/test")
        data = response.json()
        assert response.headers["X-Trace-Id"] == data["trace_id"]
        assert response.headers["X-Request-Id"] == data["request_id"]

    def test_mission_id_propagation(self) -> None:
        """Incoming X-Mission-Id should be available in trace context."""
        app = FastAPI()

        @app.get("/mission")
        async def mission_endpoint(request: Request) -> dict:
            trace = request.state.trace
            return {"mission_id": trace.mission_id}

        apply_trace_middleware(app)
        client = TestClient(app)
        response = client.get("/mission", headers={"X-Mission-Id": "m-123"})
        assert response.json()["mission_id"] == "m-123"
