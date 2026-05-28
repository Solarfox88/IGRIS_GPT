# Mission Brain Rollback Simulation — #838

- total_cases: 3
- wrapper_effective_count: 2
- auto_rollback_count: 1
- manual_force_count: 1

## Cases
- manual_force_wrapper: effective_mode=wrapper, reason=manual_force_wrapper_mode
- risky_auto_rollback: effective_mode=wrapper, reason=risky_mismatch_guardrail
- safe_keep_shadow: effective_mode=shadow, reason=no_guardrail_trigger
