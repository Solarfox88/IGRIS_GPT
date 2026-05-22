from types import SimpleNamespace
from unittest.mock import patch

from igris.core.delivery_workflow import CIStatus, DeliveryWorkflow


def _cp(code=0, out="[]"):
    return SimpleNamespace(returncode=code, stdout=out)


def test_create_branch_naming(tmp_path):
    with patch("igris.core.delivery_workflow.subprocess.run") as run:
        b = DeliveryWorkflow(str(tmp_path)).create_mission_branch("abcdef1234")
        assert b == "igris/mission-abcdef12"
        run.assert_called()


def test_commit_staged_atomic(tmp_path):
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return _cp(0, "")
    with patch("igris.core.delivery_workflow.subprocess.run", side_effect=fake_run):
        ok = DeliveryWorkflow(str(tmp_path)).commit_staged("m", ["a.py", "b.py"])
        assert ok
        assert calls[0][:2] == ["git", "add"]


def test_open_pr_with_closes_issues(tmp_path):
    with patch("igris.core.delivery_workflow.subprocess.run", return_value=_cp(0, "url\n")) as run:
        DeliveryWorkflow(str(tmp_path)).open_pr("b", "t", "body", [44, 48])
        assert "Closes #44" in run.call_args.args[0][6]


def test_wait_for_ci_green(tmp_path):
    checks='[{"name":"ci","status":"completed","conclusion":"success"}]'
    with patch("igris.core.delivery_workflow.subprocess.run", return_value=_cp(0, checks)):
        st=DeliveryWorkflow(str(tmp_path)).wait_for_ci(1,timeout=1,poll=0)
        assert st.status=="green"


def test_wait_for_ci_red(tmp_path):
    checks='[{"name":"ci","status":"completed","conclusion":"failure"}]'
    with patch("igris.core.delivery_workflow.subprocess.run", return_value=_cp(0, checks)):
        st=DeliveryWorkflow(str(tmp_path)).wait_for_ci(1,timeout=1,poll=0)
        assert st.status=="red" and st.failed_jobs==["ci"]


def test_wait_for_ci_timeout(tmp_path):
    with patch("igris.core.delivery_workflow.subprocess.run", return_value=_cp(1, "")):
        st=DeliveryWorkflow(str(tmp_path)).wait_for_ci(1,timeout=0,poll=0)
        assert st.status=="timeout"


def test_fix_ci_loop_success_writes_lesson(tmp_path):
    dw=DeliveryWorkflow(str(tmp_path))
    with patch.object(dw,"wait_for_ci",return_value=CIStatus("green",[],"")), patch("igris.core.memory_graph.MemoryGraph") as mg:
        assert dw.fix_ci_loop(1)
        mg.return_value.add_node.assert_called()


def test_fix_ci_loop_failure_runs_detectors(tmp_path):
    dw=DeliveryWorkflow(str(tmp_path))
    with patch.object(dw,"wait_for_ci",return_value=CIStatus("red",["x"],"")), patch("igris.core.smw_weak_signals.run_all_detectors", return_value={}) as r, patch("igris.core.smw_weak_signals.save_weak_signals"):
        assert dw.fix_ci_loop(1,max_attempts=1) is False
        r.assert_called_once()


def test_fix_ci_loop_anti_repeat(tmp_path):
    dw=DeliveryWorkflow(str(tmp_path))
    with patch.object(dw,"wait_for_ci",return_value=CIStatus("red",["x"],"")):
        dw.fix_ci_loop(3,max_attempts=1)
        assert dw._fix_attempts["3"]==1


def test_verify_and_unsaturate_calls_graph(tmp_path):
    with patch("igris.core.memory_graph.MemoryGraph") as mg:
        DeliveryWorkflow(str(tmp_path)).verify_and_unsaturate("family")
        mg.return_value.unsaturate_family.assert_called_once_with("family")


def test_update_issue(tmp_path):
    with patch("igris.core.delivery_workflow.subprocess.run", return_value=_cp(0, "")):
        assert DeliveryWorkflow(str(tmp_path)).update_issue(1, "c")


def test_merge_pr(tmp_path):
    with patch("igris.core.delivery_workflow.subprocess.run", return_value=_cp(0, "")) as run:
        assert DeliveryWorkflow(str(tmp_path)).merge_pr(1)
        assert "--squash" in run.call_args.args[0]
