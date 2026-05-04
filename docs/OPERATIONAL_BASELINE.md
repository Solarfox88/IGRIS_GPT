# IGRIS_GPT Operational Baseline

Current state of the system and operational procedures.

## What Works

### Core Infrastructure
- **FastAPI server** on port 7778 with 30+ API endpoints
- **Web console** with 11 functional tabs
- **Persistent storage** under `.igris/` (tasks, reports, timeline, memory)
- **Ubuntu install scripts** (install, start, stop, restart, status, smoke test)
- **Systemd service example** for production deployment

### Chat Engine
- **Ollama integration** — uses local LLM when available
- **OpenAI fallback** — if API key configured
- **Deterministic fallback** — contextual responses without any LLM
- Response includes `provider`, `model`, `fallback_used`, `latency_ms`

### Task Management
- Create, list, complete, block tasks via API and UI
- Tasks persist as JSON files under `.igris/tasks/`
- Task family classification, priority, risk assessment
- Anti-loop detection with family saturation

### Safety
- Terminal accepts only `command_id` from allowlist (no free shell)
- File preview blocks `.env`, path traversal, binary files
- Secret redaction in all output (OpenAI, GitHub, AWS patterns)
- Agent card contains no secrets

### Teacher Governance
- `POST /api/teacher/remediate` builds payload and proposes remediation
- Detects: family saturation, duplicate tasks, observation loops
- Validates assignments against success criteria requirements
- Can auto-create remediation tasks with `create: true`

### Outcome Router
- Routes execution report outcomes to recommendations
- Suggests validation, strategy shifts, or teacher review
- Connected to test runs and terminal commands
- `GET /api/outcome/recent` shows recent recommendations

### A2A Protocol
- Agent card at `/.well-known/agent-card.json`
- Task creation, querying, and message exchange
- Capabilities listing

### Cost and Routing
- Tracks routing decisions with provider, model, latency, cost
- Cost summary with local vs. fallback call counts
- Ollama availability check

## How to Operate

### Start
```bash
# Ubuntu with scripts:
bash scripts/start_igris.sh

# Manual:
python -c "from igris.web.server import create_app, run_app; run_app(create_app())"
```

### Stop
```bash
bash scripts/stop_igris.sh
# or kill the process manually
```

### Test
```bash
python -m pytest -q
```

### Verify Safety
```bash
# Check no secrets in agent card:
curl -s http://localhost:7778/.well-known/agent-card.json | python -c "import sys,json; d=json.load(sys.stdin); print('OK' if 'key' not in str(d).lower() else 'FAIL')"

# Check .env blocked:
curl -s http://localhost:7778/api/files/preview?path=.env
# Should return error

# Check terminal safety:
curl -s -X POST http://localhost:7778/api/terminal/run -H 'Content-Type: application/json' -d '{"command_id": "git_status"}'
# Should work

curl -s -X POST http://localhost:7778/api/terminal/run -H 'Content-Type: application/json' -d '{"command": "ls"}'
# Should fail or be ignored
```

### Check Health
```bash
curl -s http://localhost:7778/api/health
curl -s http://localhost:7778/api/readiness
```

## What's Still Placeholder

| Feature | Status | Notes |
|---|---|---|
| VAST.ai integration | Placeholder | Routing logic exists, no real API calls |
| Auto-execution of recommendations | Not implemented | Outcome router suggests only |
| WebSocket live updates | Not implemented | UI uses polling (15s auto-refresh) |
| Vector search memory | Not implemented | Memory is simple JSON append |
| Multi-repo management | Not implemented | Single project root |

## Runtime Directories

Created at first run, never committed:
- `.igris/tasks/` — persistent task storage
- `.igris/reports/` — execution reports
- `.igris/timeline/` — agent events
- `.igris/memory/` — memory events
- `logs/` — application logs

## Next Steps for Devin

To continue development on IGRIS_GPT:

1. **Clone and install**: Follow README Ubuntu Quick Install
2. **Run tests**: `python -m pytest -q` (77 tests must pass)
3. **Start server**: `bash scripts/start_igris.sh`
4. **Key files**:
   - `igris/web/server.py` — all API endpoints
   - `igris/core/chat_engine.py` — LLM integration
   - `igris/core/task_engine.py` — task persistence
   - `igris/core/teacher.py` — teacher governance
   - `igris/core/outcome_router.py` — outcome routing
   - `igris/core/safety.py` — safety module
   - `igris/web/templates/index.html` — UI HTML
   - `igris/web/static/js/app.js` — UI JavaScript
5. **Add new features** by adding endpoints to `server.py` and tests to `tests/`
6. **Always run `python -m pytest -q` before committing**

### Suggested Next Development Priorities
1. VAST.ai real integration for cost-effective GPU workloads
2. WebSocket for real-time task progress updates
3. Plugin system for custom agents
4. Persistent vector memory with semantic search
5. Multi-repo management support
