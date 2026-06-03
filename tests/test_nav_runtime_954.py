"""
Runtime tests for nav_invariants wiring — issue #954.

Verifies:
- GET /api/nav/invariant returns {"passed": bool, ...}
- Current index.html passes nav invariants
- Fabricated 15-tab HTML fails
- NavInvariantReport logic
- Startup wiring exists in server lifespan
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from igris.web.nav_invariants import check_nav_hierarchy, NavInvariantReport, MAX_TOP_LEVEL_TABS


@pytest.fixture
def client(tmp_path):
    from igris.models.config import CONFIG
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    for d in [".igris/tasks", ".igris/timeline", ".igris/memory"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["IGRIS_PROJECT_ROOT"] = str(root)
    CONFIG.project_root = Path(str(root))
    from igris.web.server import create_app
    return TestClient(create_app())


# ---- Unit tests for check_nav_hierarchy ----

class TestCheckNavHierarchy:
    def test_empty_html_passes(self):
        r = check_nav_hierarchy("")
        assert r.passed is True

    def test_few_tabs_passes(self):
        html = '<nav>' + ''.join(f'<a data-tab="tab{i}">Tab {i}</a>' for i in range(5)) + '</nav>'
        r = check_nav_hierarchy(html)
        assert r.passed is True
        assert len(r.top_level_tabs) == 5

    def test_too_many_tabs_fails(self):
        # 15 tabs — exceeds MAX_TOP_LEVEL_TABS (12)
        html = '<nav>' + ''.join(f'<a data-tab="tab{i}">Tab {i}</a>' for i in range(15)) + '</nav>'
        r = check_nav_hierarchy(html)
        assert r.passed is False
        assert any("too_many_tabs" in v for v in r.violations)
        assert len(r.top_level_tabs) == 15

    def test_exactly_max_tabs_passes(self):
        html = '<nav>' + ''.join(f'<a data-tab="tab{i}">Tab {i}</a>' for i in range(MAX_TOP_LEVEL_TABS)) + '</nav>'
        r = check_nav_hierarchy(html)
        assert not any("too_many_tabs" in v for v in r.violations)

    def test_to_dict(self):
        r = check_nav_hierarchy('<nav><a data-tab="home">Home</a></nav>')
        d = r.to_dict()
        assert "passed" in d
        assert "violations" in d
        assert "top_level_tabs" in d

    def test_top_level_tabs_extracted(self):
        html = '<a data-tab="dashboard">Dash</a><a data-tab="logs">Logs</a>'
        r = check_nav_hierarchy(html)
        assert "dashboard" in r.top_level_tabs
        assert "logs" in r.top_level_tabs

    def test_fabricated_15_tab_html_fails(self):
        """15 data-tab attributes must trigger too_many_tabs violation."""
        tabs = "\n".join(f'<li><a data-tab="section{i}">Section {i}</a></li>' for i in range(15))
        html = f"<nav><ul>{tabs}</ul></nav>"
        r = check_nav_hierarchy(html)
        assert r.passed is False
        assert len(r.top_level_tabs) == 15


# ---- Integration: /api/nav/invariant endpoint ----

class TestNavInvariantEndpoint:
    def test_endpoint_returns_200(self, client):
        r = client.get("/api/nav/invariant")
        assert r.status_code == 200

    def test_endpoint_has_passed_field(self, client):
        r = client.get("/api/nav/invariant")
        data = r.json()
        assert "passed" in data

    def test_endpoint_has_violations_field(self, client):
        r = client.get("/api/nav/invariant")
        data = r.json()
        assert "violations" in data
        assert isinstance(data["violations"], list)

    def test_endpoint_has_top_level_tabs_field(self, client):
        r = client.get("/api/nav/invariant")
        data = r.json()
        assert "top_level_tabs" in data

    def test_current_index_html_passes(self, client):
        """The real index.html must pass nav invariants."""
        r = client.get("/api/nav/invariant")
        data = r.json()
        # passed may be True or None (if template missing), but must not be a clear fail
        if data["passed"] is False:
            pytest.fail(f"index.html fails nav invariants: {data['violations']}")


# ---- Startup wiring check ----

class TestNavStartupWiring:
    def test_lifespan_calls_nav_check(self):
        """Verify server._lifespan contains nav invariant check code."""
        import igris.web.server as srv
        import inspect
        src = inspect.getsource(srv._lifespan)
        assert "nav_invariants" in src or "check_nav_hierarchy" in src, (
            "Nav invariant check not found in _lifespan — startup wiring missing"
        )
