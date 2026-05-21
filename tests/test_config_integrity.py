"""
Regression guard for igris/models/config.py structural integrity.

These tests protect against modifications that silently remove required
fields (e.g. project_root) or break CONFIG loading and TaskEngine startup.
The supervisor on issue #12 repeatedly broke these invariants.
"""
from pathlib import Path


def test_config_project_root_exists():
    """CONFIG.project_root must always be accessible as a Path."""
    from igris.models.config import CONFIG
    assert hasattr(CONFIG, "project_root"), "CONFIG.project_root was removed"
    assert isinstance(CONFIG.project_root, Path)


def test_config_workspace_root_exists():
    from igris.models.config import CONFIG
    assert hasattr(CONFIG, "workspace_root")
    assert isinstance(CONFIG.workspace_root, Path)


def test_config_local_llm_default_is_phi4mini():
    """Default local LLM must be phi4-mini (normalised)."""
    import os
    from igris.models.config import Config
    env_backup = os.environ.pop("LOCAL_LLM_MODEL", None)
    try:
        cfg = Config.load()
        assert cfg.local_llm.model == "phi4-mini", (
            f"Default local LLM is {cfg.local_llm.model!r}, expected 'phi4-mini'"
        )
    finally:
        if env_backup is not None:
            os.environ["LOCAL_LLM_MODEL"] = env_backup


def test_config_local_llm_provider_default_is_ollama():
    import os
    from igris.models.config import Config
    env_backup = os.environ.pop("LOCAL_LLM_PROVIDER", None)
    try:
        cfg = Config.load()
        assert cfg.local_llm.provider == "ollama"
    finally:
        if env_backup is not None:
            os.environ["LOCAL_LLM_PROVIDER"] = env_backup


def test_normalize_model_name_aliases():
    from igris.models.config import normalize_model_name
    assert normalize_model_name("phi4mini") == "phi4-mini"
    assert normalize_model_name("phi4_mini") == "phi4-mini"
    assert normalize_model_name("phi-4-mini") == "phi4-mini"
    assert normalize_model_name("phi4") == "phi4-mini"
    assert normalize_model_name("phi4-mini") == "phi4-mini"


def test_task_engine_instantiates():
    """TaskEngine() must not crash — it depends on CONFIG.project_root."""
    from igris.core.task_engine import TaskEngine
    engine = TaskEngine()
    assert engine is not None
