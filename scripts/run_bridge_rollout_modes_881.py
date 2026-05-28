#!/usr/bin/env python3
"""Mission Brain EPIC #880 — #881: Define bridge rollout modes and feature flags.

Validates the BridgeConfig and rollout mode system defined in bridge_config.py.

Usage:
    python scripts/run_bridge_rollout_modes_881.py
"""
from __future__ import annotations

import json
from pathlib import Path

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


def main() -> int:
    # Validate defaults — bridge must be off by default
    assert not DEFAULT_BRIDGE_CONFIG.enabled, "STOP: default config is enabled"
    assert DEFAULT_BRIDGE_CONFIG.rollout_mode == ROLLOUT_MODE_DISABLED
    assert not DEFAULT_BRIDGE_CONFIG.should_compute
    assert not DEFAULT_BRIDGE_CONFIG.should_emit
    assert not DEFAULT_BRIDGE_CONFIG.is_gate

    # shadow config
    shadow = make_shadow_config()
    assert shadow.enabled
    assert shadow.should_compute
    assert not shadow.should_emit
    assert not shadow.is_gate

    # diagnostic config
    diag = make_diagnostic_config()
    assert diag.enabled
    assert diag.should_compute
    assert diag.should_emit
    assert not diag.is_gate

    # env-based loading (no env vars → default off)
    env_config = config_from_env()
    assert not env_config.enabled, "STOP: env config enabled without env vars"

    # All 3 modes enumerated
    assert ROLLOUT_MODES == frozenset({ROLLOUT_MODE_DISABLED, ROLLOUT_MODE_SHADOW_ONLY, ROLLOUT_MODE_DIAGNOSTIC_ONLY})

    # is_gate always False for all modes
    for mode in ROLLOUT_MODES:
        cfg = BridgeConfig(enabled=True, rollout_mode=mode)
        assert not cfg.is_gate, f"STOP: is_gate=True for mode={mode}"

    rollout_modes_doc = [
        {
            "mode": ROLLOUT_MODE_DISABLED,
            "computes": False, "emits_to_reports": False, "is_gate": False,
            "description": "Bridge completely off. Zero overhead. Default state.",
        },
        {
            "mode": ROLLOUT_MODE_SHADOW_ONLY,
            "computes": True, "emits_to_reports": False, "is_gate": False,
            "description": "Bridge computes but output not emitted to reports.",
        },
        {
            "mode": ROLLOUT_MODE_DIAGNOSTIC_ONLY,
            "computes": True, "emits_to_reports": True, "is_gate": False,
            "description": "Bridge computes and emits to report diagnostics section. Informational only.",
        },
    ]

    feature_flags = [
        {"name": "BRIDGE_DIAGNOSTIC_ENABLED", "default": "false", "env_var": "BRIDGE_DIAGNOSTIC_ENABLED"},
        {"name": "BRIDGE_ROLLOUT_MODE", "default": ROLLOUT_MODE_DISABLED, "env_var": "BRIDGE_ROLLOUT_MODE"},
        {"name": "BRIDGE_LOG_ENABLED", "default": "false", "env_var": "BRIDGE_LOG_ENABLED"},
    ]

    result = {
        "epic": 880, "subissue": 881,
        "title": "Bridge Rollout Modes and Feature Flags",
        "default_state": "disabled", "default_enabled": False, "default_is_gate": False,
        "rollout_modes": rollout_modes_doc,
        "feature_flags": feature_flags,
        "rollback_procedure": {
            "steps": [
                "Set BRIDGE_DIAGNOSTIC_ENABLED=false (or unset)",
                "Restart service — bridge off, zero overhead",
                "Loop behavior identical to pre-bridge state",
            ],
            "reversible": True, "data_loss": False, "loop_behavior_changed": False,
            "time_to_rollback": "immediate (env var + restart)",
        },
        "invariants": [
            "is_gate is ALWAYS False",
            "default_enabled is ALWAYS False",
            "bridge output is ADDITIVE — never replaces existing fields",
            "loop decision is NEVER derived from bridge output",
        ],
        "guardrails": {
            "default_off": True, "feature_flag_required": True,
            "no_mandatory_gate": True, "no_enable_by_default": True,
            "rollback_reversible": True,
        },
        "evaluation": "passed", "stop_reason": None, "next_subissue": 882,
    }

    out_dir = Path("reports/mission_brain/rollout/881")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bridge_rollout_modes_881.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    md = [
        "# Bridge Rollout Modes & Feature Flags — #881",
        "## EPIC #880 Mission Brain Controlled Bridge Rollout Plan",
        "",
        "| mode | computes | emits_to_reports | is_gate |",
        "|------|----------|-----------------|---------|",
    ]
    for m in rollout_modes_doc:
        md.append(f"| {m['mode']} | {m['computes']} | {m['emits_to_reports']} | {m['is_gate']} |")
    md += ["", "## Invariants", ""]
    for inv in result["invariants"]:
        md.append(f"- {inv}")
    md += ["", "## Evaluation: passed"]
    (out_dir / "bridge_rollout_modes_881.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "subissue": 881, "default_enabled": False,
        "rollout_modes_count": len(rollout_modes_doc),
        "is_gate_always_false": True, "rollback_reversible": True,
        "evaluation": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
