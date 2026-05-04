# Decision Reports per Loop Cycle

## Overview

Every loop step generates a structured JSON decision report capturing the
full context of the decision: project state, task selection, safety checks,
outcome, memory constraints, and next action recommendation.

Reports are stored under `.igris/reports/decisions/` (git-ignored).

## Report Structure

```json
{
  "id": "abc123def456",
  "timestamp": "2024-01-01T00:00:00Z",
  "step_number": 1,
  "project_snapshot": {
    "task_counts": {"total": 10, "pending": 3, "running": 1, "completed": 5, "blocked": 1},
    "cooling_down_families": [],
    "critical_families": []
  },
  "selected_task": {"id": 1, "title": "...", ...},
  "rejected_candidates": [{"task_id": 2, "title": "...", "score": -50, "why": "..."}],
  "selection_source": "fallback",
  "selection_summary": "Selected task #1...",
  "safety_decisions": [{"check": "allowlist", "passed": true}],
  "action_type": "execute_command",
  "action_detail": "ran tests",
  "outcome": "success",
  "outcome_reason": "",
  "memory_constraints": {"saturated_families": [], "avoid_families": []},
  "teacher_recommendation": null,
  "next_action": "continue",
  "next_action_reason": ""
}
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/decision-reports` | GET | List recent decision reports |
| `/api/decision-reports/{id}` | GET | Get a specific report |
| `/api/decision-reports` | POST | Create a new decision report |

### POST /api/decision-reports

```json
{
  "step_number": 1,
  "action_type": "execute_command",
  "action_detail": "ran tests",
  "outcome": "success",
  "outcome_reason": "",
  "next_action": "continue",
  "safety_decisions": [{"check": "rate_limit", "passed": true}]
}
```

## Integration

- **Loop**: Each loop step should create a decision report
- **Selection Explain**: Reports include full candidate scoring
- **Memory**: Reports include current memory constraints
- **Project State**: Reports include cooldown/recovery snapshot
- **Safety**: All report content is secret-redacted

## Safety

- All text fields are secret-redacted before persistence
- Reports stored in git-ignored directory
- Read-only query endpoints
