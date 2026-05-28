# Mission Brain Shadow Monitoring Protocol (Epic #845)

## Scope
This protocol defines how to observe Mission Brain in shadow mode on real loop
cycles without changing default loop behavior.

## Hard constraints
- Shadow mode only.
- No default behavior override.
- No irreversible integration.
- Feature flag remains off by default.
- Wrapper rollback/fallback path must remain active.
- No automatic promotion to default.

## Monitoring cycle record (per loop run)
Each observed cycle must capture:
- `cycle_id`
- `timestamp`
- `mission_brain_decision`
- `current_loop_decision`
- `agreement` (bool)
- `mismatch_class`
- `prevented_error_candidate` (bool)
- `risk_introduced_candidate` (bool)
- `potential_false_completed` (bool)
- `potential_critical_false_completed` (bool)
- `potential_false_partial` (bool)
- `potential_false_failed` (bool)
- `latency_overhead_ms`
- `cost_overhead_usd`
- `rollback_path_status` (`ok` | `degraded` | `failed`)
- `report_usefulness_score` (0.0-1.0)

## Batch aggregation
Each batch report must include the mandatory metrics schema defined in:
- `reports/mission_brain/shadow_monitoring/aggregate_metrics_schema.json`

## Stop conditions
Stop and request explicit confirmation if:
- `potential_critical_false_completed > 0`
- default loop behavior changes
- Mission Brain must become mandatory gate
- severe operational regression occurs
- operational overhead becomes excessive

## Allowed final decisions
- `keep shadow mode`
- `candidate for controlled rollout`
- `remediate again`
- `do not integrate`

Even if the decision is `candidate for controlled rollout`, do not activate
rollout in this epic.
