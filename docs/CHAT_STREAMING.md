# Chat Streaming + Session Tier Selector

## Overview

SSE-based streaming for chat responses and a session tier selector to
control which LLM provider handles chat requests.

## Tiers

| Tier | Behavior |
|---|---|
| `auto` | Local → fallback → deterministic (default) |
| `local` | Force local Ollama. Falls to deterministic if unavailable. |
| `fallback` | Force OpenAI fallback. Falls to deterministic if unavailable. |

**Not active:** Vast tier (future, behind approval gate).

## Streaming

`POST /api/chat/stream` returns SSE (`text/event-stream`). Each event is:

```
data: {"type": "content", "text": "partial response...", "metadata": {}}
```

Final event:

```
data: {"type": "done", "text": "", "metadata": {"provider": "...", "model": "...", "tier": "auto", "latency_ms": 42}}
```

Note: Current implementation simulates streaming by chunking the full
response (80-char chunks). True token-level streaming will be added
when Ollama streaming support is integrated.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat/stream` | POST | SSE streaming chat (message, optional session_id) |
| `/api/chat/tiers` | GET | Get tier availability and current tier |
| `/api/chat/tiers` | POST | Set session tier (auto/local/fallback) |

### POST /api/chat/stream

```json
{"message": "help me with tests", "session_id": "1"}
```

### POST /api/chat/tiers

```json
{"tier": "local"}
```

## Safety

- No command execution from chat
- No WRITE_FILE from chat
- All responses secret-redacted
- No Vast tier active (future)
