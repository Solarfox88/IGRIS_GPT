# Bridge Rollout Modes & Feature Flags — #881
## EPIC #880 Mission Brain Controlled Bridge Rollout Plan

| mode | computes | emits_to_reports | is_gate |
|------|----------|-----------------|---------|
| disabled | False | False | False |
| shadow_only | True | False | False |
| diagnostic_only | True | True | False |

## Invariants

- is_gate is ALWAYS False
- default_enabled is ALWAYS False
- bridge output is ADDITIVE — never replaces existing fields
- loop decision is NEVER derived from bridge output

## Evaluation: passed
