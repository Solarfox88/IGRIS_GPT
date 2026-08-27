"""Plugin system for extensible tools (#1325 Phase 1).

Provides a plugin interface, discovery mechanism, and registry for
adding new tools to IGRIS without modifying the core.

Usage:
    from igris.core.plugin_system import PluginRegistry, ToolPlugin

    # Define a plugin
    class MyPlugin(ToolPlugin):
        name = "my_tool"
        actions = ["run", "status"]
        risk_level = "low"

        def execute(self, action: str, **kwargs) -> dict:
            if action == "run":
                return {"status": "ok", "output": "done"}
            return {"status": "error", "message": "unknown action"}

    # Register and use
    registry = PluginRegistry()
    registry.register(MyPlugin())
    result = registry.execute("my_tool", "run", arg1="value")
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

_log = logging.getLogger(__name__)


@runtime_checkable
class ToolPluginProtocol(Protocol):
    """Protocol for tool plugins.

    Every plugin must implement this interface.
    """

    @property
    def name(self) -> str:
        """Unique plugin name."""
        ...

    @property
    def actions(self) -> List[str]:
        """List of supported actions."""
        ...

    @property
    def risk_level(self) -> str:
        """Risk level: low, medium, high."""
        ...

    def execute(self, action: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute an action and return a result dict."""
        ...


class ToolPlugin:
    """Base class for tool plugins.

    Subclasses must define:
    - name: unique plugin name
    - actions: list of supported actions
    - risk_level: "low", "medium", or "high"
    - execute(): action handler

    Example:
        class GitPlugin(ToolPlugin):
            name = "git"
            actions = ["status", "diff", "log"]
            risk_level = "low"

            def execute(self, action, **kwargs):
                if action == "status":
                    return {"status": "ok", "output": "clean"}
                return {"status": "error", "message": "unknown action"}
    """

    name: str = ""
    actions: List[str] = []
    risk_level: str = "low"
    description: str = ""
    version: str = "1.0.0"

    def execute(self, action: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute an action. Override in subclass."""
        return {
            "status": "error",
            "message": f"Action '{action}' not implemented for plugin '{self.name}'",
        }

    def metadata(self) -> Dict[str, Any]:
        """Return plugin metadata."""
        return {
            "name": self.name,
            "actions": list(self.actions),
            "risk_level": self.risk_level,
            "description": self.description,
            "version": self.version,
            "class": self.__class__.__name__,
        }


@dataclass
class PluginRegistry:
    """Registry for tool plugins.

    Supports:
    - Manual registration via register()
    - Auto-discovery from ~/.igris/plugins/ and plugins/ directories
    - Lookup by name and action
    - Metadata export for UI/API
    """

    _plugins: Dict[str, ToolPlugin] = field(default_factory=dict)

    def register(self, plugin: ToolPlugin) -> None:
        """Register a plugin instance."""
        if not plugin.name:
            raise ValueError("Plugin must have a non-empty name")
        if plugin.name in self._plugins:
            _log.warning("plugin: overwriting existing plugin '%s'", plugin.name)
        self._plugins[plugin.name] = plugin
        _log.info("plugin: registered '%s' (actions=%s, risk=%s)",
                   plugin.name, plugin.actions, plugin.risk_level)

    def unregister(self, name: str) -> bool:
        """Unregister a plugin by name. Returns True if found."""
        if name in self._plugins:
            del self._plugins[name]
            _log.info("plugin: unregistered '%s'", name)
            return True
        return False

    def get(self, name: str) -> Optional[ToolPlugin]:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> List[Dict[str, Any]]:
        """List all registered plugins with metadata."""
        return [p.metadata() for p in self._plugins.values()]

    def list_names(self) -> List[str]:
        """List all plugin names."""
        return sorted(self._plugins.keys())

    def execute(self, plugin_name: str, action: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute an action on a plugin.

        Returns error dict if plugin or action not found.
        """
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            return {
                "status": "error",
                "message": f"Plugin '{plugin_name}' not found",
            }

        if action not in plugin.actions:
            return {
                "status": "error",
                "message": f"Action '{action}' not supported by plugin '{plugin_name}'",
                "available_actions": list(plugin.actions),
            }

        try:
            result = plugin.execute(action, **kwargs)
            if not isinstance(result, dict):
                return {
                    "status": "error",
                    "message": f"Plugin '{plugin_name}' returned non-dict result",
                    "raw": str(result),
                }
            return result
        except Exception as exc:
            _log.error("plugin: '%s' action '%s' failed: %s", plugin_name, action, exc, exc_info=True)
            return {
                "status": "error",
                "message": f"Plugin execution failed: {exc}",
                "plugin": plugin_name,
                "action": action,
            }

    def discover(self, *search_paths: str) -> int:
        """Auto-discover plugins from search paths.

        Looks for Python files in the given directories and imports any
        module that defines a ToolPlugin subclass.

        Returns the number of plugins discovered.
        """
        count = 0

        # Default search paths
        paths = list(search_paths)
        if not paths:
            # ~/.igris/plugins/
            home = os.path.expanduser("~")
            paths.append(os.path.join(home, ".igris", "plugins"))
            # ./plugins/ (project root)
            paths.append("plugins")

        for search_path in paths:
            p = Path(search_path)
            if not p.exists() or not p.is_dir():
                continue

            _log.debug("plugin: discovering in %s", p)

            for py_file in sorted(p.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                try:
                    # Import the module
                    mod_name = f"_igris_plugin_{py_file.stem}"
                    spec = importlib.util.spec_from_file_location(mod_name, str(py_file))
                    if spec is None or spec.loader is None:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)

                    # Find ToolPlugin subclasses
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (isinstance(attr, type)
                                and issubclass(attr, ToolPlugin)
                                and attr is not ToolPlugin
                                and attr.__module__ == mod_name):
                            try:
                                instance = attr()
                                if instance.name:
                                    self.register(instance)
                                    count += 1
                            except Exception as exc:
                                _log.warning("plugin: failed to instantiate %s: %s", attr_name, exc)

                except Exception as exc:
                    _log.warning("plugin: failed to import %s: %s", py_file, exc)

        _log.info("plugin: discovered %d plugins from %s", count, paths)
        return count

    def clear(self) -> None:
        """Clear all registered plugins."""
        self._plugins.clear()


# Global registry instance
_global_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """Get the global PluginRegistry instance."""
    global _global_registry
    if _global_registry is None:
        _global_registry = PluginRegistry()
    return _global_registry


def reset_plugin_registry() -> None:
    """Reset the global PluginRegistry (for testing)."""
    global _global_registry
    _global_registry = None
