"""Tests for #913 — decompositor quality improvements.

Verifies that:
1. _infer_file_scopes() no longer returns the broad "igris/**" glob.
2. _make_sub() anti-loop guard flags broad-scope + generic-criteria combos
   as human_approval_required=True.
3. Strategy 4 (Memory Tree) produces 5 explicit steps with concrete
   file_scopes and verifiable acceptance_criteria.
4. All sub-missions produced by Strategy 4 are NOT flagged as broad/generic
   (they have explicit params → human_approval_required=False per step).
5. Strategy 4 outer result has human_approval_required=True (gate).
"""
from __future__ import annotations

import pytest

from igris.core.self_repair_supervisor import SelfRepairSupervisor


def _decompose(goal: str) -> dict:
    """Run _deterministic_decompose_fallback on a goal and return the result."""
    signals = {"no_diff_repair": 3}
    return SelfRepairSupervisor._deterministic_decompose_fallback(goal, signals)


# ---------------------------------------------------------------------------
# _infer_file_scopes — no longer returns igris/**
# ---------------------------------------------------------------------------

class TestInferFileScopes:
    """Validate file scope inference improvements."""

    def test_no_broad_igris_glob_for_generic_goal(self):
        """Generic goal must not return ['igris/**']."""
        result = _decompose("Do something unrelated")
        for sub in result.get("sub_missions", []):
            scopes = sub.get("allowed_file_scopes", [])
            assert "igris/**" not in scopes, (
                f"Sub-mission {sub['title']!r} still uses broad igris/** scope: {scopes}"
            )

    def test_memory_scorer_gets_precise_scope(self):
        result = _decompose(
            "Implement memory_scorer module with score() and rank() methods; "
            "write tests in tests/test_memory_scorer.py"
        )
        sub = result["sub_missions"][0]
        scopes = sub["allowed_file_scopes"]
        assert any("memory_scorer" in s for s in scopes), (
            f"Expected memory_scorer.py in scopes, got: {scopes}"
        )

    def test_endpoint_goal_gets_web_scope(self):
        result = _decompose(
            "Add GET /api/status endpoint to the server; "
            "write test coverage"
        )
        sub = result["sub_missions"][0]
        scopes = sub["allowed_file_scopes"]
        assert any("server" in s or "web" in s for s in scopes), (
            f"Expected web scope for endpoint goal, got: {scopes}"
        )


# ---------------------------------------------------------------------------
# _make_sub anti-loop guard
# ---------------------------------------------------------------------------

class TestMakeSubAntiLoopGuard:
    """Broad scope + generic criteria must trigger human_approval_required."""

    def test_strategy5_single_sub_has_human_approval(self):
        """Strategy 5 (fallback) should flag human_approval_required=True."""
        result = _decompose(
            "Some unrecognized goal that does not match any specific strategy pattern"
        )
        assert result.get("human_approval_required") is True, (
            "Strategy 5 outer dict must require human approval"
        )

    def test_strategy4_outer_requires_human_approval(self):
        """Strategy 4 outer dict must be human_approval_required=True."""
        result = _decompose(
            "Memory tree hierarchy: implement chunk, score, topic and global pipeline"
        )
        assert result.get("human_approval_required") is True, (
            "Strategy 4 must require human approval"
        )


# ---------------------------------------------------------------------------
# Strategy 4 — 5 explicit steps
# ---------------------------------------------------------------------------

