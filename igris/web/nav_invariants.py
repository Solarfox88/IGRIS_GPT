"""Nav/tab hierarchy invariants for Control Room UI.
Ensures the navigation structure doesn't regress silently.
"""
from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass

@dataclass
class NavReport:
    passed: bool
    violations: list[str]
    top_level_tabs: list[str]
    grouped_items: int

MAX_TOP_LEVEL_TABS = 10  # more than this is a flat nav regression
# Current template has 7; buffer of 3 for planned additions before requiring grouping

def extract_nav_structure(html: str) -> tuple[list[str], int]:
    """Extract top-level nav tabs and count of grouped/nested items."""
    # Look for data-tab attribute on elements (top-level nav buttons)
    top_level = re.findall(
        r'data-tab=["\']([^"\']+)["\']',
        html
    )

    # Fallback: role="tab" with aria-label
    if not top_level:
        top_level = re.findall(
            r'role=["\']tab["\'][^>]*aria-label=["\']([^"\']+)["\']',
            html
        )
    if not top_level:
        top_level = re.findall(
            r'aria-label=["\']([^"\']+)["\'][^>]*role=["\']tab["\']',
            html
        )

    # Count grouped/nested items (sub-tabs, dropdowns, nav-groups)
    grouped = len(re.findall(r'(?:dropdown-item|sub-tab|nav-group|data-subtab)', html))

    return [t.strip() for t in top_level if t.strip()], grouped


def check_nav_hierarchy(html: str) -> NavReport:
    """Check nav HTML against hierarchy invariants."""
    top_level, grouped = extract_nav_structure(html)
    violations = []

    if len(top_level) > MAX_TOP_LEVEL_TABS:
        violations.append(
            f"Too many top-level tabs: {len(top_level)} (max {MAX_TOP_LEVEL_TABS}). "
            f"Group advanced tabs under sections."
        )

    return NavReport(
        passed=len(violations) == 0,
        violations=violations,
        top_level_tabs=top_level,
        grouped_items=grouped,
    )
