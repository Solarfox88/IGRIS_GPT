import os
from igris.models.config import Config


def test_config_defaults():
    # Ensure defaults are loaded when no environment variables are set
    os.environ.pop("LOCAL_LLM_PROVIDER", None)
    cfg = Config.load()
    assert cfg.local_llm.provider == "ollama"
    assert cfg.local_llm.model == "phi4-mini"
    assert cfg.fallback_llm.provider == "deepseek"
    assert cfg.mission_brain_integration.enabled is False
    assert cfg.mission_brain_integration.mode == "shadow"
    assert cfg.mission_brain_integration.compare_with_current_loop is True
    assert cfg.mission_brain_integration.telemetry_enabled is True
    assert cfg.mission_brain_integration.rollback_to_wrapper_on_guardrail is True
    assert cfg.mission_brain_integration.auto_rollback_on_risky_mismatch is True
    assert cfg.mission_brain_integration.force_wrapper_mode is False
    assert cfg.mission_brain_integration.allow_enforce_mode is False


def test_mission_brain_integration_env_override(monkeypatch):
    monkeypatch.setenv("IGRIS_MB_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("IGRIS_MB_INTEGRATION_MODE", "wrapper")
    monkeypatch.setenv("IGRIS_MB_COMPARE_WITH_CURRENT_LOOP", "false")
    monkeypatch.setenv("IGRIS_MB_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("IGRIS_MB_ROLLBACK_TO_WRAPPER_ON_GUARDRAIL", "false")
    monkeypatch.setenv("IGRIS_MB_AUTO_ROLLBACK_ON_RISKY_MISMATCH", "false")
    monkeypatch.setenv("IGRIS_MB_FORCE_WRAPPER_MODE", "true")
    monkeypatch.setenv("IGRIS_MB_ALLOW_ENFORCE_MODE", "true")
    cfg = Config.load()
    assert cfg.mission_brain_integration.enabled is True
    assert cfg.mission_brain_integration.mode == "wrapper"
    assert cfg.mission_brain_integration.compare_with_current_loop is False
    assert cfg.mission_brain_integration.telemetry_enabled is False
    assert cfg.mission_brain_integration.rollback_to_wrapper_on_guardrail is False
    assert cfg.mission_brain_integration.auto_rollback_on_risky_mismatch is False
    assert cfg.mission_brain_integration.force_wrapper_mode is True
    assert cfg.mission_brain_integration.allow_enforce_mode is True
