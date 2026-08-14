"""Tests for #1312 Phase 2 — supervisor split (static method extraction).

Verifies that:
- supervisor_helpers.py module exists
- Extracted functions are importable from supervisor_helpers
- Static methods in SelfRepairSupervisor still work (delegation)
- Backward compatibility is maintained
- No behavior change
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def test_supervisor_helpers_module_exists():
    """supervisor_helpers.py module exists."""
    mod = REPO_ROOT / "igris" / "core" / "supervisor_helpers.py"
    assert mod.exists(), "igris/core/supervisor_helpers.py not found"


def test_supervisor_helpers_importable():
    """supervisor_helpers module is importable."""
    from igris.core import supervisor_helpers
    assert supervisor_helpers is not None


def test_self_repair_supervisor_still_importable():
    """SelfRepairSupervisor is still importable from self_repair_supervisor."""
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    assert SelfRepairSupervisor is not None


def test_static_methods_still_callable():
    """Static methods are still callable on the class."""
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    # _timestamp_to_iso should still work as a static method
    result = SelfRepairSupervisor._timestamp_to_iso(1700000000.0)
    assert isinstance(result, str)
    assert len(result) > 0


def test_timestamp_to_iso_handles_none():
    """_timestamp_to_iso handles None input."""
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    assert SelfRepairSupervisor._timestamp_to_iso(None) == ""


def test_goal_requires_backend_change():
    """_goal_requires_backend_change classifies correctly."""
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    assert SelfRepairSupervisor._goal_requires_backend_change("modify the API backend") is True
    assert SelfRepairSupervisor._goal_requires_backend_change("update docs") is False


def test_goal_requires_tests():
    """_goal_requires_tests classifies correctly."""
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    assert SelfRepairSupervisor._goal_requires_tests("add unit tests") is True


def test_goal_needs_preflight_decomposition():
    """_goal_needs_preflight_decomposition classifies correctly."""
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    # Short goal with few markers → False
    assert SelfRepairSupervisor._goal_needs_preflight_decomposition("fix typo") is False
    # Long goal → True
    long_goal = "a" * 250
    assert SelfRepairSupervisor._goal_needs_preflight_decomposition(long_goal) is True


def test_file_size_reduced():
    """supervisor_helpers.py should exist and contain extracted functions."""
    helpers = REPO_ROOT / "igris" / "core" / "supervisor_helpers.py"
    assert helpers.exists(), "supervisor_helpers.py not found"
    content = helpers.read_text(encoding="utf-8")
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    # Should have at least 200 lines (36 extracted functions)
    assert line_count >= 200, f"supervisor_helpers.py has only {line_count} lines (expected >= 200)"


def test_supervisor_helpers_has_functions():
    """supervisor_helpers.py has extracted functions."""
    from igris.core import supervisor_helpers
    # At least some functions should be defined
    funcs = [name for name in dir(supervisor_helpers) if not name.startswith("__")]
    assert len(funcs) > 0, "No functions found in supervisor_helpers"


# ------------------------------------------------------------------
# Phase 3 tests — mission planning extraction (#1356)
# ------------------------------------------------------------------

def test_supervisor_mission_planning_module_exists():
    """supervisor_mission_planning.py module exists."""
    mod = REPO_ROOT / "igris" / "core" / "supervisor_mission_planning.py"
    assert mod.exists(), "igris/core/supervisor_mission_planning.py not found"


def test_supervisor_mission_planning_importable():
    """supervisor_mission_planning module is importable."""
    from igris.core import supervisor_mission_planning
    assert supervisor_mission_planning is not None


def test_mission_planning_functions_importable():
    """Key functions are importable from supervisor_mission_planning."""
    from igris.core.supervisor_mission_planning import (
        build_mission_plan,
        mission_is_non_trivial,
        init_stage_statuses,
        set_stage_status,
        track_non_blocking_behavior,
        stage_is_already_satisfied,
        ui_stage_retry_goal,
        path_in_allowed_family,
        restore_ui_stage_scope,
        validate_new_stage_paths,
    )
    assert callable(build_mission_plan)
    assert callable(mission_is_non_trivial)
    assert callable(init_stage_statuses)
    assert callable(set_stage_status)
    assert callable(track_non_blocking_behavior)
    assert callable(stage_is_already_satisfied)
    assert callable(ui_stage_retry_goal)
    assert callable(path_in_allowed_family)
    assert callable(restore_ui_stage_scope)
    assert callable(validate_new_stage_paths)


def test_mission_is_non_trivial_simple_goal():
    """Simple goals are not non-trivial."""
    from igris.core.supervisor_mission_planning import mission_is_non_trivial
    from igris.core.supervisor_models import RankSupervisorConfig
    config = RankSupervisorConfig(goal="fix typo", targeted_tests=[])
    assert mission_is_non_trivial(config) is False


def test_build_mission_plan_single_stage():
    """Simple goals produce single-stage plan."""
    from igris.core.supervisor_mission_planning import build_mission_plan
    from igris.core.supervisor_models import RankSupervisorConfig
    config = RankSupervisorConfig(goal="fix typo", targeted_tests=[])
    plan = build_mission_plan(config)
    assert plan.mode == "single-stage"
    assert len(plan.stages) == 1
    assert plan.stages[0].stage_id == "single_stage_execution"


def test_build_mission_plan_staged():
    """Complex goals produce multi-stage plan."""
    from igris.core.supervisor_mission_planning import build_mission_plan
    from igris.core.supervisor_models import RankSupervisorConfig
    config = RankSupervisorConfig(
        goal="Add backend API endpoint, add UI dashboard visibility, add tests, update docs, add e2e workflow",
        targeted_tests=["tests/test_a.py", "tests/test_b.py"],
    )
    plan = build_mission_plan(config)
    assert plan.mode == "staged"
    assert len(plan.stages) > 1
    stage_ids = [s.stage_id for s in plan.stages]
    assert "understand_locate" in stage_ids
    assert "backend_api_change" in stage_ids
    assert "final_report" in stage_ids


def test_path_in_allowed_family():
    """path_in_allowed_family classifies paths correctly."""
    from igris.core.supervisor_mission_planning import path_in_allowed_family
    assert path_in_allowed_family("igris/core/foo.py", ["igris/core/"]) is True
    assert path_in_allowed_family("tests/test_foo.py", ["tests/"]) is True
    assert path_in_allowed_family("igris/web/server.py", ["igris/core/"]) is False
    assert path_in_allowed_family("README.md", ["README"]) is True
    assert path_in_allowed_family("pyproject.toml", ["pyproject.toml"]) is True


def test_validate_new_stage_paths_allowed():
    """validate_new_stage_paths returns True for allowed paths."""
    from igris.core.supervisor_mission_planning import validate_new_stage_paths
    from igris.core.supervisor_models import MissionStage
    stage = MissionStage(
        stage_id="test",
        goal="test",
        required=True,
        allowed_file_families=["tests/"],
        acceptance_criteria=[],
        validation=[],
        rollback_policy="",
        preserved_progress_policy="",
        failure_classification=[],
        repair_strategy="",
        report_entry="",
    )
    ok, invalid = validate_new_stage_paths(stage, set(), set(), ["tests/test_foo.py"])
    assert ok is True
    assert invalid == ""


def test_validate_new_stage_paths_blocked():
    """validate_new_stage_paths returns False for disallowed paths."""
    from igris.core.supervisor_mission_planning import validate_new_stage_paths
    from igris.core.supervisor_models import MissionStage
    stage = MissionStage(
        stage_id="test",
        goal="test",
        required=True,
        allowed_file_families=["tests/"],
        acceptance_criteria=[],
        validation=[],
        rollback_policy="",
        preserved_progress_policy="",
        failure_classification=[],
        repair_strategy="",
        report_entry="",
    )
    ok, invalid = validate_new_stage_paths(stage, set(), set(), ["igris/core/server.py"])
    assert ok is False
    assert "igris/core/server.py" in invalid


def test_ui_stage_retry_goal():
    """ui_stage_retry_goal constructs a retry prompt."""
    from igris.core.supervisor_mission_planning import ui_stage_retry_goal
    from igris.core.supervisor_models import MissionStage
    stage = MissionStage(
        stage_id="ui_dashboard_change",
        goal="Add UI visibility",
        required=False,
        allowed_file_families=["igris/web/templates/"],
        acceptance_criteria=["UI change visible"],
        validation=["smoke"],
        rollback_policy="restore",
        preserved_progress_policy="keep",
        failure_classification=[],
        repair_strategy="repair",
        report_entry="entry",
    )
    result = ui_stage_retry_goal(
        base_goal="Add rank dashboard",
        stage=stage,
        hard_forbidden={"igris/web/server.py"},
        retry_attempt=1,
        invalid_paths=["igris/core/foo.py"],
    )
    assert "Add rank dashboard" in result
    assert "igris/web/server.py" in result
    assert "Retry attempt 1" in result


def test_init_stage_statuses():
    """init_stage_statuses creates status entries for all stages."""
    from igris.core.supervisor_mission_planning import init_stage_statuses, build_mission_plan
    from igris.core.supervisor_models import RankSupervisorConfig
    config = RankSupervisorConfig(goal="fix typo", targeted_tests=[])
    plan = build_mission_plan(config)
    statuses = init_stage_statuses(plan)
    assert len(statuses) == len(plan.stages)
    for stage in plan.stages:
        assert stage.stage_id in statuses


def test_supervisor_file_size_decreased():
    """self_repair_supervisor.py should have decreased from Phase 2 baseline."""
    p = REPO_ROOT / "igris" / "core" / "self_repair_supervisor.py"
    content = p.read_text(encoding="utf-8")
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    # Phase 2 left it at 6,013 lines; Phase 3 should have reduced it
    assert line_count < 6013, f"self_repair_supervisor.py is {line_count} lines (expected < 6013 after Phase 3)"


def test_supervisor_mission_planning_file_size():
    """supervisor_mission_planning.py should have substantial content."""
    p = REPO_ROOT / "igris" / "core" / "supervisor_mission_planning.py"
    content = p.read_text(encoding="utf-8")
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    assert line_count >= 200, f"supervisor_mission_planning.py has only {line_count} lines (expected >= 200)"


def test_delegation_wrappers_preserve_behavior():
    """SelfRepairSupervisor methods delegate correctly to extracted functions."""
    from igris.core.self_repair_supervisor import SelfRepairSupervisor
    from igris.core.supervisor_models import RankSupervisorConfig
    config = RankSupervisorConfig(goal="fix typo", targeted_tests=[])
    # _build_mission_plan should still work via delegation
    plan = SelfRepairSupervisor._build_mission_plan(None, config)
    assert plan is not None
    assert plan.mode == "single-stage"
