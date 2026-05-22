from igris.core.mission_controller import ControlledMission, MissionController
from igris.core.work_session import DeliveryReport, WorkPhase, WorkSession
from unittest.mock import patch


def _report(session_id="s1"):
    return DeliveryReport(session_id, "goal", ["a.py"], "diff", "tests", "green", "http://pr", 1, "", [], True, "run1", "", 0, {})


def test_phases_advance_correctly():
    ws = WorkSession.create("goal")
    ws.advance_phase(WorkPhase.PLAN)
    ws.advance_phase(WorkPhase.ACT)
    assert len(ws.phases) == 2
    assert ws.phases[0].completed_at is not None


def test_remember_writes_to_graph(tmp_path):
    ws = WorkSession.create("goal").complete_deliver(_report())
    with patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
        ws.remember(str(tmp_path))
        assert mg_cls.return_value.add_node.call_count >= 2


def test_delivery_report_aligns_with_pr_review_request():
    ws = WorkSession.create("goal").complete_deliver(_report())
    req = ws.to_pr_review_request()
    assert set(req.keys()) == {"pr_number", "pr_diff", "changed_files", "ci_passed", "run_id", "last_failure_class", "repair_cycles_used", "capability_signals"}


def test_work_session_id_in_controlled_mission():
    m = ControlledMission(goal="g", work_session_id="ws1")
    d = m.to_dict()
    assert d["work_session_id"] == "ws1"
    m2 = ControlledMission.from_dict(d)
    assert m2.work_session_id == "ws1"


def test_generate_final_report_includes_delivery_report(tmp_path):
    ctrl = MissionController(project_root=str(tmp_path))
    m = ctrl.create_mission("t", "g")
    ctrl.add_artifact(m.id, "file", "x.py", "x")
    report = ctrl.generate_final_report(m.id)
    assert "delivery_report" in report


def test_work_session_status_delivered_after_complete_deliver():
    ws = WorkSession.create("goal")
    ws.complete_deliver(_report())
    assert ws.status == "delivered"


def test_world_state_snapshot_written_on_remember(tmp_path):
    ws = WorkSession.create("goal").complete_deliver(_report())
    with patch("igris.core.memory_graph.MemoryGraph") as mg_cls:
        ws.remember(str(tmp_path))
        assert any(c.args[0] == "world_state_snapshot" for c in mg_cls.return_value.add_node.call_args_list)


def test_remember_graph_unavailable_no_raise(tmp_path):
    ws = WorkSession.create("goal").complete_deliver(_report())
    with patch("igris.core.memory_graph.MemoryGraph", side_effect=RuntimeError()):
        ws.remember(str(tmp_path))


def test_to_dict_round_trip():
    ws = WorkSession.create("goal", mission_id="m1")
    data = ws.to_dict()
    assert data["mission_id"] == "m1"


def test_pr_review_request_fields_complete():
    ws = WorkSession.create("goal").complete_deliver(_report())
    assert len(ws.to_pr_review_request()) == 8
