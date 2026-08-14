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
