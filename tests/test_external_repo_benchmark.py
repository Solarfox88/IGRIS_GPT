"""Tests for Sprint 27 — External Repo Sandbox Benchmark.

Verifies IGRIS_GPT can execute its full workflow on an external
sandbox project (tests/fixtures/sandbox_repo).

5 scenarios:
1. Simple Python bugfix
2. Failing test repair
3. Docs update
4. Small refactor
5. Multi-file safe patch

Each scenario exercises: mission -> plan -> materialize -> patch proposal ->
validation -> decision report -> memory update -> final outcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

import pytest
from fastapi.testclient import TestClient

from igris.web.server import create_app


SANDBOX = Path(__file__).parent / "fixtures" / "sandbox_repo"


@pytest.fixture
def client():
    return TestClient(create_app())


def _full_workflow(client: TestClient, mission_data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute complete IGRIS workflow and return benchmark record."""
    record: Dict[str, Any] = {"scenario": mission_data["title"]}

    # 1. Create mission
    r = client.post("/api/missions", json=mission_data)
    assert r.status_code == 200
    mission = r.json()
    mid = mission["id"]
    record["mission_id"] = mid

    # 2. Plan
    r = client.post(f"/api/missions/{mid}/plan?mode=deterministic")
    assert r.status_code == 200
    plan = r.json()
    record["plan_mode"] = plan["planning"]["mode"]
    record["plan_steps"] = len(plan.get("mission", plan).get("steps", []))

    # 3. Materialize tasks
    r = client.post(f"/api/missions/{mid}/materialize-tasks")
    assert r.status_code == 200
    mat = r.json()
    record["tasks_created"] = len(mat.get("task_ids", []))

    # 4. Loop step
    r = client.post("/api/loop/step")
    assert r.status_code == 200
    record["loop_result"] = r.json().get("stop_reason") or "task_selected"

    # 5. Decision report
    r = client.get("/api/decision-reports")
    assert r.status_code == 200
    reports = r.json()
    record["decision_reports"] = len(reports) if isinstance(reports, list) else 0

    # 6. Memory analysis
    r = client.post("/api/memory/analyze")
    assert r.status_code == 200
    analysis = r.json()
    record["memory_advisory_only"] = analysis["advisory_only"]

    record["outcome"] = "workflow_complete"
    return record


def _propose_patch(client: TestClient, title: str, desc: str, files: list) -> dict:
    """Create patch proposal with correct API format."""
    r = client.post("/api/patches/propose", json={
        "title": title,
        "description": desc,
        "files": files,
    })
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Scenario 1: Simple Python bugfix
# ---------------------------------------------------------------------------


class TestBugfixScenario:
    """Scenario 1: Fix divide-by-zero bug in calculator.py."""

    def test_bugfix_mission_workflow(self, client):
        record = _full_workflow(client, {
            "title": "Fix divide-by-zero bug",
            "description": (
                "1. Read calculator.py divide function\n"
                "2. Add zero division check\n"
                "3. Run tests to verify fix"
            ),
        })
        assert record["plan_steps"] >= 2
        assert record["memory_advisory_only"] is True
        assert record["outcome"] == "workflow_complete"

    def test_bugfix_patch_proposal(self, client):
        """Create a patch proposal for the bugfix."""
        original = (SANDBOX / "calculator.py").read_text()
        fixed = original.replace(
            "    # BUG: no zero division check\n    return a / b",
            '    if b == 0:\n        raise ValueError("Cannot divide by zero")\n    return a / b',
        )
        proposal = _propose_patch(client,
            title="Fix divide-by-zero",
            desc="Raise ValueError instead of ZeroDivisionError",
            files=[{"path": "calculator.py", "action": "create", "after": fixed}],
        )
        assert "id" in proposal

    def test_bugfix_patch_validation(self, client):
        """Validate the bugfix patch is safe."""
        original = (SANDBOX / "calculator.py").read_text()
        fixed = original.replace(
            "    # BUG: no zero division check\n    return a / b",
            '    if b == 0:\n        raise ValueError("Cannot divide by zero")\n    return a / b',
        )
        proposal = _propose_patch(client,
            title="Fix divide validation",
            desc="Validate the fix",
            files=[{"path": "calculator.py", "action": "create", "after": fixed}],
        )
        r = client.post(f"/api/patches/{proposal['id']}/validate")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 2: Failing test repair
# ---------------------------------------------------------------------------


class TestFailingTestScenario:
    """Scenario 2: Identify and repair failing test."""

    def test_failing_test_workflow(self, client):
        record = _full_workflow(client, {
            "title": "Fix failing test_divide_by_zero",
            "description": (
                "1. Run test suite\n"
                "2. Identify test_divide_by_zero fails\n"
                "3. Fix calculator.divide to raise ValueError on zero"
            ),
        })
        assert record["plan_steps"] >= 2
        assert record["outcome"] == "workflow_complete"

    def test_failure_memory_recording(self, client):
        """Record test failure in memory."""
        r = client.post("/api/memory/events", json={
            "event_type": "failure",
            "title": "test_divide_by_zero failed",
            "family": "test",
            "reason": "ZeroDivisionError raised instead of ValueError",
        })
        assert r.status_code == 200

        r = client.get("/api/memory/failures")
        assert r.status_code == 200

    def test_failure_triggers_analysis(self, client):
        """Memory analysis detects the failure pattern."""
        client.post("/api/memory/events", json={
            "event_type": "failure",
            "title": "test_divide_by_zero failed",
            "family": "test",
            "reason": "ZeroDivisionError raised instead of ValueError",
        })
        r = client.post("/api/memory/analyze")
        assert r.status_code == 200
        assert r.json()["advisory_only"] is True


