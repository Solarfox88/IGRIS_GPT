"""Tests for backward-compatible API path aliases (#1289)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from igris.api.routes.github_read import router, legacy_router


def _router_paths(rtr: object) -> set[str]:
    """Extract all paths from a router or app."""
    paths: set[str] = set()
    for r in getattr(rtr, "routes", []):
        path = getattr(r, "path", None)
        if path:
            paths.add(path)
    return paths


@pytest.fixture()
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.include_router(legacy_router)
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_legacy_issues_alias_exists() -> None:
    """Legacy /api/github/issues path should be registered (deprecated)."""
    routes = _router_paths(legacy_router)
    assert "/api/github/issues" in routes, "Legacy /api/github/issues alias missing"


def test_legacy_prs_alias_exists() -> None:
    """Legacy /api/github/prs/{pr_number} path should be registered (deprecated)."""
    routes = _router_paths(legacy_router)
    assert "/api/github/prs/{pr_number}" in routes, "Legacy /api/github/prs alias missing"


def test_canonical_issues_path_exists() -> None:
    """Canonical /api/github/read/issues path should still exist."""
    routes = _router_paths(router)
    assert "/api/github/read/issues" in routes


def test_canonical_pr_path_exists() -> None:
    """Canonical /api/github/read/pr/{pr_number} path should still exist."""
    routes = _router_paths(router)
    assert "/api/github/read/pr/{pr_number}" in routes


def test_legacy_git_log_alias_registered() -> None:
    """Legacy /api/git/log alias should be present in routes_08 source."""
    from pathlib import Path

    source = Path("igris/web/routers/routes_08.py").read_text()
    assert '"/api/git/log"' in source, "Legacy /api/git/log alias missing"
    assert '"/api/tools/git/log"' in source, "Canonical /api/tools/git/log missing"


def test_legacy_terminal_exec_alias_registered() -> None:
    """Legacy /api/terminal/exec alias should be present in routes_04 source."""
    from pathlib import Path

    source = Path("igris/web/routers/routes_04.py").read_text()
    assert '"/api/terminal/exec"' in source, "Legacy /api/terminal/exec alias missing"
    assert '"/api/terminal/run"' in source, "Canonical /api/terminal/run missing"
