"""Bridge Rollout Configuration — EPIC #880 (#881).

Defines the feature flag system and rollout modes for the Goal/Run Status Bridge.

Design constraints:
  - BRIDGE_DIAGNOSTIC_ENABLED defaults to False (off by default).
  - No code path changes the loop's operational decision.
  - Bridge enrichment is additive: it can only ADD diagnostic fields to reports.
  - Rollback = flip flag to False → bridge output disappears, loop unchanged.
  - No mandatory gate: the bridge never blocks or overrides a loop decision.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Rollout modes
# ---------------------------------------------------------------------------

ROLLOUT_MODE_DISABLED        = "disabled"
ROLLOUT_MODE_SHADOW_ONLY     = "shadow_only"
ROLLOUT_MODE_DIAGNOSTIC_ONLY = "diagnostic_only"

ROLLOUT_MODES: frozenset = frozenset({
    ROLLOUT_MODE_DISABLED,
    ROLLOUT_MODE_SHADOW_ONLY,
    ROLLOUT_MODE_DIAGNOSTIC_ONLY,
})

EMIT_MODES: frozenset    = frozenset({ROLLOUT_MODE_DIAGNOSTIC_ONLY})
COMPUTE_MODES: frozenset = frozenset({ROLLOUT_MODE_SHADOW_ONLY, ROLLOUT_MODE_DIAGNOSTIC_ONLY})


@dataclass(frozen=True)
class BridgeConfig:
    """Runtime configuration for the Goal/Run Status Bridge.

    Attributes:
        enabled: Master switch. Default: False. Never True unless explicitly set.
        rollout_mode: "disabled" | "shadow_only" | "diagnostic_only"
        log_enabled: If True, bridge output is logged even when not emitted.
        max_latency_budget_ms: Max allowed bridge computation time (ms).
    """
    enabled: bool = False
    rollout_mode: str = ROLLOUT_MODE_DISABLED
    log_enabled: bool = False
    max_latency_budget_ms: int = 50

    def __post_init__(self) -> None:
        if self.rollout_mode not in ROLLOUT_MODES:
            raise ValueError(
                f"Invalid rollout_mode {self.rollout_mode!r}. "
                f"Must be one of: {sorted(ROLLOUT_MODES)}"
            )
        if self.enabled and self.rollout_mode == ROLLOUT_MODE_DISABLED:
            object.__setattr__(self, "rollout_mode", ROLLOUT_MODE_SHADOW_ONLY)

    @property
    def should_compute(self) -> bool:
        return self.enabled and self.rollout_mode in COMPUTE_MODES

    @property
    def should_emit(self) -> bool:
        return self.enabled and self.rollout_mode in EMIT_MODES

    @property
    def is_gate(self) -> bool:
        return False  # NEVER a gate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rollout_mode": self.rollout_mode,
            "log_enabled": self.log_enabled,
            "max_latency_budget_ms": self.max_latency_budget_ms,
            "should_compute": self.should_compute,
            "should_emit": self.should_emit,
            "is_gate": self.is_gate,
        }


DEFAULT_BRIDGE_CONFIG = BridgeConfig(
    enabled=False,
    rollout_mode=ROLLOUT_MODE_DISABLED,
    log_enabled=False,
)


def make_diagnostic_config(log_enabled: bool = False) -> BridgeConfig:
    """Create a diagnostic_only config (enabled, emits to reports). Requires explicit opt-in."""
    return BridgeConfig(enabled=True, rollout_mode=ROLLOUT_MODE_DIAGNOSTIC_ONLY, log_enabled=log_enabled)


def make_shadow_config(log_enabled: bool = False) -> BridgeConfig:
    """Create a shadow_only config (enabled, computes but doesn't emit)."""
    return BridgeConfig(enabled=True, rollout_mode=ROLLOUT_MODE_SHADOW_ONLY, log_enabled=log_enabled)


def config_from_env() -> BridgeConfig:
    """Load bridge config from environment variables. Default: disabled."""
    raw_enabled = os.environ.get("BRIDGE_DIAGNOSTIC_ENABLED", "").strip().lower()
    enabled = raw_enabled in ("true", "1", "yes")
    if not enabled:
        return DEFAULT_BRIDGE_CONFIG
    raw_mode = os.environ.get("BRIDGE_ROLLOUT_MODE", ROLLOUT_MODE_DIAGNOSTIC_ONLY).strip().lower()
    if raw_mode not in ROLLOUT_MODES:
        raw_mode = ROLLOUT_MODE_DIAGNOSTIC_ONLY
    raw_log = os.environ.get("BRIDGE_LOG_ENABLED", "").strip().lower()
    return BridgeConfig(
        enabled=True,
        rollout_mode=raw_mode,
        log_enabled=raw_log in ("true", "1", "yes"),
    )
