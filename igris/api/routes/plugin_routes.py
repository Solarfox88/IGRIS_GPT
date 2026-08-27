"""Plugin system API routes (#1325 Phase 2).

Provides /api/plugins endpoint for listing registered plugins.
Read-only — does not expose arbitrary plugin execution.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("")
async def list_plugins(request: Request) -> JSONResponse:
    """List all registered plugins with metadata.

    Returns a list of plugin metadata dicts. Read-only.
    Does not expose plugin execution endpoints.
    """
    from igris.core.plugin_system import get_plugin_registry

    registry = get_plugin_registry()

    # Auto-discover plugins if registry is empty
    if not registry.list_names():
        home = os.path.expanduser("~")
        search_paths = [
            os.path.join(home, ".igris", "plugins"),
            os.path.join(os.environ.get("PROJECT_ROOT", "."), "plugins"),
        ]
        registry.discover(*search_paths)

    plugins = registry.list_plugins()

    # Redact any sensitive fields from metadata
    safe_plugins = []
    for p in plugins:
        safe = {
            "name": p.get("name", ""),
            "actions": p.get("actions", []),
            "risk_level": p.get("risk_level", "unknown"),
            "description": p.get("description", ""),
            "version": p.get("version", ""),
        }
        safe_plugins.append(safe)

    return JSONResponse(status_code=200, content={
        "plugins": safe_plugins,
        "count": len(safe_plugins),
    })


@router.get("/{plugin_name}")
async def get_plugin(plugin_name: str, request: Request) -> JSONResponse:
    """Get metadata for a specific plugin by name.

    Returns 404 if plugin not found.
    """
    from igris.core.plugin_system import get_plugin_registry

    registry = get_plugin_registry()
    plugin = registry.get(plugin_name)

    if plugin is None:
        return JSONResponse(
            status_code=404,
            content={"error": "Plugin not found", "plugin_name": plugin_name},
        )

    meta = plugin.metadata()
    # Redact sensitive fields
    safe = {
        "name": meta.get("name", ""),
        "actions": meta.get("actions", []),
        "risk_level": meta.get("risk_level", "unknown"),
        "description": meta.get("description", ""),
        "version": meta.get("version", ""),
    }

    return JSONResponse(status_code=200, content=safe)
