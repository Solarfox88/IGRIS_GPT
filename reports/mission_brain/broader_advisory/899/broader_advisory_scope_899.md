# Broader Advisory Rollout Scope — #899
## EPIC #898

- Selected report types: ['diagnostic', 'mission_execution']
- Default run statuses: [failed]
- Blocked: pending validation (#900)
- monitoring_only=True by default

## Rollout Stages

| Stage | Name | Surfaces Advisory | Blocked |
|-------|------|-------------------|---------|
| 1 | monitoring_only_failed | False | False |
| 2 | validate_blocked | True | True |
| 3 | activate_selected_reports | True | True |
| 4 | controlled_monitoring | False | True |

## Evaluation: passed
