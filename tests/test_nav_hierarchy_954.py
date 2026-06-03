"""Tests for nav/tab hierarchy CI invariant — issue #954."""
from __future__ import annotations
import pytest
from pathlib import Path
from igris.web.nav_invariants import (
    check_nav_hierarchy,
    extract_nav_structure,
    MAX_TOP_LEVEL_TABS,
)

# Path to the real template
INDEX_HTML_PATH = Path(__file__).parent.parent / "igris" / "web" / "templates" / "index.html"


# ---------------------------------------------------------------------------
# Real template
# ---------------------------------------------------------------------------

def test_real_index_html_passes_invariant():
    """The actual index.html must pass the nav hierarchy invariant."""
    assert INDEX_HTML_PATH.exists(), f"index.html not found at {INDEX_HTML_PATH}"
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    report = check_nav_hierarchy(html)
    assert report.passed, (
        f"index.html violates nav invariant: {report.violations}\n"
        f"Top-level tabs found: {report.top_level_tabs}"
    )


def test_real_index_html_extract_non_empty():
    """extract_nav_structure returns a non-empty tab list for the real template."""
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    tabs, grouped = extract_nav_structure(html)
    assert len(tabs) > 0, "No top-level tabs detected in index.html"


def test_real_index_html_has_expected_tabs():
    """Real template has the 7 known top-level tabs."""
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    tabs, _ = extract_nav_structure(html)
    expected = {"dashboard", "code", "tasks", "terminal", "memory", "safety", "advanced"}
    found = set(tabs)
    assert expected.issubset(found), f"Missing expected tabs. Found: {found}"


# ---------------------------------------------------------------------------
# Fabricated HTML — passing cases
# ---------------------------------------------------------------------------

def _make_nav_html(tab_names: list[str], include_grouped: bool = False) -> str:
    tabs = "\n".join(
        f'<button data-tab="{name}" role="tab" aria-label="{name}">{name}</button>'
        for name in tab_names
    )
    grouped = ""
    if include_grouped:
        grouped = """
        <div class="sub-tab-bar">
          <button class="sub-tab" data-subtab="sub1">Sub1</button>
          <button class="sub-tab" data-subtab="sub2">Sub2</button>
          <button class="sub-tab" data-subtab="sub3">Sub3</button>
          <div class="dropdown-item">Advanced Option</div>
        </div>
        """
    return f"<nav>{tabs}{grouped}</nav>"


def test_few_top_level_tabs_passes():
    """5 top-level tabs is well within the limit."""
    html = _make_nav_html(["home", "tasks", "code", "memory", "settings"])
    report = check_nav_hierarchy(html)
    assert report.passed
    assert len(report.violations) == 0


def test_exactly_max_tabs_passes():
    """Exactly MAX_TOP_LEVEL_TABS tabs must pass."""
    names = [f"tab{i}" for i in range(MAX_TOP_LEVEL_TABS)]
    html = _make_nav_html(names)
    report = check_nav_hierarchy(html)
    assert report.passed, report.violations


def test_grouped_items_counted():
    """Grouped/nested items are detected and counted."""
    html = _make_nav_html(["dashboard", "code", "tasks"], include_grouped=True)
    _, grouped = extract_nav_structure(html)
    assert grouped > 0  # sub-tabs and dropdown-item detected


def test_many_total_items_with_grouping_passes():
    """Even with many total items, if top-level is within limit it passes."""
    html = _make_nav_html(["dashboard", "code", "tasks"], include_grouped=True)
    report = check_nav_hierarchy(html)
    assert report.passed


# ---------------------------------------------------------------------------
# Fabricated HTML — failing cases
# ---------------------------------------------------------------------------

def test_too_many_top_level_tabs_fails():
    """More than MAX_TOP_LEVEL_TABS flat top-level tabs must fail."""
    names = [f"tab{i}" for i in range(MAX_TOP_LEVEL_TABS + 1)]
    html = _make_nav_html(names)
    report = check_nav_hierarchy(html)
    assert not report.passed
    assert len(report.violations) >= 1
    assert str(MAX_TOP_LEVEL_TABS + 1) in report.violations[0]


def test_far_too_many_tabs_fails():
    """20 flat top-level tabs clearly violates the invariant."""
    names = [f"tab{i}" for i in range(20)]
    html = _make_nav_html(names)
    report = check_nav_hierarchy(html)
    assert not report.passed
    assert any("20" in v for v in report.violations)
