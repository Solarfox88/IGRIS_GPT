"""Centralized router import/registration helpers (#1111)."""

from __future__ import annotations

import importlib
import logging
from typing import Any, Iterable, Sequence


CORE_ROUTE_MODULES: Sequence[str] = (
    "igris.web.routers.routes_01",
    "igris.web.routers.routes_02",
    "igris.web.routers.routes_03",
    "igris.web.routers.routes_04",
    "igris.web.routers.routes_05",
    "igris.web.routers.routes_06",
    "igris.web.routers.routes_07",
    "igris.web.routers.routes_08",
    "igris.web.routers.routes_09",
    "igris.web.routers.routes_10",
)

OPTIONAL_API_ROUTERS: Sequence[tuple[str, str]] = (
    ("igris.api.routes.github_admin", "router"),
    ("igris.api.routes.github_write", "router"),
    ("igris.api.routes.github_read", "router"),
    ("igris.api.routes.network", "router"),
    ("igris.api.routes.interlocutor", "router"),
    ("igris.api.routes.tts", "router"),
    ("igris.api.routes.nav", "router"),
    ("igris.api.routes.code_health", "router"),
    ("igris.api.routes.conversation_memory_routes", "router"),
    ("igris.api.routes.context_routes", "router"),
    ("igris.api.routes.verifier_routes", "router"),
    ("igris.api.routes.learning_routes", "router"),
    ("igris.api.routes.shadow_routes", "router"),
)


def include_core_routers(app: Any, deps: Any, modules: Iterable[str] = CORE_ROUTE_MODULES) -> None:
    for module_name in modules:
        module = importlib.import_module(module_name)
        app.include_router(module.create_router(deps))


def include_optional_api_routers(
    app: Any,
    logger: logging.Logger | None = None,
    routers: Iterable[tuple[str, str]] = OPTIONAL_API_ROUTERS,
) -> None:
    log = logger or logging.getLogger("igris.router_registry")
    for module_name, router_attr in routers:
        try:
            module = importlib.import_module(module_name)
            app.include_router(getattr(module, router_attr))
        except Exception as exc:  # pragma: no cover - best effort path
            log.debug("Skipping optional router %s: %s", module_name, exc)
