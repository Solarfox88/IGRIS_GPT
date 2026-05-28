# Advisory Rollout Integration — #894
## EPIC #892

**Test cases:** 5 | **All passed:** True

| run_status | goal_status | report_type | expected | got | match |
|------------|-------------|-------------|----------|-----|-------|
| failed | partial | mission_execution | True | True | True |
| blocked | partial | shadow_cycle | True | True | True |
| failed | failed | diagnostic | True | True | True |
| passed | completed | mission_execution | False | False | True |
| failed | partial | mission_execution | False | False | True |

## Evaluation: passed
