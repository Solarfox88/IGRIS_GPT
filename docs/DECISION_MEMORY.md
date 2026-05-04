# Decision Memory & Failure Memory

## Overview

The Decision Memory system stores structured decision events, failure events, saturation markers, and remediation attempts. Unlike simple logs, this memory is **queryable** and **influences reasoning** — the teacher payload and task selection actively consult memory constraints to avoid repeating mistakes.

## What It Does

- **Record decisions**: Track what was decided and why
- **Record failures**: Track what failed and the reason
- **Record saturation**: Mark families as saturated to prevent loops
- **Record remediation attempts**: Track fix attempts and their outcomes
- **Query constraints**: Get a summary of what to avoid
- **Influence teacher**: Memory constraints are included in teacher payload
- **Influence task selection**: Saturated/failed families are blocked from selection

## What It Does NOT Do

- No automatic execution based on memory
- No LLM-based reasoning over memory (deterministic queries)
- No automatic deletion of memory events
- No cross-session memory (persisted per project in `.igris/memory/`)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/memory/decisions` | Recent decision events |
| `GET` | `/api/memory/failures` | Recent failure events |
| `GET` | `/api/memory/saturation` | Saturated families + constraints |
| `POST` | `/api/memory/events` | Record a new memory event |

### POST /api/memory/events Body

```json
{
  "event_type": "decision|failure|saturation|remediation",
  "title": "What happened",
  "family": "code|test|fix|...",
  "description": "Details",
  "outcome": "success|failure|blocked|pending",
  "reason": "Why",
  "task_id": "optional-task-id"
}
```

## Memory Constraints

The `explain_memory_constraints()` function returns:

```json
{
  "saturated_families": ["testing"],
  "recently_failed_families": {"code": 3},
  "avoid_families": ["testing", "code"],
  "recent_failure_count": 5,
  "recent_decision_count": 10,
  "remediation_count": 2,
  "recommendation": "Avoid families: testing, code"
}
```

## Integration

### Teacher Payload

`build_teacher_payload()` now includes:
- `memory_constraints`: full constraints object
- `memory_avoid_families`: list of families to avoid

### Task Selection

`select_next_task()` now merges memory-blocked families with explicitly blocked families, preventing selection of tasks in saturated or repeatedly-failing families.

### should_avoid_family()

Returns `True` if:
- Family is recorded as saturated, OR
- Family has 3+ recent failures

## Persistence

Events are stored as JSON in `.igris/memory/` (git-ignored):
- `decisions.json`
- `failures.json`
- `saturations.json`
- `remediations.json`

## Safety

- All text (title, description, reason) is redacted for secrets before storage
- No secrets appear in API responses
- Timeline events are logged for every memory event
- No automatic execution triggered by memory state

## UI

The **Memory** tab (14th tab) shows:
- Current constraints and recommendation
- Recent decisions with outcome badges
- Recent failures with family tags
- Form to record new events (decision/failure/saturation/remediation)
