"""Tests for rate limit status endpoint (#1329)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from igris.api.routes.rate_limit_routes import router
from igris.core.user_rate_limiter import reset_user_rate_limiter


class TestRateLimitEndpoint:
    """Tests for /api/rate-limit/status endpoint."""

    def _create_app(self) -> FastAPI:
        """Create a test app with the rate limit router."""
        reset_user_rate_limiter()
        app = FastAPI()
        app.include_router(router)
        return app

    def test_status_anonymous(self) -> None:
        """Status endpoint should return defaults for anonymous user."""
        app = self._create_app()
        client = TestClient(app)
        response = client.get("/api/rate-limit/status")
        assert response.status_code == 200
        data = response.json()
        assert data["profile_id"] == "anonymous"
        assert data["current"] == 0
        assert "limit" in data
        assert "remaining" in data
        assert "window_seconds" in data

    def test_status_with_invalid_token(self) -> None:
        """Status endpoint should handle invalid session token gracefully."""
        app = self._create_app()
        client = TestClient(app)
        response = client.get(
            "/api/rate-limit/status",
            headers={"Authorization": "Bearer invalid-token-xyz"},
        )
        assert response.status_code == 200
        data = response.json()
        # Should fall back to anonymous
        assert data["profile_id"] == "anonymous"

    def test_status_returns_json(self) -> None:
        """Status endpoint should return JSON content."""
        app = self._create_app()
        client = TestClient(app)
        response = client.get("/api/rate-limit/status")
        assert response.headers["content-type"].startswith("application/json")
