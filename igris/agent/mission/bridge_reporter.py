"""Bridge Reporter — EPIC #880 (#882).

Enriches execution reports with Goal/Run Status Bridge diagnostics.

Design constraints:
  - ADDITIVE ONLY: never modifies or removes existing report fields.
  - NON-BLOCKING: bridge computation errors are caught silently;
    the original report is returned unchanged on any failure.
  - Feature-flagged: enrichment only happens when BridgeConfig.should_emit is True.
  - The bridge diagnostic section is namespaced under "bridge_diagnostics".
  - Loop decisions are NEVER derived from bridge output.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from igris.agent.mission.bridge_config import DEFAULT_BRIDGE_CONFIG, BridgeConfig
from igris.agent.mission.status_bridge import COMBINED_STATUSES, NEXT_ACTIONS, bridge

logger = logging.getLogger(__name__)


def enrich_report(
    report: Dict[str, Any],
    *,
    run_status: Optional[str] = None,
    goal_status: Optional[str] = None,
    config: BridgeConfig = DEFAULT_BRIDGE_CONFIG,
) -> Dict[str, Any]:
    """Enrich an execution report with bridge diagnostics (additive, non-blocking).

    Returns the original report unchanged if config.should_emit is False,
    or if bridge computation fails for any reason.
    """
    if not config.should_emit:
        return report

    t0 = time.monotonic()
    try:
        if run_status is None:
            run_status = (
                report.get("run_status")
                or report.get("current_loop_decision")
                or report.get("outcome")
                or ""
            )
        if goal_status is None:
            goal_status = (
                report.get("goal_status")
                or report.get("mission_brain_decision")
                or ""
            )

        bridge_result = bridge(run_status, goal_status)
        elapsed_ms = round((time.monotonic() - t0) * 1000, 2)

        if elapsed_ms > config.max_latency_budget_ms:
            if config.log_enabled:
                logger.warning(
                    "bridge_reporter: latency budget exceeded (%.1fms > %dms), skipping",
                    elapsed_ms, config.max_latency_budget_ms,
                )
            return report

        diagnostics = {
            "bridge_diagnostics": {
                "combined_status": bridge_result["combined_status"],
                "next_action_recommendation": bridge_result["next_action_recommendation"],
                "run_status_normalized": bridge_result["run_status"],
                "goal_status_normalized": bridge_result["goal_status"],
                "rationale": bridge_result["rationale"],
                "bridge_version": "v1",
                "rollout_mode": config.rollout_mode,
                "computation_ms": elapsed_ms,
                "is_gate": False,
                "affects_loop_decision": False,
            }
        }

        if config.log_enabled:
            logger.info(
                "bridge_reporter: combined=%s next=%s (%.1fms)",
                bridge_result["combined_status"],
                bridge_result["next_action_recommendation"],
                elapsed_ms,
            )

        return {**report, **diagnostics}

    except Exception as exc:  # noqa: BLE001
        if config.log_enabled:
            logger.warning("bridge_reporter: error enriching report: %s", exc)
        return report


def enrich_report_from_cycle(
    report: Dict[str, Any],
    cycle: Dict[str, Any],
    *,
    config: BridgeConfig = DEFAULT_BRIDGE_CONFIG,
) -> Dict[str, Any]:
    """Convenience wrapper: read run/goal status from a cycle record."""
    return enrich_report(
        report,
        run_status=cycle.get("current_loop_decision", ""),
        goal_status=cycle.get("mission_brain_decision", ""),
        config=config,
    )


def strip_bridge_diagnostics(report: Dict[str, Any]) -> Dict[str, Any]:
    """Remove bridge_diagnostics from a report (rollback utility)."""
    return {k: v for k, v in report.items() if k != "bridge_diagnostics"}


def is_enriched(report: Dict[str, Any]) -> bool:
    """Return True if the report contains bridge diagnostics."""
    return "bridge_diagnostics" in report


def validate_bridge_diagnostics(diagnostics: Dict[str, Any]) -> bool:
    """Validate that a bridge_diagnostics block is well-formed."""
    required = {
        "combined_status", "next_action_recommendation",
        "run_status_normalized", "goal_status_normalized",
        "is_gate", "affects_loop_decision",
    }
    missing = required - set(diagnostics.keys())
    if missing:
        raise ValueError(f"bridge_diagnostics missing fields: {missing}")
    if diagnostics["combined_status"] not in COMBINED_STATUSES:
        raise ValueError(f"invalid combined_status: {diagnostics['combined_status']!r}")
    if diagnostics["next_action_recommendation"] not in NEXT_ACTIONS:
        raise ValueError(f"invalid next_action_recommendation: {diagnostics['next_action_recommendation']!r}")
    if diagnostics["is_gate"] is not False:
        raise ValueError("bridge_diagnostics.is_gate must always be False")
    if diagnostics["affects_loop_decision"] is not False:
        raise ValueError("bridge_diagnostics.affects_loop_decision must always be False")
    return True
