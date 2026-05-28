# Post-subissue Evaluation — #838

Status: `passed`

## What changed
- Added explicit rollback/fallback policy module:
  - `igris/agent/mission/rollback_policy.py`
- Extended Mission Brain integration config with rollback controls:
  - `auto_rollback_on_risky_mismatch`
  - `force_wrapper_mode`
- Integrated wrapper policy evaluation into shadow hook path in reasoning loop.
- Persisted wrapper-policy decisions to:
  - `.igris/mission_brain/shadow/rollback_policy_decisions.jsonl`
- Added rollback simulation runner:
  - `scripts/run_mission_brain_rollback_simulation_838.py`

## Rollback controls now supported
- Manual rollback:
  - `IGRIS_MB_FORCE_WRAPPER_MODE=true`
- Automatic rollback guardrail:
  - risky mismatch class -> wrapper fallback
  - shadow execution error -> wrapper fallback

## Simulation artifact
- `reports/mission_brain/integration/838/rollback_simulation_838.json`
- `reports/mission_brain/integration/838/rollback_simulation_838.md`

Summary:
- total_cases: 3
- wrapper_effective_count: 2
- auto_rollback_count: 1
- manual_force_count: 1

## Verification executed
- `.venv/bin/pytest -q tests/test_config.py tests/test_mission_shadow_integration.py tests/test_mission_shadow_comparison.py tests/test_mission_rollback_policy.py tests/test_agent_reasoning_loop.py`
  - `61 passed`
- `.venv/bin/python scripts/run_mission_brain_rollback_simulation_838.py`
  - `status: passed`

## Next-subissue propagation (#839)
- Confirmed unchanged.
- #839 should consolidate readiness with:
  - shadow comparison metrics (#837),
  - rollback simulation outcomes (#838),
  - explicit go/no-go decision constrained to non-default rollout recommendation.
