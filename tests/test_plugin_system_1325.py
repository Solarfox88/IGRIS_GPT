"""Tests for plugin system (#1325 Phase 1)."""
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from igris.core.plugin_system import (
    PluginRegistry,
    ToolPlugin,
    ToolPluginProtocol,
    get_plugin_registry,
    reset_plugin_registry,
)


class EchoPlugin(ToolPlugin):
    """Test plugin that echoes input."""
    name = "echo"
    actions = ["run", "status"]
    risk_level = "low"
    description = "Echo plugin for testing"

    def execute(self, action: str, **kwargs: Any) -> dict:
        if action == "run":
            return {"status": "ok", "output": kwargs.get("message", "")}
        if action == "status":
            return {"status": "ok", "running": True}
        return {"status": "error", "message": "unknown action"}


class CalculatorPlugin(ToolPlugin):
    """Test plugin for calculations."""
    name = "calculator"
    actions = ["add", "multiply"]
    risk_level = "low"

    def execute(self, action: str, **kwargs: Any) -> dict:
        a = kwargs.get("a", 0)
        b = kwargs.get("b", 0)
        if action == "add":
            return {"status": "ok", "result": a + b}
        if action == "multiply":
            return {"status": "ok", "result": a * b}
        return {"status": "error", "message": "unknown action"}




class TestToolPlugin:
    """Tests for ToolPlugin base class."""

    def test_plugin_metadata(self) -> None:
        """Plugin should return correct metadata."""
        plugin = EchoPlugin()
        meta = plugin.metadata()
        assert meta["name"] == "echo"
        assert meta["actions"] == ["run", "status"]
        assert meta["risk_level"] == "low"
        assert meta["description"] == "Echo plugin for testing"

    def test_plugin_execute(self) -> None:
        """Plugin should execute actions."""
        plugin = EchoPlugin()
        result = plugin.execute("run", message="hello")
        assert result["status"] == "ok"
        assert result["output"] == "hello"

    def test_plugin_protocol_compliance(self) -> None:
        """ToolPlugin should satisfy ToolPluginProtocol."""
        plugin = EchoPlugin()
        assert isinstance(plugin, ToolPluginProtocol)


