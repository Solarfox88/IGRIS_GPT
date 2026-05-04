# Teacher Governance

The teacher module provides oversight of agent decisions.

## Payload

`build_teacher_payload()` assembles a rich context including:
- Recent tasks and family counts
- Saturated and blocked families
- Duplicate detection results
- Last test result and execution report
- Required strategy shift
- Policy text

## Assignment Validation

`validate_teacher_assignment(assignment, history)` checks:

1. **Saturation**: If the selected family is saturated and no concrete differentiator
   is provided, the assignment is rejected.
2. **Differentiator quality**: Short or empty differentiators are rejected.
3. **Observation loops**: If too many recent tasks are observation-like and the new
   task is also observation-like, it's rejected.
4. **Success criteria**: Required on every assignment.

## Assignment Schema

```json
{
  "diagnosis": "Tests are failing",
  "selected_family": "testing",
  "why_this_family": "Need to verify fixes",
  "differentiator": "Focus on integration tests for A2A module",
  "task_title": "Run A2A integration tests",
  "task_description": "Execute tests in test_a2a_*.py",
  "success_criteria": ["All A2A tests pass"],
  "safe_command_ids": ["run_tests"],
  "expected_next_state": "Tests green",
  "fallback_if_blocked": "Review test output manually"
}
```

## Remediation

`propose_remediation_task(payload)` suggests a family shift when the current
strategy is stuck. If `required_strategy_shift` is set, the remediation will
target that family.
