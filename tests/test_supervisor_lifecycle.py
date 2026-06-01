from __future__ import annotations

from dataclasses import dataclass

from igris.core.supervisor_lifecycle import (
    configure_run_tracking,
    is_terminal_status,
    transition_run_status,
)
from igris.core.supervisor_run_store import SupervisorRunStore


@dataclass
class _Cfg:
    goal: str = "g"
    max_repair_cycles: int = 2
    max_api_escalations_per_run: int = 1
    max_api_budget_usd: float = 1.234567


@dataclass
class _Run:
    run_id: str = "r1"
    status: str = "running"
    audit_resolver: object | None = None
    update_hook: object | None = None
    max_repair_cycles: int = 0
    max_api_escalations_per_run: int = 0
    max_api_budget_usd: float = 0.0
    goal: str = ""


def test_configure_run_tracking_sets_fields(tmp_path):
    run = _Run()
    store = SupervisorRunStore(project_root=str(tmp_path), strict_transitions=True)

    def _audit(_):
        return None

    def _hook(_):
        return None

    configure_run_tracking(
        run=run,
        config=_Cfg(),
        run_store=store,
        audit_resolver=_audit,
        update_hook=_hook,
    )
    assert run.audit_resolver is _audit
    assert run.update_hook is _hook
    assert run.max_repair_cycles == 2
    assert run.max_api_escalations_per_run == 1
    assert run.max_api_budget_usd == round(1.234567, 6)
    assert run.goal == "g"


def test_transition_run_status_preserves_valid_transition(tmp_path):
    run = _Run()
    store = SupervisorRunStore(project_root=str(tmp_path), strict_transitions=True)
    store.register(run)
    transition_run_status(run=run, new_status="cancelling", reason="x", run_store=store)
    assert run.status == "cancelling"


def test_is_terminal_status():
    assert is_terminal_status("completed") is True
    assert is_terminal_status("blocked") is True
    assert is_terminal_status("running") is False
