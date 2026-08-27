"""Tests for plugin API endpoint (#1325 Phase 2)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from igris.api.routes.plugin_routes import router
from igris.core.plugin_system import (
    PluginRegistry,
    ToolPlugin,
    reset_plugin_registry,
    get_plugin_registry,
)
from typing import Any


class TestPlugin(ToolPlugin):
    """Test plugin."""
    name = "test_api_plugin"
    actions = ["run", "status"]
    risk_level = "low"
    description = "Test plugin for API tests"

    def execute(self, action: str, **kwargs: Any) -> dict:
        return {"status": "ok"}


def _create_app() -> FastAPI:
    """Create a test app with plugin routes."""
    reset_plugin_registry()
    app = FastAPI()
    app.include_router(router)
    return app


class TestPluginListEndpoint:
    """Tests for GET /api/plugins."""

    def test_list_empty(self) -> None:
        """List endpoint should return empty list when no plugins registered."""
        app = _create_app()
        client = TestClient(app)
        response = client.get("/api/plugins")
        assert response.status_code == 200
        data = response.json()
        assert "plugins" in data
        assert "count" in data
        assert data["count"] == 0

    def test_list_with_plugin(self) -> None:
        """List endpoint should return registered plugins."""
        app = _create_app()
        registry = get_plugin_registry()
        registry.register(TestPlugin())
        client = TestClient(app)
        response = client.get("/api/plugins")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["plugins"][0]["name"] == "test_api_plugin"
        assert data["plugins"][0]["actions"] == ["run", "status"]
        assert data["plugins"][0]["risk_level"] == "low"

    def test_list_redacts_sensitive_fields(self) -> None:
        """List endpoint should not expose class name or internal fields."""
        app = _create_app()
        registry = get_plugin_registry()
        registry.register(TestPlugin())
        client = TestClient(app)
        response = client.get("/api/plugins")
        data = response.json()
        plugin = data["plugins"][0]
        # Should only have safe fields
        assert "class" not in plugin
        assert set(plugin.keys()) == {"name", "actions", "risk_level", "description", "version"}


class TestPluginDetailEndpoint:
    """Tests for GET /api/plugins/{plugin_name}."""

    def test_get_existing_plugin(self) -> None:
        """Get endpoint should return plugin metadata."""
        app = _create_app()
        registry = get_plugin_registry()
        registry.register(TestPlugin())
        client = TestClient(app)
        response = client.get("/api/plugins/test_api_plugin")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test_api_plugin"
        assert data["actions"] == ["run", "status"]

    def test_get_nonexistent_plugin(self) -> None:
        """Get endpoint should return 404 for unknown plugin."""
        app = _create_app()
        client = TestClient(app)
        response = client.get("/api/plugins/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_get_redacts_sensitive_fields(self) -> None:
        """Get endpoint should not expose class name."""
        app = _create_app()
        registry = get_plugin_registry()
        registry.register(TestPlugin())
        client = TestClient(app)
        response = client.get("/api/plugins/test_api_plugin")
        data = response.json()
        assert "class" not in data
