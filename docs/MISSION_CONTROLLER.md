# Mission Controller — Epic #40

Persistent, long-running mission orchestration for IGRIS_GPT.

## Overview

The Mission Controller manages the complete lifecycle of autonomous missions:

```
create → plan → execute → observe → replan → verify → report
```

Missions survive restarts, prevent duplicate execution, support pause/resume,
and always produce an explainable state + final report.

## Mission Schema

```json
{
  "id": "mission-abc123def456",
  "title": "Add logging feature",
  "goal": "Add structured logging to the API layer",
  "description": "...",
  "status": "executing",
  "workspace": "/home/user/project",
  "target_hosts": [],
  "constraints": ["no force push", "no auto-merge"],
  "success_criteria": ["Tests pass", "Feature documented"],
  "risk_level": "low",
  "plan": [...],
  "tasks": [...],
  "artifacts": [...],
  "rollback_plan": "revert last commit",
  "current_step": 2,
  "total_steps": 5,
  "final_report": null,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T01:00:00Z",
  "trace_id": "trace-abc12345",
  "paused_at": null,
  "blocked_reason": null,
  "execution_log": [...]
}
```

## Mission Statuses

| Status | Description |
|--------|-------------|
| `created` | Mission created, not yet planned |
| `planning` | Plan generation in progress |
| `planned` | Plan ready, not yet executing |
| `executing` | Currently executing steps |
| `blocked` | Blocked (3 consecutive failures or manual block) |
| `verifying` | All steps done, checking success criteria |
| `paused` | Manually paused, can be resumed |
| `done` | Successfully completed |
| `failed` | Failed verification |

## API Endpoints

### CRUD

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/controller/missions` | Create a mission |
| `GET` | `/api/controller/missions` | List all missions |
| `GET` | `/api/controller/missions/{id}` | Get mission details |

### Lifecycle

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/controller/missions/{id}/plan` | Generate plan |
| `POST` | `/api/controller/missions/{id}/execute-next` | Execute next step |
| `POST` | `/api/controller/missions/{id}/report-outcome` | Report step result |
| `POST` | `/api/controller/missions/{id}/pause` | Pause mission |
| `POST` | `/api/controller/missions/{id}/resume` | Resume mission |
| `POST` | `/api/controller/missions/{id}/block` | Block mission |
| `POST` | `/api/controller/missions/{id}/unblock` | Unblock mission |
| `POST` | `/api/controller/missions/{id}/verify` | Verify success criteria |

### Inspection

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/controller/missions/{id}/explain` | Explain current state |
| `GET` | `/api/controller/missions/{id}/report` | Generate final report |
| `GET` | `/api/controller/missions/{id}/context` | Reconstruct context |
| `POST` | `/api/controller/missions/{id}/artifacts` | Add artifact |

## Lifecycle Example

```bash
# 1. Create mission
curl -X POST /api/controller/missions \
  -d '{"title": "Fix login bug", "goal": "Fix the auth timeout issue"}'

# 2. Generate plan
curl -X POST /api/controller/missions/{id}/plan

# 3. Execute steps
curl -X POST /api/controller/missions/{id}/execute-next

# 4. Report outcome
curl -X POST /api/controller/missions/{id}/report-outcome \
  -d '{"step_index": 0, "outcome": "success", "detail": "Analysis complete"}'

# 5. Verify
curl -X POST /api/controller/missions/{id}/verify

# 6. Final report
curl /api/controller/missions/{id}/report
```

## Safety Features

- **Duplicate execution guard**: Cannot re-execute a step already in progress
- **Auto-block on 3 failures**: Three consecutive step failures block the mission
- **Pause/resume**: Manual control over execution
- **Context reconstruction**: After restart, reconstructs full state
- **Execution log**: Every state change is logged with timestamp
- **Trace ID**: Every mission has a unique trace ID for observability
- **Secret redaction**: All output is redacted via `safety.redact_secrets()`

## Persistence

Missions are stored as JSON in `.igris/controller/missions/`:

```
.igris/controller/missions/
  mission-abc123.json
  mission-def456.json
```

## Final Report Schema

```json
{
  "mission_id": "mission-abc123",
  "title": "Fix login bug",
  "goal": "...",
  "status": "done",
  "trace_id": "trace-abc12345",
  "total_tasks": 3,
  "completed_tasks": 3,
  "failed_tasks": 0,
  "success_rate": 1.0,
  "artifacts": [...],
  "execution_summary": [
    {"title": "Analyze", "status": "done", "family": "analyze"},
    {"title": "Implement", "status": "done", "family": "code"},
    {"title": "Test", "status": "done", "family": "test"}
  ]
}
```

## File Layout

```
igris/core/mission_controller.py   — Controller logic
tests/test_mission_controller.py   — 61 tests
docs/MISSION_CONTROLLER.md         — This file
```
