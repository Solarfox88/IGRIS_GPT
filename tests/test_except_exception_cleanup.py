"""Tests for #1314 Phase 1 — except Exception cleanup (logging added).

Verifies that silent `except Exception: pass` patterns now log errors
instead of silently swallowing them. Tests are behavioral — they verify
that the code still works correctly and that errors are logged.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest


def _setup(tmp_path):
    """Create isolated test environment."""
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / ".igris" / "tasks").mkdir(parents=True)
    (root / ".igris" / "timeline").mkdir(parents=True)
    (root / ".igris" / "missions").mkdir(parents=True)
    (root / ".igris" / "memory").mkdir(parents=True)
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["WORKSPACE_ROOT"] = str(root)
    os.environ["IGRIS_PROJECT_ROOT"] = str(root)
    from igris.models.config import CONFIG
    CONFIG.project_root = Path(str(root))
    return root


# ── UnifiedMemory silent catches ─────────────────────────────────────────────

def test_unified_memory_handles_missing_backends_gracefully(tmp_path):
    """UnifiedMemory should handle unavailable backends without crashing."""
    _setup(tmp_path)
    from igris.core.unified_memory import UnifiedMemory
    um = UnifiedMemory(project_root=str(tmp_path))
    # Should not crash even if backends are unavailable
    assert um is not None
    # Backends dict should exist
    assert hasattr(um, "_backends")


def test_unified_memory_retrieve_does_not_crash_on_empty(tmp_path):
    """UnifiedMemory retrieve on empty store should not crash."""
    _setup(tmp_path)
    from igris.core.unified_memory import UnifiedMemory
    um = UnifiedMemory(project_root=str(tmp_path))
    result = um.retrieve_for_chat("test query", interlocutor_id="test", trust_level="admin")
    assert result is not None


# ── TaskEngine silent catches ────────────────────────────────────────────────

def test_task_engine_loads_with_malformed_json(tmp_path):
    """TaskEngine should skip malformed task files without crashing."""
    _setup(tmp_path)
    from igris.core.task_engine import TaskEngine
    engine = TaskEngine(runtime_root=tmp_path / ".igris")
    # Create a malformed task file
    tasks_dir = tmp_path / ".igris" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "malformed.json").write_text("{invalid json}", encoding="utf-8")
    # Should not crash
    tasks = engine.list_tasks()
    assert isinstance(tasks, list)


def test_task_engine_timeline_loads_with_malformed_json(tmp_path):
    """TaskEngine timeline loading should skip malformed files."""
    _setup(tmp_path)
    from igris.core.task_engine import TaskEngine
    engine = TaskEngine(runtime_root=tmp_path / ".igris")
    timeline_dir = tmp_path / ".igris" / "timeline"
    timeline_dir.mkdir(parents=True, exist_ok=True)
    (timeline_dir / "malformed.json").write_text("{invalid json}", encoding="utf-8")
    # Should not crash — use recent_timeline_events (actual method name)
    events = engine.recent_timeline_events(limit=10)
    assert isinstance(events, list)


# ── SystemInfo silent catches ────────────────────────────────────────────────

def test_system_info_does_not_crash(tmp_path):
    """SystemInfo should return data even if some checks fail."""
    _setup(tmp_path)
    from igris.core.system_info import get_system_info
    info = get_system_info()
    assert isinstance(info, dict)
    # Should have some basic fields
    assert "os" in info or "platform" in info or "cpu" in info


# ── ShadowML silent catches ──────────────────────────────────────────────────

def test_shadow_ml_handles_missing_config(tmp_path):
    """ShadowML components should handle missing CONFIG gracefully."""
    _setup(tmp_path)
    from igris.core.shadow_ml import IntentRiskShadowModel
    model = IntentRiskShadowModel(project_root=str(tmp_path))
    assert model is not None


# ── VerifierRegistry silent catches ──────────────────────────────────────────

def test_verifier_registry_handles_missing_config(tmp_path):
    """VerifierRegistry should handle missing CONFIG gracefully."""
    _setup(tmp_path)
    from igris.core.verifier_registry import VerifierRegistry
    registry = VerifierRegistry(project_root=str(tmp_path))
    assert registry is not None


# ── TTS engine silent catches ────────────────────────────────────────────────

def test_tts_engine_handles_missing_manifest(tmp_path):
    """TTS engine should handle missing voice manifest gracefully."""
    _setup(tmp_path)
    from igris.core.tts_engine import TTSEngine
    # Should not crash even if no manifests exist
    engine = TTSEngine(project_root=str(tmp_path))
    assert engine is not None


# ── Logging verification ─────────────────────────────────────────────────────

def test_silent_catches_now_log(tmp_path, caplog):
    """Verify that silent catches now produce log entries when errors occur."""
    _setup(tmp_path)
    # Create a malformed task file BEFORE creating the engine
    tasks_dir = tmp_path / ".igris" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "malformed.json").write_text("{invalid json}", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="igris.core.task_engine"):
        from igris.core.task_engine import TaskEngine
        engine = TaskEngine(runtime_root=tmp_path / ".igris")

    # Should have at least one debug log about the malformed file
    assert len(caplog.records) > 0, "Expected at least one log entry for malformed task file"
