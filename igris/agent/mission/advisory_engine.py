"""Conservative advisory facade for gradual consolidation (#1108).

This module is intentionally behavior-preserving: it delegates to existing
advisory modules without changing their semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from igris.agent.mission.advisory_rollout import (
    AdvisoryRolloutConfig,
    enrich_cycle_with_advisory,
    enrich_report_with_advisory,
)
from igris.agent.mission.broader_advisory import (
    BroaderAdvisoryConfig,
    aggregate_broader_cycles,
    compute_monitoring_metrics,
    enrich_cycle_broader,
    enrich_report_broader,
)
from igris.agent.mission.selected_advisory import (
    SelectedAdvisoryConfig,
    aggregate_selected_cycles,
    enrich_cycle_selected,
    enrich_report_selected,
    strip_selected_advisory,
)

AdvisoryMode = Literal["rollout", "broader", "selected"]


@dataclass(frozen=True)
class AdvisoryEngineConfig:
    mode: AdvisoryMode = "selected"
    rollout: AdvisoryRolloutConfig | None = None
    broader: BroaderAdvisoryConfig | None = None
    selected: SelectedAdvisoryConfig | None = None


class AdvisoryEngine:
    """Small dispatch layer over existing advisory modules."""

    def __init__(self, config: AdvisoryEngineConfig) -> None:
        self.config = config

    def enrich_report(
        self,
        report: Dict[str, Any],
        *,
        run_status: Optional[str] = None,
        goal_status: Optional[str] = None,
        cycle: Optional[Dict[str, Any]] = None,
        report_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        mode = self.config.mode
        if mode == "rollout":
            return enrich_report_with_advisory(
                report,
                run_status=run_status,
                goal_status=goal_status,
                cycle=cycle,
                advisory_config=self.config.rollout or AdvisoryRolloutConfig(),
            )
        if mode == "broader":
            return enrich_report_broader(
                report,
                run_status=run_status,
                goal_status=goal_status,
                cycle=cycle,
                config=self.config.broader or BroaderAdvisoryConfig(),
            )
        return enrich_report_selected(
            report,
            run_status=run_status,
            goal_status=goal_status,
            cycle=cycle,
            report_type=report_type,
            config=self.config.selected or SelectedAdvisoryConfig(),
        )

    def enrich_cycle(self, cycle: Dict[str, Any], *, report_type: Optional[str] = None) -> Dict[str, Any]:
        mode = self.config.mode
        if mode == "rollout":
            return enrich_cycle_with_advisory(
                cycle,
                advisory_config=self.config.rollout or AdvisoryRolloutConfig(),
            )
        if mode == "broader":
            return enrich_cycle_broader(cycle, config=self.config.broader or BroaderAdvisoryConfig())
        return enrich_cycle_selected(
            cycle,
            report_type=report_type,
            config=self.config.selected or SelectedAdvisoryConfig(),
        )

    def aggregate(self, cycles: List[Dict[str, Any]], *, report_type: str = "diagnostic") -> Dict[str, Any]:
        mode = self.config.mode
        if mode == "broader":
            return aggregate_broader_cycles(cycles, config=self.config.broader or BroaderAdvisoryConfig())
        if mode == "selected":
            return aggregate_selected_cycles(
                cycles,
                config=self.config.selected or SelectedAdvisoryConfig(),
                report_type=report_type,
            )
        return {
            "total_cycles": len(cycles),
            "note": "rollout mode has no aggregate helper; use per-cycle/report enrichment",
        }

    def monitoring_metrics(self, cycles: List[Dict[str, Any]]) -> Dict[str, Any]:
        if self.config.mode != "broader":
            return {"total_cycles": len(cycles), "note": "monitoring metrics supported in broader mode only"}
        return compute_monitoring_metrics(cycles, config=self.config.broader or BroaderAdvisoryConfig())

    @staticmethod
    def strip(report: Dict[str, Any]) -> Dict[str, Any]:
        return strip_selected_advisory(report)
