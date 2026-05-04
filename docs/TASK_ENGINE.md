# Task Engine

The persistent task engine stores tasks as JSON files under `.igris/tasks/`.

## Task Schema

```json
{
  "id": 1,
  "uuid": "abc-123",
  "title": "Run pytest",
  "description": "Execute the test suite",
  "family": "testing",
  "status": "pending",
  "priority": 0,
  "risk": "low",
  "source": "user",
  "success_criteria": ["all tests pass"],
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "result": null,
  "blocked_reason": null,
  "semantic_fingerprint": "abc123"
}
```

## Status Transitions

- `pending` → `running` → `completed`
- `pending` → `blocked`
- `running` → `blocked`

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/tasks` | GET | List all tasks |
| `/api/tasks` | POST | Create task |
| `/api/tasks/{id}` | GET | Get task |
| `/api/tasks/{id}/complete` | POST | Mark complete |
| `/api/tasks/{id}/block` | POST | Block task |

## Timeline

Events are stored in `.igris/timeline/` as numbered JSON files.
`/api/agent/timeline` returns the most recent 50 events.

## Persistence

Tasks survive server restarts. The `TaskEngine` reloads all JSON files from disk
on initialization.

## Anti-Loop Integration

Tasks carry a `semantic_fingerprint` and `family`. The engine checks for
saturation and duplication before scheduling via `select_next_task()`.
