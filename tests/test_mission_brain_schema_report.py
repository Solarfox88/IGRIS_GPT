from pathlib import Path

from igris.agent.mission import Mission, load_mission_report, save_mission_report


def test_mission_schema_roundtrip_and_report(tmp_path: Path):
    mission = Mission(
        project="igrisgpt",
        user_input="Implement mission schema and save report",
        intent_summary="Create mission object",
    )
    mission.status = "in_progress"
    mission.quality_gate_passed = True
    path = save_mission_report(mission, project_root=str(tmp_path))
    assert path.exists()

    loaded = load_mission_report(mission.id, project_root=str(tmp_path))
    assert loaded is not None
    assert loaded.id == mission.id
    assert loaded.project == "igrisgpt"
    assert loaded.user_input == mission.user_input
    assert loaded.quality_gate_passed is True

