# A2A Artifacts + Long-Running Tasks

## Overview

Extends the A2A (Agent-to-Agent) protocol with artifact storage, richer task statuses, cancellation, and event tracking for long-running task patterns.

## Task Statuses

| Status | Description |
|--------|-------------|
| `submitted` | Task received, not yet started |
| `working` | Task actively being worked on |
| `input_required` | Task needs user/agent input to continue |
| `completed` | Task finished successfully (terminal) |
| `failed` | Task failed (terminal) |
| `canceled` | Task canceled (terminal) |

Terminal statuses (`completed`, `failed`, `canceled`) cannot be transitioned away from.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/a2a/store/tasks` | Create A2A task |
| `GET` | `/api/a2a/store/tasks` | List all A2A tasks |
| `GET` | `/api/a2a/store/tasks/{id}` | Get A2A task detail |
| `POST` | `/api/a2a/store/tasks/{id}/status` | Update task status |
| `GET` | `/api/a2a/tasks/{id}/artifacts` | List artifacts |
| `POST` | `/api/a2a/tasks/{id}/artifacts` | Add artifact |
| `POST` | `/api/a2a/tasks/{id}/cancel` | Cancel task |
| `GET` | `/api/a2a/tasks/{id}/events` | Get task events |

### POST /api/a2a/store/tasks

```json
{"title": "Analyze codebase", "description": "..."}
```

### POST /api/a2a/tasks/{id}/artifacts

```json
{"name": "report.md", "content": "# Analysis Report...", "mime_type": "text/markdown"}
```

## Artifacts

- Text-only for MVP (no binary uploads)
- Max size: 100 KB per artifact
- Content is redacted for secrets before storage
- Each artifact gets a unique ID

## Events

Every status change and artifact addition is logged as an event:

```json
{
  "type": "status_change",
  "status": "working",
  "timestamp": 1234567890.0,
  "detail": "Started processing"
}
```

## Safety

- Secret redaction on all text fields (title, description, content, detail)
- Size limit on artifacts (100 KB)
- No path traversal (artifacts are content-only, not file-backed)
- Terminal statuses prevent further modification
- Timeline event for every A2A action

## Persistence

A2A tasks stored in `.igris/a2a/tasks/` as JSON files (git-ignored).
