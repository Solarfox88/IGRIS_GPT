from __future__ import annotations

from igris.agent.mission.advisory_engine import AdvisoryEngine, AdvisoryEngineConfig
from igris.agent.mission.broader_advisory import make_broader_monitoring_config
from igris.agent.mission.selected_advisory import make_selected_activation_config


def _sample_cycle() -> dict:
    return {
        "cycle_id": "c1",
        "current_loop_decision": "failed",
        "mission_brain_decision": "partial",
    }


def test_selected_mode_delegates_and_is_advisory_only() -> None:
    cfg = AdvisoryEngineConfig(mode="selected", selected=make_selected_activation_config(include_blocked=True))
    engine = AdvisoryEngine(cfg)
    out = engine.enrich_cycle(_sample_cycle(), report_type="diagnostic")
    rec = out.get("recovery_recommendation")
    assert rec is not None
    assert rec.get("advisory_only") is True
    assert rec.get("auto_executable") is False


def test_broader_mode_metrics_and_enrichment() -> None:
    cfg = AdvisoryEngineConfig(mode="broader", broader=make_broader_monitoring_config(include_blocked=True))
    engine = AdvisoryEngine(cfg)
    cycles = [_sample_cycle(), {"cycle_id": "c2", "current_loop_decision": "blocked", "mission_brain_decision": "partial"}]
    metrics = engine.monitoring_metrics(cycles)
    assert metrics["total_cycles"] == 2
    enriched = engine.enrich_cycle(cycles[0])
    assert isinstance(enriched, dict)


def test_rollout_mode_no_crash_and_aggregate_note() -> None:
    engine = AdvisoryEngine(AdvisoryEngineConfig(mode="rollout"))
    out = engine.enrich_report({}, run_status="failed", goal_status="partial")
    assert isinstance(out, dict)
    agg = engine.aggregate([_sample_cycle()])
    assert "note" in agg
