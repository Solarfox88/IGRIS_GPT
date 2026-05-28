# Controlled Integration Architecture and Flags (Issue #835)

## Scope
Define controlled Mission Brain integration points without changing current loop default behavior.

## Non-goals
- No irreversible switch to Mission Brain as default gate.
- No bypass/removal of current loop.
- No enforce mode activation in this phase.

## Integration model
1. Current loop remains source of truth for operational decisions.
2. Mission Brain runs in side-channel mode (`shadow` or `wrapper`) only.
3. Side-by-side telemetry captures:
   - current loop decision
   - Mission Brain decision
   - divergence markers
   - evidence depth summary
4. Rollback policy keeps wrapper fallback always available.

## Feature flags
Environment variables:
- `IGRIS_MB_INTEGRATION_ENABLED` (default: `false`)
- `IGRIS_MB_INTEGRATION_MODE` (default: `shadow`)
  - allowed values: `shadow`, `wrapper`, `enforce`
  - `enforce` is blocked unless `IGRIS_MB_ALLOW_ENFORCE_MODE=true`
- `IGRIS_MB_COMPARE_WITH_CURRENT_LOOP` (default: `true`)
- `IGRIS_MB_TELEMETRY_ENABLED` (default: `true`)
- `IGRIS_MB_ROLLBACK_TO_WRAPPER_ON_GUARDRAIL` (default: `true`)
- `IGRIS_MB_ALLOW_ENFORCE_MODE` (default: `false`)

## Safeguards
- Safety validator raises error if `IGRIS_MB_INTEGRATION_MODE=enforce` and allow flag is not enabled.
- Default config ships with:
  - integration disabled
  - shadow mode
  - enforce disallowed

## Telemetry schema (phase 1 shape)
Minimal telemetry record required by shadow-mode steps:
- `mission_id`
- `loop_decision`
- `mission_brain_decision`
- `decision_divergence` (bool)
- `quality_gate_passed`
- `satisfaction_gate_passed`
- `evidence_depth_summary`
- `timestamp`

## Next step propagation
Issue #836 will implement shadow-mode execution path and emit telemetry records
without influencing default loop actions.
