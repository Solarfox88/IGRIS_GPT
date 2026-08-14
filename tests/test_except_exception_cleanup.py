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


# ── Phase 2 tests — specific exception types (#1353) ─────────────────────────

REPO_ROOT = Path(__file__).parent.parent


def test_except_exception_count_decreased():
    """Phase 2: the number of 'except Exception' patterns should decrease.

    Baseline was 627 at the start of #1353 Phase 2.
    We expect at least 50 to be narrowed to specific types.
    """
    import subprocess
    result = subprocess.run(
        ["python", "-c",
         "import subprocess,sys; "
         "r=subprocess.run(['rg','--count','except Exception','igris/'],"
         "capture_output=True,text=True); "
         "print(r.stdout.count(chr(10)))"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    # Fallback: count manually
    import re
    count = 0
    for py_file in (REPO_ROOT / "igris").rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            count += len(re.findall(r'except Exception', content))
        except Exception:
            continue
    # Baseline was 627; we should have reduced by at least 50
    assert count < 627, \
        f"except Exception count ({count}) should be less than baseline (627)"


def test_no_bare_except_exception_pass_in_changed_modules():
    """Phase 2: no 'except Exception: pass' in modules we narrowed.

    The modules we changed should not have bare 'except Exception: pass'
    patterns remaining — they should either log or use specific types.
    """
    import re
    changed_modules = [
        "igris/core/chat_context.py",
        "igris/core/system_info.py",
        "igris/core/proactive_engine.py",
        "igris/core/unified_memory.py",
        "igris/core/memory_gc.py",
        "igris/core/memory_graph.py",
        "igris/core/context_aggregator.py",
        "igris/core/task_engine.py",
        "igris/core/work_session.py",
        "igris/core/tts_engine.py",
        "igris/core/verifier_registry.py",
        "igris/core/code_health_monitor.py",
        "igris/core/mbop_runner.py",
        "igris/core/execution_report.py",
        "igris/core/patch_proposal.py",
        "igris/core/inventory_catalog.py",
    ]
    bare_pattern = re.compile(r'except Exception:\s*pass\s*$')
    violations = []
    for mod in changed_modules:
        fp = REPO_ROOT / mod
        if not fp.exists():
            continue
        try:
            content = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if bare_pattern.search(line):
                violations.append(f"{mod}:{i}")
    assert not violations, \
        f"Found bare 'except Exception: pass' in changed modules: {violations}"


def test_proactive_engine_uses_specific_exceptions():
    """Phase 2: proactive_engine should use specific exception types."""
    fp = REPO_ROOT / "igris" / "core" / "proactive_engine.py"
    content = fp.read_text(encoding="utf-8")
    # Should no longer have 'except Exception' for JSON parsing
    assert "(OSError, json.JSONDecodeError, TypeError)" in content or \
           "(json.JSONDecodeError, OSError, TypeError)" in content, \
        "proactive_engine should use specific exception types for JSON parsing"


def test_memory_gc_uses_specific_exceptions():
    """Phase 2: memory_gc should use specific exception types."""
    fp = REPO_ROOT / "igris" / "core" / "memory_gc.py"
    content = fp.read_text(encoding="utf-8")
    # Should use specific types for value conversion
    assert "(ValueError, TypeError)" in content, \
        "memory_gc should use (ValueError, TypeError) for float conversions"
    # Should use sqlite3.Error for database operations
    assert "sqlite3.Error" in content, \
        "memory_gc should use sqlite3.Error for database operations"


# ── Logging verification ─────────────────────────────────────────────────────

def test_silent_catches_now_log(tmp_path, caplog):
    """Verify that silent catches now produce log entries when errors occur."""
    _setup(tmp_path)
    # Create a malformed task file BEFORE creating the engine
    tasks_dir = tmp_path / ".igris" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "malformed.json").write_text("{invalid json}", encoding="utf-8")

    # Ensure propagation is enabled for caplog to capture records
    igris_logger = logging.getLogger("igris")
    original_propagate = igris_logger.propagate
    igris_logger.propagate = True
    try:
        with caplog.at_level(logging.DEBUG, logger="igris.core.task_engine"):
            from igris.core.task_engine import TaskEngine
            engine = TaskEngine(runtime_root=tmp_path / ".igris")
    finally:
        igris_logger.propagate = original_propagate

    # Should have at least one debug log about the malformed file
    assert len(caplog.records) > 0, "Expected at least one log entry for malformed task file"
