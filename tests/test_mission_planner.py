"""Tests for igris.core.mission_planner."""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path

from igris.core import mission_planner
from igris.core.mission_planner import (
    Mission,
    PlanStep,
    generate_plan,
    get_mission_graph,
    list_missions,
    load_mission,
    materialize_tasks,
    plan_mission,
    save_mission,
)
from igris.core.task_engine import TaskEngine


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Temporary project directory with .igris structure."""
    (tmp_path / ".igris" / "missions").mkdir(parents=True)
    (tmp_path / ".igris" / "tasks").mkdir(parents=True)
    (tmp_path / ".igris" / "timeline").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def task_engine(project_dir: Path) -> TaskEngine:
    return TaskEngine(runtime_root=project_dir / ".igris")


# ---- Mission CRUD ----


class TestMissionCRUD:
    def test_create_and_load(self, project_dir: Path) -> None:
        m = Mission(title="Test mission", description="Do something")
        save_mission(m, project_root=str(project_dir))
        loaded = load_mission(m.id, project_root=str(project_dir))
        assert loaded is not None
        assert loaded.title == "Test mission"
        assert loaded.status == "created"

    def test_load_not_found(self, project_dir: Path) -> None:
        assert load_mission("nonexistent", project_root=str(project_dir)) is None

    def test_list_missions(self, project_dir: Path) -> None:
        m1 = Mission(title="Mission A")
        m2 = Mission(title="Mission B")
        save_mission(m1, project_root=str(project_dir))
        save_mission(m2, project_root=str(project_dir))
        missions = list_missions(project_root=str(project_dir))
        assert len(missions) >= 2
        titles = {m.title for m in missions}
        assert "Mission A" in titles
        assert "Mission B" in titles

    def test_mission_to_dict(self) -> None:
        m = Mission(title="X", description="Y")
        d = m.to_dict()
        assert d["title"] == "X"
        assert d["description"] == "Y"
        assert d["step_count"] == 0
        assert "id" in d

    def test_mission_from_dict(self) -> None:
        data = {"id": "abc", "title": "T", "description": "D", "status": "planned"}
        m = Mission.from_dict(data)
        assert m.id == "abc"
        assert m.status == "planned"


# ---- Plan generation ----


class TestPlanGeneration:
    def test_generate_plan_numbered_steps(self) -> None:
        m = Mission(title="Multi-step", description="1. Analyze code\n2. Implement feature\n3. Write tests")
        steps = generate_plan(m)
        assert len(steps) == 3
        assert steps[0].title == "Analyze code"
        assert steps[0].family == "analyze"
        assert steps[1].family == "code"
        assert steps[2].family == "test"

    def test_generate_plan_bulleted_steps(self) -> None:
        m = Mission(title="Bullet", description="- Fix bug\n- Test the fix\n- Document changes")
        steps = generate_plan(m)
        assert len(steps) == 3
        assert steps[0].family == "fix"

    def test_generate_plan_single_description(self) -> None:
        m = Mission(title="Simple task", description="Implement a new feature for the dashboard")
        steps = generate_plan(m)
        assert len(steps) == 3  # analyze, implement, test
        assert steps[0].family == "analyze"
        assert steps[2].family == "test"

    def test_plan_steps_have_success_criteria(self) -> None:
        m = Mission(title="Test", description="1. Analyze\n2. Implement\n3. Test")
        steps = generate_plan(m)
        for step in steps:
            assert len(step.success_criteria) > 0

    def test_plan_steps_have_dependencies(self) -> None:
        m = Mission(title="Deps", description="1. First\n2. Second\n3. Third")
        steps = generate_plan(m)
        assert steps[0].dependencies == []
        assert steps[1].dependencies == [steps[0].id]
        assert steps[2].dependencies == [steps[1].id]

    def test_plan_steps_have_order(self) -> None:
        m = Mission(title="Order", description="1. A\n2. B\n3. C")
        steps = generate_plan(m)
        assert steps[0].order == 0
        assert steps[1].order == 1
        assert steps[2].order == 2

    def test_plan_mission_saves(self, project_dir: Path) -> None:
        m = Mission(title="Plan me", description="1. Do this\n2. Do that")
        save_mission(m, project_root=str(project_dir))
        planned = plan_mission(m.id, project_root=str(project_dir))
        assert planned is not None
        assert planned.status == "planned"
        assert len(planned.steps) == 2
        assert planned.plan_summary == "2 steps planned"

    def test_plan_mission_not_found(self, project_dir: Path) -> None:
        assert plan_mission("nope", project_root=str(project_dir)) is None

    def test_empty_lines_ignored(self) -> None:
        m = Mission(title="Gaps", description="1. Do this\n\n\n2. Do that\n\n")
        steps = generate_plan(m)
        assert len(steps) == 2

    def test_duplicates_avoided_in_materialize(self, project_dir: Path, task_engine: TaskEngine) -> None:
        m = Mission(title="Dup", description="1. Step one\n2. Step two")
        save_mission(m, project_root=str(project_dir))
        plan_mission(m.id, project_root=str(project_dir))
        materialize_tasks(m.id, task_engine, project_root=str(project_dir))
        count_first = len(task_engine.tasks)
        materialize_tasks(m.id, task_engine, project_root=str(project_dir))
        assert len(task_engine.tasks) == count_first  # no new duplicates


# ---- Materialize tasks ----


class TestMaterializeTasks:
    def test_materialize_creates_tasks(self, project_dir: Path, task_engine: TaskEngine) -> None:
        m = Mission(title="Mat", description="1. Analyze code\n2. Write tests")
        save_mission(m, project_root=str(project_dir))
        plan_mission(m.id, project_root=str(project_dir))
        result = materialize_tasks(m.id, task_engine, project_root=str(project_dir))
        assert result is not None
        assert result.status == "active"
        assert len(result.task_ids) == 2
        assert len(task_engine.tasks) == 2

    def test_materialize_without_plan(self, project_dir: Path, task_engine: TaskEngine) -> None:
        m = Mission(title="NoPlan")
        save_mission(m, project_root=str(project_dir))
        result = materialize_tasks(m.id, task_engine, project_root=str(project_dir))
        assert result is None

    def test_materialize_not_found(self, project_dir: Path, task_engine: TaskEngine) -> None:
        assert materialize_tasks("nope", task_engine, project_root=str(project_dir)) is None

    def test_materialized_tasks_have_source_mission(self, project_dir: Path, task_engine: TaskEngine) -> None:
        m = Mission(title="Src", description="1. Do a thing")
        save_mission(m, project_root=str(project_dir))
        plan_mission(m.id, project_root=str(project_dir))
        materialize_tasks(m.id, task_engine, project_root=str(project_dir))
        assert task_engine.tasks[0].source == "mission"

    def test_materialized_tasks_have_success_criteria(self, project_dir: Path, task_engine: TaskEngine) -> None:
        m = Mission(title="Crit", description="1. Test something")
        save_mission(m, project_root=str(project_dir))
        plan_mission(m.id, project_root=str(project_dir))
        materialize_tasks(m.id, task_engine, project_root=str(project_dir))
        assert len(task_engine.tasks[0].success_criteria) > 0


# ---- Graph serialization ----


class TestMissionGraph:
    def test_graph_structure(self, project_dir: Path) -> None:
        m = Mission(title="Graph", description="1. A\n2. B\n3. C")
        save_mission(m, project_root=str(project_dir))
        plan_mission(m.id, project_root=str(project_dir))
        graph = get_mission_graph(m.id, project_root=str(project_dir))
        assert graph is not None
        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2  # A→B, B→C
        assert graph["title"] == "Graph"

    def test_graph_serializable(self, project_dir: Path) -> None:
        m = Mission(title="Ser", description="1. X\n2. Y")
        save_mission(m, project_root=str(project_dir))
        plan_mission(m.id, project_root=str(project_dir))
        graph = get_mission_graph(m.id, project_root=str(project_dir))
        serialized = json.dumps(graph)
        assert isinstance(serialized, str)

    def test_graph_not_found(self, project_dir: Path) -> None:
        assert get_mission_graph("nope", project_root=str(project_dir)) is None


# ---- PlanStep model ----


class TestPlanStep:
    def test_to_dict(self) -> None:
        s = PlanStep(title="S", family="code", order=0)
        d = s.to_dict()
        assert d["title"] == "S"
        assert d["family"] == "code"

    def test_from_dict(self) -> None:
        s = PlanStep.from_dict({"title": "T", "family": "test", "order": 1})
        assert s.title == "T"
        assert s.order == 1

    def test_roundtrip(self) -> None:
        s = PlanStep(title="RT", family="fix", dependencies=["a", "b"])
        d = s.to_dict()
        s2 = PlanStep.from_dict(d)
        assert s2.title == s.title
        assert s2.dependencies == ["a", "b"]


# ---- Family classification ----


class TestFamilyClassification:
    def test_analyze(self) -> None:
        from igris.core.mission_planner import _classify_family
        assert _classify_family("Analyze the codebase") == "analyze"

    def test_test(self) -> None:
        from igris.core.mission_planner import _classify_family
        assert _classify_family("Run tests and verify") == "test"

    def test_code(self) -> None:
        from igris.core.mission_planner import _classify_family
        assert _classify_family("Implement new feature") == "code"

    def test_fix(self) -> None:
        from igris.core.mission_planner import _classify_family
        assert _classify_family("Fix the login bug") == "fix"

    def test_docs(self) -> None:
        from igris.core.mission_planner import _classify_family
        assert _classify_family("Document the API") == "docs"

    def test_other(self) -> None:
        from igris.core.mission_planner import _classify_family
        assert _classify_family("something random") == "other"
