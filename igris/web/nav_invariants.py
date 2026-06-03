"""
Nav Hierarchy Invariants — checks that the navigation structure in index.html
does not violate project invariants (issue #954).

Invariants:
1. Top-level tabs must not exceed MAX_TOP_LEVEL_TABS (default 12).
2. Every nav item must have a non-empty label.
3. Nav items must not be nested more than MAX_NAV_DEPTH levels.

Usage:
    from igris.web.nav_invariants import check_nav_hierarchy
    report = check_nav_hierarchy(html_text)
    if not report.passed:
        logger.warning("Nav violation: %s", report.violations)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

MAX_TOP_LEVEL_TABS = 12
MAX_NAV_DEPTH = 3


@dataclass
class NavInvariantReport:
    """Result of a nav hierarchy invariant check."""
    passed: bool
    violations: List[str] = field(default_factory=list)
    top_level_tabs: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "top_level_tabs": self.top_level_tabs,
        }


def check_nav_hierarchy(html: str) -> NavInvariantReport:
    """Parse nav structure from HTML and validate invariants.

    Uses simple regex-based parsing: looks for <nav> elements and counts
    top-level <a> / <li> / data-tab items. Does NOT require a full HTML parser.

    Args:
        html: Raw HTML text (e.g. index.html content).

    Returns:
        NavInvariantReport with passed status, violations, and tab names found.
    """
    if not html or not html.strip():
        return NavInvariantReport(passed=True, violations=[], top_level_tabs=[])

    violations: List[str] = []
    top_level_tabs: List[str] = []

    # Strategy 1: look for data-tab attributes (IGRIS UI pattern)
    data_tabs = re.findall(r'data-tab=["\']([^"\']+)["\']', html)
    if data_tabs:
        top_level_tabs = list(dict.fromkeys(data_tabs))  # deduplicated, order preserved

    # Strategy 2: look for nav > li or nav > a items
    if not top_level_tabs:
        nav_blocks = re.findall(r'<nav[^>]*>(.*?)</nav>', html, re.DOTALL | re.IGNORECASE)
        for nav_html in nav_blocks:
            links = re.findall(r'<a[^>]*>([^<]+)</a>', nav_html, re.IGNORECASE)
            top_level_tabs.extend(link.strip() for link in links if link.strip())
        top_level_tabs = list(dict.fromkeys(top_level_tabs))

    # Invariant 1: tab count
    if len(top_level_tabs) > MAX_TOP_LEVEL_TABS:
        violations.append(
            f"too_many_tabs: found {len(top_level_tabs)} top-level tabs "
            f"(max={MAX_TOP_LEVEL_TABS}): {top_level_tabs}"
        )

    # Invariant 2: empty labels
    empty_tabs = [t for t in top_level_tabs if not t.strip()]
    if empty_tabs:
        violations.append(f"empty_tab_labels: {len(empty_tabs)} tabs have empty labels")

    # Invariant 3: nav nesting depth (rough check via indentation of <nav> tags)
    nav_opens = [m.start() for m in re.finditer(r'<nav', html, re.IGNORECASE)]
    max_depth = _estimate_nav_depth(html, nav_opens)
    if max_depth > MAX_NAV_DEPTH:
        violations.append(
            f"excessive_nav_depth: estimated nesting depth {max_depth} "
            f"(max={MAX_NAV_DEPTH})"
        )

    passed = len(violations) == 0
    return NavInvariantReport(passed=passed, violations=violations, top_level_tabs=top_level_tabs)


def _estimate_nav_depth(html: str, nav_positions: list) -> int:
    """Estimate max nav nesting depth by counting overlapping <nav> open/close tags."""
    if not nav_positions:
        return 0
    depth = 0
    max_depth = 0
    for m in re.finditer(r'</?nav[> ]', html, re.IGNORECASE):
        if m.group().startswith("</"):
            depth = max(0, depth - 1)
        else:
            depth += 1
            max_depth = max(max_depth, depth)
    return max_depth
