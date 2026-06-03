"""Code health monitor API routes (#521)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

logger = logging.getLogger("igris.api.code_health")

router = APIRouter(prefix="/api/code-health", tags=["code-health"])

# In-memory cache: set by meta_watchdog after each run
_last_report: Optional[Dict[str, Any]] = None


def update_code_health_cache(report: Any) -> None:
    """Called by meta_watchdog after each CodeHealthMonitor run."""
    global _last_report
    try:
        _last_report = {
            "findings": [
                {
                    "category": f.category,
                    "module_path": f.module_path,
                    "title": f.title,
                    "severity": f.severity,
                }
                for f in report.findings
            ],
            "issues_opened": list(report.issues_opened),
            "issues_skipped": report.issues_skipped,
            "errors": list(report.errors),
            "ran_at": report.ran_at,
        }
    except Exception as exc:
        logger.warning("Failed to cache code health report: %s", exc)


@router.get("/summary")
async def get_code_health_summary() -> Dict[str, Any]:
    """Return the latest CodeHealthMonitor report, or status=no_data if not yet run."""
    if _last_report is None:
        return {"status": "no_data"}
    return {"status": "ok", **_last_report}