class TestStrategy4MemoryTree:
    """Validate Strategy 4 produces 5 bounded, explicit sub-missions."""

    @pytest.fixture
    def result(self):
        return _decompose(
            "Memory tree hierarchy: implement chunk layer, score aggregation, "
            "topic grouping, global synthesis pipeline for issue #536"
        )

    def test_produces_five_sub_missions(self, result):
        assert len(result["sub_missions"]) == 5, (
            f"Expected 5 sub-missions, got {len(result['sub_missions'])}"
        )

    def test_step0_is_readonly(self, result):
        step0 = result["sub_missions"][0]
        assert "Step 0" in step0["title"] or "architecture" in step0["title"].lower(), (
            f"First sub-mission should be Step 0 / architecture: {step0['title']}"
        )
        assert step0["tests"] == [], (
            "Step 0 (read-only) must have empty tests list"
        )
        criteria = step0["acceptance_criteria"]
        assert any("production code" in c.lower() or "no production" in c.lower()
                   for c in criteria), (
            "Step 0 must assert no production code is written"
        )

    def test_all_steps_have_explicit_acceptance_criteria(self, result):
        for i, sub in enumerate(result["sub_missions"]):
            criteria = sub.get("acceptance_criteria", [])
            assert len(criteria) >= 2, (
                f"Sub-mission {i} ({sub['title']!r}) must have ≥2 acceptance criteria, "
                f"got: {criteria}"
            )
            # No generic "implemented and validated" criterion allowed on explicit steps
            if i > 0:  # step 0 is special
                assert not any(c.strip().lower().endswith("implemented and validated")
                               and len(c) < 60
                               for c in criteria), (
                    f"Sub-mission {i} has generic criterion: {criteria}"
                )

    def test_all_steps_have_precise_file_scopes(self, result):
        broad = {"igris/**", "igris/core/", "tests/"}
        for i, sub in enumerate(result["sub_missions"]):
            scopes = set(sub.get("allowed_file_scopes", []))
            if i > 0:  # step 0 has .igris/ which is fine
                assert "igris/**" not in scopes, (
                    f"Step {i} ({sub['title']!r}) uses broad igris/** scope"
                )
                assert not scopes <= broad, (
                    f"Step {i} ({sub['title']!r}) scopes are too broad: {scopes}"
                )

    def test_steps_1_4_have_test_files(self, result):
        for i, sub in enumerate(result["sub_missions"][1:], start=1):
            tests = sub.get("tests", [])
            assert len(tests) >= 1, (
                f"Step {i} ({sub['title']!r}) must have at least 1 test file"
            )
            assert any("test_" in t for t in tests), (
                f"Step {i} tests should reference a test_*.py file: {tests}"
            )

    def test_step4_covers_retrieval_integration(self, result):
        step4 = result["sub_missions"][4]
        assert "Step 4" in step4["title"] or "retrieval" in step4["title"].lower(), (
            f"Last sub-mission should be Step 4 / retrieval: {step4['title']}"
        )
        assert any("memory_graph" in s for s in step4["allowed_file_scopes"]), (
            f"Step 4 must target memory_graph.py: {step4['allowed_file_scopes']}"
        )

    def test_generated_by_deterministic_fallback(self, result):
        assert result.get("generated_by") == "deterministic_fallback"


# ---------------------------------------------------------------------------
# Advisory diagnostic test (#914 sanity)
# ---------------------------------------------------------------------------

class TestAdvisoryImport:
    """Verify the advisory lazy-import flag is accessible (#914)."""

    def test_advisory_flag_exists(self):
        import igris.core.self_repair_supervisor as sup
        assert hasattr(sup, "_selected_advisory_available"), (
            "_selected_advisory_available flag must be defined at module level"
        )

    def test_advisory_flag_is_bool(self):
        import igris.core.self_repair_supervisor as sup
        assert isinstance(sup._selected_advisory_available, bool)

    def test_no_broad_igris_glob_in_any_strategy(self):
        """Exhaustive check: no strategy should ever produce igris/** scope."""
        goals = [
            "Generic task",
            "Build something new",
            "Update the configuration",
            "Memory tree hierarchy chunk score topic global pipeline",
            "Implement endpoint /api/status with tests",
        ]
        for goal in goals:
            result = _decompose(goal)
            for sub in result.get("sub_missions", []):
                scopes = sub.get("allowed_file_scopes", [])
                assert "igris/**" not in scopes, (
                    f"Goal {goal!r} → sub {sub['title']!r} still uses igris/**: {scopes}"
                )
