# Goal/Run Status Bridge Model — #875
## EPIC #874 Mission Brain Goal/Run Status Bridge

## Status Enumerations

### RunStatus (loop, run-level, binary)
  `blocked, failed, passed, unknown`

### GoalStatus (Mission Brain, goal-level, graded)
  `completed, failed, partial, unknown`

### CombinedStatus (bridge output)
  `blocked_goal_failed, blocked_with_goal_progress, completed, goal_complete_run_blocked, goal_complete_run_failed, hard_failure, insufficient_context, technical_failure_with_goal_progress, technical_success_but_goal_incomplete`

## Mapping Table

| run_status | goal_status | combined_status | next_action_recommendation |
|------------|-------------|-----------------|---------------------------|
| blocked | completed | goal_complete_run_blocked | review_anomaly |
| blocked | failed | blocked_goal_failed | unblock_then_diagnose |
| blocked | partial | blocked_with_goal_progress | unblock_then_continue_from_partial |
| blocked | unknown | insufficient_context | request_context_or_planning |
| failed | completed | goal_complete_run_failed | review_anomaly |
| failed | failed | hard_failure | diagnose_failure |
| failed | partial | technical_failure_with_goal_progress | recover_or_continue_from_partial_progress |
| failed | unknown | insufficient_context | request_context_or_planning |
| passed | completed | completed | mark_mission_complete |
| passed | failed | technical_success_but_goal_incomplete | review_anomaly |
| passed | partial | technical_success_but_goal_incomplete | continue_mission_or_request_clarification |
| passed | unknown | insufficient_context | request_context_or_planning |
| unknown | completed | insufficient_context | request_context_or_planning |
| unknown | failed | insufficient_context | request_context_or_planning |
| unknown | partial | insufficient_context | request_context_or_planning |
| unknown | unknown | insufficient_context | request_context_or_planning |

## Design Constraints

- Bridge is observational/diagnostic only — not decisional by default
- Shadow mode only — does not modify loop behavior
- `combined=completed` only when `run=passed AND goal=completed`
- `goal=completed` with `run=failed/blocked` → anomaly review, not completed
- Mapping is deterministic and fully enumerated (4×4 = 16 pairs)

## Evaluation: passed
