# A2A-Ready Architecture

IGRIS_GPT implements the Agent-to-Agent (A2A) protocol, enabling interoperability
with other AI agents.

## Agent Card

`GET /.well-known/agent-card.json` returns a JSON document describing the agent:

```json
{
  "name": "IGRIS_GPT",
  "description": "A2A-ready AI engineering agent",
  "url": "http://localhost:7778",
  "capabilities": {
    "skills": [
      { "id": "git.status", "name": "Git status", "risk": "low" },
      { "id": "validation.run_tests", "name": "Run Tests", "risk": "medium" },
      { "id": "execution.run_safe_command", "name": "Run Safe Command", "risk": "medium" }
    ]
  }
}
```

Skills are derived from the agent registry at startup.

## Task Lifecycle

1. **Create**: `POST /api/a2a/tasks` with `{"description": "..."}` → task with `source="a2a"`.
2. **Query**: `GET /api/a2a/tasks/{id}` → task status and details.
3. **Message**: `POST /api/a2a/tasks/{id}/messages` → append message to timeline/memory.

A2A tasks are stored identically to user tasks in `.igris/tasks/` and participate
in the same anti-loop and deduplication checks.

## Capabilities Endpoint

`GET /api/a2a/capabilities` returns the full list of registered capabilities.

## Security

- Agent card never exposes API keys or secrets.
- A2A tasks cannot trigger arbitrary command execution.
- Messages are stored but not auto-executed.

## Discovery

Both `/.well-known/agent-card.json` and `/.well-known/agent.json` serve the same card.
`/api/a2a/agent-card` provides an API-prefixed alias.