class TestPluginRegistry:
    """Tests for PluginRegistry."""

    def test_register_and_get(self) -> None:
        """Register and retrieve a plugin."""
        registry = PluginRegistry()
        plugin = EchoPlugin()
        registry.register(plugin)
        assert registry.get("echo") is plugin

    def test_register_empty_name_raises(self) -> None:
        """Registering a plugin with empty name should raise."""
        registry = PluginRegistry()

        class NoName(ToolPlugin):
            name = ""
            actions = ["run"]
            risk_level = "low"

        with pytest.raises(ValueError):
            registry.register(NoName())

    def test_unregister(self) -> None:
        """Unregister should remove the plugin."""
        registry = PluginRegistry()
        registry.register(EchoPlugin())
        assert registry.unregister("echo") is True
        assert registry.get("echo") is None
        assert registry.unregister("echo") is False

    def test_list_plugins(self) -> None:
        """list_plugins should return metadata for all plugins."""
        registry = PluginRegistry()
        registry.register(EchoPlugin())
        registry.register(CalculatorPlugin())
        plugins = registry.list_plugins()
        assert len(plugins) == 2
        names = [p["name"] for p in plugins]
        assert "echo" in names
        assert "calculator" in names

    def test_list_names(self) -> None:
        """list_names should return sorted plugin names."""
        registry = PluginRegistry()
        registry.register(CalculatorPlugin())
        registry.register(EchoPlugin())
        names = registry.list_names()
        assert names == ["calculator", "echo"]

    def test_execute_success(self) -> None:
        """execute should run the plugin action."""
        registry = PluginRegistry()
        registry.register(CalculatorPlugin())
        result = registry.execute("calculator", "add", a=2, b=3)
        assert result["status"] == "ok"
        assert result["result"] == 5

    def test_execute_plugin_not_found(self) -> None:
        """execute should return error for unknown plugin."""
        registry = PluginRegistry()
        result = registry.execute("nonexistent", "run")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_execute_action_not_supported(self) -> None:
        """execute should return error for unsupported action."""
        registry = PluginRegistry()
        registry.register(EchoPlugin())
        result = registry.execute("echo", "nonexistent_action")
        assert result["status"] == "error"
        assert "not supported" in result["message"]
        assert "available_actions" in result

    def test_execute_handles_exception(self) -> None:
        """execute should handle plugin exceptions gracefully."""
        registry = PluginRegistry()

        class ErrorPlugin(ToolPlugin):
            name = "error_plugin"
            actions = ["crash"]
            risk_level = "low"

            def execute(self, action: str, **kwargs: Any) -> dict:
                raise RuntimeError("intentional crash")

        registry.register(ErrorPlugin())
        result = registry.execute("error_plugin", "crash")
        assert result["status"] == "error"
        assert "intentional crash" in result["message"]

    def test_execute_non_dict_result(self) -> None:
        """execute should handle non-dict return values."""
        registry = PluginRegistry()

        class BadPlugin(ToolPlugin):
            name = "bad_plugin"
            actions = ["run"]
            risk_level = "low"

            def execute(self, action: str, **kwargs: Any) -> dict:
                return "not a dict"  # type: ignore[return-value]

        registry.register(BadPlugin())
        result = registry.execute("bad_plugin", "run")
        assert result["status"] == "error"
        assert "non-dict" in result["message"]

    def test_clear(self) -> None:
        """clear should remove all plugins."""
        registry = PluginRegistry()
        registry.register(EchoPlugin())
        registry.register(CalculatorPlugin())
        registry.clear()
        assert len(registry.list_names()) == 0

    def test_overwrite_warning(self) -> None:
        """Registering an existing plugin should overwrite."""
        registry = PluginRegistry()
        registry.register(EchoPlugin())
        # Registering again should not raise
        registry.register(EchoPlugin())
        assert registry.get("echo") is not None


class TestPluginDiscovery:
    """Tests for plugin auto-discovery."""

    def test_discover_from_directory(self, tmp_path: Path) -> None:
        """discover should find plugins in a directory."""
        # Create a plugin file
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        plugin_file = plugin_dir / "test_plugin.py"
        plugin_file.write_text('''
from igris.core.plugin_system import ToolPlugin

class TestPlugin(ToolPlugin):
    name = "test_discovered"
    actions = ["run"]
    risk_level = "low"

    def execute(self, action, **kwargs):
        return {"status": "ok", "discovered": True}
''')

        registry = PluginRegistry()
        count = registry.discover(str(plugin_dir))
        assert count == 1
        assert "test_discovered" in registry.list_names()

    def test_discover_empty_directory(self, tmp_path: Path) -> None:
        """discover should return 0 for empty directory."""
        registry = PluginRegistry()
        count = registry.discover(str(tmp_path))
        assert count == 0

    def test_discover_nonexistent_directory(self) -> None:
        """discover should handle non-existent directories."""
        registry = PluginRegistry()
        count = registry.discover("/nonexistent/path")
        assert count == 0

    def test_discover_skips_underscore_files(self, tmp_path: Path) -> None:
        """discover should skip files starting with underscore."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("")
        (plugin_dir / "_private.py").write_text('')

        registry = PluginRegistry()
        count = registry.discover(str(plugin_dir))
        assert count == 0


class TestGlobalRegistry:
    """Tests for global registry singleton."""

    def test_singleton(self) -> None:
        """get_plugin_registry should return a singleton."""
        reset_plugin_registry()
        reg1 = get_plugin_registry()
        reg2 = get_plugin_registry()
        assert reg1 is reg2
        reset_plugin_registry()