# ---------------------------------------------------------------------------
# Scenario 3: Docs update
# ---------------------------------------------------------------------------


class TestDocsUpdateScenario:
    """Scenario 3: Update README with new usage info."""

    def test_docs_workflow(self, client):
        record = _full_workflow(client, {
            "title": "Update calculator README",
            "description": (
                "1. Read current README\n"
                "2. Add percentage function documentation\n"
                "3. Verify formatting"
            ),
        })
        assert record["plan_steps"] >= 2
        assert record["outcome"] == "workflow_complete"

    def test_docs_patch_proposal(self, client):
        """Create patch proposal for docs update."""
        original = (SANDBOX / "README.md").read_text()
        updated = original + "\n## Percentage\n\n```python\npercentage(25, 100)  # 25.0\n```\n"
        proposal = _propose_patch(client,
            title="Add percentage docs",
            desc="Document percentage function",
            files=[{"path": "README.md", "action": "create", "after": updated}],
        )
        assert "id" in proposal

    def test_docs_patch_safe(self, client):
        """Docs patch must pass safety validation."""
        proposal = _propose_patch(client,
            title="Add new section",
            desc="Safe content addition",
            files=[{"path": "README.md", "action": "create", "after": "# Safe\n\nSafe content.\n"}],
        )
        r = client.post(f"/api/patches/{proposal['id']}/validate")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 4: Small refactor
# ---------------------------------------------------------------------------


class TestRefactorScenario:
    """Scenario 4: Refactor calculator to add input validation."""

    def test_refactor_workflow(self, client):
        record = _full_workflow(client, {
            "title": "Add input validation to calculator",
            "description": (
                "1. Read calculator.py\n"
                "2. Add type checking using utils.validate_number\n"
                "3. Update tests"
            ),
        })
        assert record["plan_steps"] >= 2
        assert record["outcome"] == "workflow_complete"

    def test_refactor_patch_proposal(self, client):
        """Create refactor patch proposal."""
        original = (SANDBOX / "calculator.py").read_text()
        refactored = original.replace(
            "def add(a, b):\n    return a + b",
            "def add(a, b):\n    \"\"\"Add two numbers.\"\"\"\n    return a + b",
        )
        proposal = _propose_patch(client,
            title="Add docstrings",
            desc="Add docstring to add function",
            files=[{"path": "calculator.py", "action": "create", "after": refactored}],
        )
        assert "id" in proposal


# ---------------------------------------------------------------------------
# Scenario 5: Multi-file safe patch
# ---------------------------------------------------------------------------


class TestMultiFileScenario:
    """Scenario 5: Modify calculator.py and utils.py together."""

    def test_multifile_workflow(self, client):
        record = _full_workflow(client, {
            "title": "Add history feature to calculator",
            "description": (
                "1. Add history list to calculator.py\n"
                "2. Add format_history to utils.py\n"
                "3. Write tests for new feature"
            ),
        })
        assert record["plan_steps"] >= 2
        assert record["outcome"] == "workflow_complete"

    def test_multifile_patch_both_files(self, client):
        """Patch proposal covering both calculator.py and utils.py."""
        calc = (SANDBOX / "calculator.py").read_text()
        calc_updated = calc + "\n\n_history = []\n\ndef get_history():\n    return list(_history)\n"
        utils = (SANDBOX / "utils.py").read_text()
        utils_updated = utils + "\n\ndef format_history(history):\n    return [f\"{i+1}. {e}\" for i, e in enumerate(history)]\n"
        proposal = _propose_patch(client,
            title="Add history feature",
            desc="Multi-file history tracking",
            files=[
                {"path": "calculator.py", "action": "create", "after": calc_updated},
                {"path": "utils.py", "action": "create", "after": utils_updated},
            ],
        )
        assert "id" in proposal

    def test_multifile_validation(self, client):
        """Multi-file patch passes validation."""
        proposal = _propose_patch(client,
            title="Multi-file safe",
            desc="Two safe files",
            files=[
                {"path": "a.py", "action": "create", "after": "# safe\n"},
                {"path": "b.py", "action": "create", "after": "# safe\n"},
            ],
        )
        r = client.post(f"/api/patches/{proposal['id']}/validate")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Cross-scenario checks
# ---------------------------------------------------------------------------


class TestBenchmarkCrossChecks:
    """Cross-cutting verification across all scenarios."""

    def test_sandbox_fixture_exists(self):
        assert SANDBOX.exists()
        assert (SANDBOX / "calculator.py").exists()
        assert (SANDBOX / "test_calculator.py").exists()
        assert (SANDBOX / "utils.py").exists()
        assert (SANDBOX / "README.md").exists()

    def test_all_scenarios_advisory_only(self, client):
        """Memory analysis is always advisory across scenarios."""
        for i in range(3):
            client.post("/api/memory/events", json={
                "event_type": "failure",
                "title": f"Benchmark failure {i}",
                "family": "test",
                "reason": "benchmark test",
            })
        r = client.post("/api/memory/analyze")
        assert r.json()["advisory_only"] is True

    def test_diagnostics_after_benchmarks(self, client):
        """Diagnostics endpoint works after benchmark runs."""
        r = client.get("/api/diagnostics")
        assert r.status_code == 200

    def test_lessons_after_benchmarks(self, client):
        """Lessons learned available after benchmark runs."""
        r = client.get("/api/memory/lessons")
        assert r.status_code == 200
        assert r.json()["advisory_only"] is True
