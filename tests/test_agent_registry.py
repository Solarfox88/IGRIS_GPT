"""Tests for the agent registry."""
from igris.agents import build_default_registry, list_capabilities, list_agents


def test_default_registry_has_agents():
    build_default_registry()
    agents = list_agents()
    assert len(agents) >= 3


def test_registry_has_git_status():
    build_default_registry()
    caps = list_capabilities()
    cap_ids = [c.id for c in caps]
    assert "git.status" in cap_ids


def test_registry_has_run_tests():
    build_default_registry()
    caps = list_capabilities()
    cap_ids = [c.id for c in caps]
    assert "validation.run_tests" in cap_ids


def test_registry_has_safe_command():
    build_default_registry()
    caps = list_capabilities()
    cap_ids = [c.id for c in caps]
    assert "execution.run_safe_command" in cap_ids
