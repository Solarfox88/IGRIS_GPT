"""Tests for #881 — BridgeConfig feature flags and rollout modes."""
from __future__ import annotations

import os
import pytest

from igris.agent.mission.bridge_config import (
    DEFAULT_BRIDGE_CONFIG,
    ROLLOUT_MODE_DIAGNOSTIC_ONLY,
    ROLLOUT_MODE_DISABLED,
    ROLLOUT_MODE_SHADOW_ONLY,
    ROLLOUT_MODES,
    BridgeConfig,
    config_from_env,
    make_diagnostic_config,
    make_shadow_config,
)


class TestDefaultConfig:
    def test_default_enabled_false(self):
        assert DEFAULT_BRIDGE_CONFIG.enabled is False

    def test_default_mode_disabled(self):
        assert DEFAULT_BRIDGE_CONFIG.rollout_mode == ROLLOUT_MODE_DISABLED

    def test_default_should_compute_false(self):
        assert not DEFAULT_BRIDGE_CONFIG.should_compute

    def test_default_should_emit_false(self):
        assert not DEFAULT_BRIDGE_CONFIG.should_emit

    def test_default_is_gate_false(self):
        assert DEFAULT_BRIDGE_CONFIG.is_gate is False


class TestRolloutModes:
    def test_three_modes_defined(self):
        assert len(ROLLOUT_MODES) == 3

    def test_disabled_mode_present(self):
        assert ROLLOUT_MODE_DISABLED in ROLLOUT_MODES

    def test_shadow_mode_present(self):
        assert ROLLOUT_MODE_SHADOW_ONLY in ROLLOUT_MODES

    def test_diagnostic_mode_present(self):
        assert ROLLOUT_MODE_DIAGNOSTIC_ONLY in ROLLOUT_MODES

    def test_disabled_no_compute(self):
        cfg = BridgeConfig(enabled=True, rollout_mode=ROLLOUT_MODE_SHADOW_ONLY)
        cfg2 = BridgeConfig(enabled=True, rollout_mode=ROLLOUT_MODE_DISABLED)
        # enabled=True + mode=disabled → mode auto-corrected to shadow_only
        assert cfg2.rollout_mode == ROLLOUT_MODE_SHADOW_ONLY

    def test_shadow_computes_not_emits(self):
        cfg = make_shadow_config()
        assert cfg.should_compute
        assert not cfg.should_emit

    def test_diagnostic_computes_and_emits(self):
        cfg = make_diagnostic_config()
        assert cfg.should_compute
        assert cfg.should_emit

    @pytest.mark.parametrize("mode", list(ROLLOUT_MODES))
    def test_is_gate_always_false(self, mode: str):
        cfg = BridgeConfig(enabled=True, rollout_mode=mode)
        assert cfg.is_gate is False


class TestShadowConfig:
    def test_enabled(self):
        assert make_shadow_config().enabled is True

    def test_mode(self):
        assert make_shadow_config().rollout_mode == ROLLOUT_MODE_SHADOW_ONLY

    def test_no_emit(self):
        assert not make_shadow_config().should_emit

    def test_computes(self):
        assert make_shadow_config().should_compute


class TestDiagnosticConfig:
    def test_enabled(self):
        assert make_diagnostic_config().enabled is True

    def test_mode(self):
        assert make_diagnostic_config().rollout_mode == ROLLOUT_MODE_DIAGNOSTIC_ONLY

    def test_emits(self):
        assert make_diagnostic_config().should_emit

    def test_is_gate_false(self):
        assert make_diagnostic_config().is_gate is False


class TestConfigFromEnv:
    def test_no_env_vars_gives_default_disabled(self, monkeypatch):
        monkeypatch.delenv("BRIDGE_DIAGNOSTIC_ENABLED", raising=False)
        cfg = config_from_env()
        assert not cfg.enabled

    def test_enabled_true_gives_diagnostic(self, monkeypatch):
        monkeypatch.setenv("BRIDGE_DIAGNOSTIC_ENABLED", "true")
        monkeypatch.delenv("BRIDGE_ROLLOUT_MODE", raising=False)
        cfg = config_from_env()
        assert cfg.enabled
        assert cfg.should_emit

    def test_enabled_false_string_stays_disabled(self, monkeypatch):
        monkeypatch.setenv("BRIDGE_DIAGNOSTIC_ENABLED", "false")
        cfg = config_from_env()
        assert not cfg.enabled

    def test_invalid_mode_falls_back_to_diagnostic(self, monkeypatch):
        monkeypatch.setenv("BRIDGE_DIAGNOSTIC_ENABLED", "true")
        monkeypatch.setenv("BRIDGE_ROLLOUT_MODE", "invalid_xyz")
        cfg = config_from_env()
        assert cfg.rollout_mode == ROLLOUT_MODE_DIAGNOSTIC_ONLY


class TestBridgeConfigToDict:
    def test_to_dict_has_required_fields(self):
        d = make_diagnostic_config().to_dict()
        for field in ("enabled", "rollout_mode", "should_compute", "should_emit", "is_gate"):
            assert field in d

    def test_to_dict_is_gate_false(self):
        assert make_diagnostic_config().to_dict()["is_gate"] is False


class TestInvalidConfig:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            BridgeConfig(enabled=False, rollout_mode="totally_invalid_mode")
