from types import SimpleNamespace

from igris.core.supervisor_repair_cycle import (
    collect_repair_diagnostics,
    update_same_failure_tracking,
)


def test_collect_repair_diagnostics_extracts_mbop_and_failure_context() -> None:
    events = [
        SimpleNamespace(phase="rank_reasoning", status="failure", detail="reasoning blocked", data={"stop_reason": "max_steps"}),
        SimpleNamespace(phase="full_pytest", status="failure", detail="3 failed", data={}),
        SimpleNamespace(phase="repair_strategy_decision", status="proceed", detail="", data={"task_type": "code_reasoning", "profile": "mini", "notes": "try scoped fix"}),
        SimpleNamespace(phase="mbop_phase9_quality_gate", status="failure", detail="stub detected", data={"stub_patterns": ["TODO", "pass"]}),
        SimpleNamespace(phase="mbop_phase10_satisfaction_gate", status="failure", detail="", data={"criteria_missing": ["ac1"], "criteria_covered": ["ac2"], "criteria_checked": ["ac1", "ac2"]}),
        SimpleNamespace(phase="mbop_phase11_post_task_eval", status="success", detail="", data={"lessons": ["lesson"], "failure_class": "pytest_failure"}),
        SimpleNamespace(phase="mbop_phase12_next_step", status="success", detail="", data={"suggestions": ["run targeted test"]}),
        SimpleNamespace(phase="diff_stat", status="success", detail="", data={"files_modified": ["a.py", "b.py"]}),
    ]
    run = SimpleNamespace(repair_cycles_used=2, same_failure_count=1, events=events)

    diag = collect_repair_diagnostics(run)

    assert diag["repair_cycles_used"] == 2
    assert diag["same_failure_count"] == 1
    assert diag["previous_stop_reason"] == "max_steps"
    assert diag["previous_pytest_failure"] == "3 failed"
    assert diag["previous_files_modified"] == ["a.py", "b.py"]
    assert diag["previous_quality_gate_status"] == "failure"
    assert diag["previous_satisfaction_missing_acs"] == ["ac1"]
    assert diag["mbop_lessons"] == ["lesson"]
    assert diag["mbop_recommended_strategy"] == "pytest_failure"
    assert diag["mbop_next_step"] == ["run targeted test"]


def test_update_same_failure_tracking_is_behavior_preserving() -> None:
    run = SimpleNamespace(same_failure_count=0, last_repair_failure="")

    count = update_same_failure_tracking(run, "pytest_failure")
    assert count == 0
    assert run.same_failure_count == 0
    assert run.last_repair_failure == "pytest_failure"

    count = update_same_failure_tracking(run, "pytest_failure")
    assert count == 1
    assert run.same_failure_count == 1

    count = update_same_failure_tracking(run, "wrong_file_edit")
    assert count == 0
    assert run.same_failure_count == 0
    assert run.last_repair_failure == "wrong_file_edit"
