from __future__ import annotations

import json
from dataclasses import dataclass

from igris.agent.mission.shadow_integration import run_shadow_comparison
from igris.core.agent_reasoning_loop import AgentReasoningLoop, LoopResult


@dataclass
class _FakeLoopResult:
    loop_id: str = "loop-1"
    status: str = "finished"
    stop_reason: str = "finish"


def test_shadow_comparison_persists_record(tmp_path):
    fake_loop = _FakeLoopResult()
    record = run_shadow_comparison(
        user_input="Verifica endpoint health e test",
        loop_result=fake_loop,
        project_root=str(tmp_path),
        compare_with_current_loop=True,
        telemetry_enabled=True,
    )
    assert record["loop_decision"] == "completed"
    assert "mission_brain_decision" in record
    assert "evidence_depth_summary" in record
    record_path = record.get("shadow_record_path")
    assert record_path
    saved = json.loads((tmp_path / ".igris" / "mission_brain" / "shadow" / "loop-1.json").read_text(encoding="utf-8"))
    assert saved["loop_id"] == "loop-1"


def test_agent_loop_runs_shadow_only_when_enabled(monkeypatch, tmp_path):
    from igris.models import config as cfg_module

    loop = AgentReasoningLoop(project_root=str(tmp_path))
    result = LoopResult(goal="test", status="finished", stop_reason="finish")

    monkeypatch.setattr(cfg_module.CONFIG.mission_brain_integration, "enabled", True)
    monkeypatch.setattr(cfg_module.CONFIG.mission_brain_integration, "mode", "shadow")
    monkeypatch.setattr(cfg_module.CONFIG.mission_brain_integration, "compare_with_current_loop", True)
    monkeypatch.setattr(cfg_module.CONFIG.mission_brain_integration, "telemetry_enabled", True)

    loop._run_mission_brain_shadow(goal="Aggiungi test endpoint", result=result)
    assert result.mission_brain_shadow_mode is True
    assert isinstance(result.mission_brain_shadow_record, dict)
    assert "mission_brain_decision" in result.mission_brain_shadow_record


def test_agent_loop_does_not_run_shadow_when_disabled(monkeypatch, tmp_path):
    from igris.models import config as cfg_module

    loop = AgentReasoningLoop(project_root=str(tmp_path))
    result = LoopResult(goal="test", status="finished", stop_reason="finish")

    monkeypatch.setattr(cfg_module.CONFIG.mission_brain_integration, "enabled", False)
    monkeypatch.setattr(cfg_module.CONFIG.mission_brain_integration, "mode", "shadow")

    loop._run_mission_brain_shadow(goal="Aggiungi test endpoint", result=result)
    assert result.mission_brain_shadow_mode is False
    assert result.mission_brain_shadow_record is None

