"""
Nav Invariant API route — returns current nav hierarchy check result (issue #954).

GET /api/nav/invariant — machine-readable nav hierarchy check for CI/monitoring.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter(prefix="/api/nav", tags=["nav"])

_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "web" / "templates" / "index.html"


@router.get("/invariant")
def nav_invariant_check() -> Dict[str, Any]:
    """Return the current nav hierarchy invariant check result."""
    try:
        from igris.web.nav_invariants import check_nav_hierarchy
        html = _TEMPLATE_PATH.read_text(encoding="utf-8") if _TEMPLATE_PATH.exists() else ""
        report = check_nav_hierarchy(html)
        return report.to_dict()
    except Exception as e:
        return {"passed": None, "error": str(e), "violations": [], "top_level_tabs": []}
