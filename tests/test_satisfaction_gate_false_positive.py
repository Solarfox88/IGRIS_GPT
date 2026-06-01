"""Tests for #1105 fix: prevent false positives in structural satisfaction gate.

The bug: `_test_ac_structurally_covered` returned `has_test_file or True`,
meaning ANY test-like AC was satisfied when pytest passed, even without
a test file in the diff.

The fix: pytest green alone is NOT sufficient — a relevant test file
must appear in the diff for test-like ACs to be structurally covered.
"""

from igris.core.mbop_runner import (
    MBOPIntakeResult,
    MBOPQualityGateResult,
    MBOPSatisfactionGateResult,
    _is_route_like_ac,
    _is_test_like_ac,
    _route_ac_structurally_covered,
    _test_ac_structurally_covered,
    mbop_phase10_satisfaction_gate,
)


def _quality(pytest_ran: bool = True, pytest_passed: bool = True) -> MBOPQualityGateResult:
    return MBOPQualityGateResult(
        passed=pytest_passed,
        pytest_ran=pytest_ran,
        pytest_passed=pytest_passed,
    )


def _intake(criteria: list[str]) -> MBOPIntakeResult:
    return MBOPIntakeResult(
        issue_number=1,
        what="test task",
        operating_mode="compact",
        acceptance_criteria=criteria,
    )


# ---------------------------------------------------------------------------
# Core false positive fix
# ---------------------------------------------------------------------------

def test_test_ac_fails_without_test_file_even_if_pytest_passed():
    """AC 'add tests' + pytest green + no test file → NOT covered."""
    qg = _quality(pytest_ran=True, pytest_passed=True)
    result = _test_ac_structurally_covered("add tests for the feature", "", qg)
    assert result is False


def test_test_ac_fails_without_test_file_no_quality_gate():
    """AC 'add tests' + no quality gate → NOT covered."""
    result = _test_ac_structurally_covered("add tests", "", None)
    assert result is False


def test_test_ac_passes_with_test_file_and_pytest_green():
    """AC 'add tests' + pytest green + test file in diff → covered."""
    diff = "+++ b/tests/test_feature.py\n+def test_something():"
    qg = _quality(pytest_ran=True, pytest_passed=True)
    result = _test_ac_structurally_covered("add tests", diff, qg)
    assert result is True


def test_test_ac_passes_with_test_file_but_pytest_failed():
    """AC 'add tests' + pytest failed + test file in diff → still covered
    (the AC is about having tests, not about them passing)."""
    diff = "+++ b/tests/test_feature.py\n+def test_something():"
    qg = _quality(pytest_ran=True, pytest_passed=False)
    result = _test_ac_structurally_covered("add tests", diff, qg)
    assert result is True


def test_test_ac_passes_with_test_file_name_pattern():
    """AC 'add tests' + diff mentions test_*.py file → covered."""
    diff = "modified: test_api.py\n+def test_endpoint():"
    qg = _quality()
    result = _test_ac_structurally_covered("ensure test coverage", diff, qg)
    assert result is True


# ---------------------------------------------------------------------------
# Route AC: endpoint in comment only must fail
# ---------------------------------------------------------------------------

def test_route_ac_fails_if_endpoint_only_in_comment():
    """Endpoint cited only in a comment, no route declaration → NOT covered."""
    diff = "# TODO: add /api/health endpoint\n+ pass"
    result = _route_ac_structurally_covered("add /api/health endpoint", diff)
    assert result is False


def test_route_ac_passes_with_real_route_declaration():
    """Endpoint in diff + route declaration → covered."""
    diff = '@app.get("/api/health")\ndef health():\n    return {"ok": True}'
    result = _route_ac_structurally_covered("add /api/health endpoint", diff)
    assert result is True


def test_route_ac_passes_with_router_declaration():
    """Route declared via router.get → covered."""
    diff = 'router.get("/api/items")\ndef items():\n    return []'
    result = _route_ac_structurally_covered("add /api/items endpoint", diff)
    assert result is True


def test_route_ac_fails_without_route_hint():
    """Endpoint path in diff but no @app. or router. → NOT covered."""
    diff = '"/api/health" appears in a string'
    result = _route_ac_structurally_covered("add /api/health", diff)
    assert result is False


# ---------------------------------------------------------------------------
# Classifier helpers
# ---------------------------------------------------------------------------

def test_is_test_like_ac_positive():
    assert _is_test_like_ac("add tests for feature")
    assert _is_test_like_ac("increase coverage")
    assert _is_test_like_ac("run pytest suite")


def test_is_test_like_ac_negative():
    assert not _is_test_like_ac("add endpoint")
    assert not _is_test_like_ac("fix bug in server")


def test_is_route_like_ac_positive():
    assert _is_route_like_ac("add /api/health endpoint")
    assert _is_route_like_ac("create route for users")
    assert _is_route_like_ac("add fastapi router")


def test_is_route_like_ac_negative():
    assert not _is_route_like_ac("add tests")
    assert not _is_route_like_ac("fix memory leak")


# ---------------------------------------------------------------------------
# Full satisfaction gate integration
# ---------------------------------------------------------------------------

def test_satisfaction_gate_test_ac_fails_without_test_file():
    """Full gate: 'add test' AC + pytest green + no test file → missing."""
    intake = _intake(["add unit tests for the feature"])
    diff = "--- a/igris/core/feature.py\n+++ b/igris/core/feature.py\n+def feature():"
    qg = _quality(pytest_ran=True, pytest_passed=True)
    result = mbop_phase10_satisfaction_gate(intake, diff, "feat: add feature", qg)
    assert "add unit tests for the feature" in result.criteria_missing


def test_satisfaction_gate_test_ac_passes_with_test_file():
    """Full gate: 'add test' AC + pytest green + test file → covered."""
    intake = _intake(["add unit tests for the feature"])
    diff = (
        "--- a/igris/core/feature.py\n+++ b/igris/core/feature.py\n+def feature():\n"
        "+++ b/tests/test_feature.py\n+def test_feature():"
    )
    qg = _quality(pytest_ran=True, pytest_passed=True)
    result = mbop_phase10_satisfaction_gate(intake, diff, "feat: add feature", qg)
    assert "add unit tests for the feature" in result.criteria_covered


def test_satisfaction_gate_mixed_criteria():
    """Mixed ACs: test AC without test file fails, route AC with route passes."""
    intake = _intake([
        "add unit tests for /api/health",
        "create /api/health endpoint",
    ])
    diff = '@app.get("/api/health")\ndef health():\n    return {"ok": True}'
    qg = _quality(pytest_ran=True, pytest_passed=True)
    result = mbop_phase10_satisfaction_gate(intake, diff, "feat: health endpoint", qg)
    # Route AC should pass, test AC should fail (no test file)
    assert "create /api/health endpoint" in result.criteria_covered
    assert "add unit tests for /api/health" in result.criteria_missing


def test_satisfaction_gate_no_criteria_advisory_pass():
    """No structured ACs → advisory pass."""
    intake = _intake([])
    result = mbop_phase10_satisfaction_gate(intake, "", "")
    assert result.passed is True
    assert "no structured ACs" in result.evidence


def test_satisfaction_gate_keyword_fallback_still_works():
    """Non-test, non-route AC uses keyword fallback."""
    intake = _intake(["implement memory cleanup function"])
    diff = "+def memory_cleanup():\n+    entries.clear()"
    result = mbop_phase10_satisfaction_gate(intake, diff, "feat: memory cleanup")
    assert "implement memory cleanup function" in result.criteria_covered
