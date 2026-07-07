"""Tests for PR-2 of epic #1301: Config.igris_dir property.

Verifies that CONFIG.igris_dir is always project_root / '.igris',
and that long_term_memory / browser_evidence fall back to it correctly.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from igris.models.config import Config, LLMConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(project_root: Path) -> Config:
    """Build a minimal Config pointing at project_root."""
    llm = LLMConfig(provider="ollama", model="phi4-mini", base_url="http://127.0.0.1:11434")
    return Config(
        local_llm=llm,
        fallback_llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash"),
        openai_chat_fallback=LLMConfig(provider="openai", model="gpt-4o-mini"),
        project_root=project_root,
    )


# ── 1. Property semantics ─────────────────────────────────────────────────────

def test_igris_dir_is_dot_igris_under_project_root(tmp_path):
    """Config.igris_dir must equal project_root / '.igris'."""
    cfg = _make_config(tmp_path)
    assert cfg.igris_dir == tmp_path / ".igris"


def test_igris_dir_changes_with_project_root(tmp_path):
    """Two configs with different project_root yield different igris_dir."""
    cfg_a = _make_config(tmp_path / "a")
    cfg_b = _make_config(tmp_path / "b")
    assert cfg_a.igris_dir != cfg_b.igris_dir
    assert cfg_a.igris_dir == tmp_path / "a" / ".igris"
    assert cfg_b.igris_dir == tmp_path / "b" / ".igris"


def test_igris_dir_returns_path_object(tmp_path):
    """igris_dir must be a pathlib.Path, not a string."""
    cfg = _make_config(tmp_path)
    assert isinstance(cfg.igris_dir, Path)


def test_igris_dir_not_serialized_by_model_dump(tmp_path):
    """igris_dir is a @property, not a model field — must not appear in model_dump()."""
    cfg = _make_config(tmp_path)
    data = cfg.model_dump()
    assert "igris_dir" not in data, (
        "igris_dir appeared in model_dump() — @property was accidentally declared as a field"
    )


def test_igris_dir_reads_project_root_at_construction(tmp_path):
    """igris_dir must reflect whatever project_root was set at construction time."""
    cfg = _make_config(tmp_path)
    assert cfg.igris_dir == tmp_path / ".igris"


# ── 2. long_term_memory fallback ──────────────────────────────────────────────

def test_long_term_memory_default_path_uses_igris_dir(monkeypatch, tmp_path):
    """LongTermMemory default path must be under CONFIG.igris_dir / memory / long_term."""
    import igris.models.config as cfg_mod
    # Patch project_root on the live singleton — no module reload needed
    monkeypatch.setattr(cfg_mod.CONFIG, "project_root", tmp_path)
    from igris.core.long_term_memory import LongTermMemory
    store = LongTermMemory()
    expected = tmp_path / ".igris" / "memory" / "long_term"
    assert store._base_path == expected, (
        f"Expected {expected}, got {store._base_path}"
    )


def test_long_term_memory_explicit_storage_dir_takes_precedence(tmp_path):
    """When storage_dir is passed, igris_dir fallback must not be used."""
    explicit = str(tmp_path / "custom_memory")
    from igris.core.long_term_memory import LongTermMemory
    store = LongTermMemory(storage_dir=explicit)
    assert store._base_path == Path(explicit)
    # Must NOT be under .igris
    assert ".igris" not in str(store._base_path)


# ── 3. browser_evidence fallback ──────────────────────────────────────────────

def test_browser_evidence_default_path_uses_igris_dir(monkeypatch, tmp_path):
    """BrowserArtifactStore default base must be under CONFIG.igris_dir / browser / artifacts."""
    import igris.models.config as cfg_mod
    monkeypatch.setattr(cfg_mod.CONFIG, "project_root", tmp_path)
    from igris.core.browser_evidence import BrowserArtifactStore
    store = BrowserArtifactStore()
    expected = tmp_path / ".igris" / "browser" / "artifacts"
    assert store._base == expected, (
        f"Expected {expected}, got {store._base}"
    )


def test_browser_evidence_explicit_base_dir_takes_precedence(tmp_path):
    """When base_dir is passed, igris_dir fallback must not be used."""
    explicit = str(tmp_path / "custom_browser")
    from igris.core.browser_evidence import BrowserArtifactStore
    store = BrowserArtifactStore(base_dir=explicit)
    assert store._base == Path(explicit)
    assert ".igris" not in str(store._base)
