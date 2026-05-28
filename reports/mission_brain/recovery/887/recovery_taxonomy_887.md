# Recovery Recommendation Taxonomy — #887
## EPIC #886

| combined_status | action | confidence | auto_executable |
|-----------------|--------|------------|-----------------|
| blocked_goal_failed | unblock_then_diagnose | medium | False |
| blocked_with_goal_progress | unblock_then_continue | high | False |
| completed | mark_complete | high | False |
| goal_complete_run_blocked | review_anomaly | low | False |
| goal_complete_run_failed | review_anomaly | low | False |
| hard_failure | diagnose_failure | high | False |
| insufficient_context | request_context | low | False |
| technical_failure_with_goal_progress | continue_from_partial_progress | high | False |
| technical_success_but_goal_incomplete | rerun_with_differentiator | medium | False |

## Invariants

- auto_executable is ALWAYS False
- advisory_only is ALWAYS True
- safe_next_action is non-empty for all templates

## Evaluation: passed
