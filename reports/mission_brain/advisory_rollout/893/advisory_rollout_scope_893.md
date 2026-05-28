# Advisory Rollout Scope — #893
## EPIC #892 Mission Brain Advisory Recovery Rollout

## Scope

- Target run statuses: ['blocked', 'failed']
- Target report types: ['diagnostic', 'mission_execution', 'shadow_cycle']
- include_passed_goal_incomplete: False (conservative default)

## Feature Flag

- Env var: `ADVISORY_ROLLOUT_ENABLED`
- Default: **OFF**
- Set to `true` to enable.

## Shadow data cycles in scope: 30/30

## Guardrails

- default_off: ✅  |  no_mandatory_gate: ✅  |  no_auto_execution: ✅

## Evaluation: passed
