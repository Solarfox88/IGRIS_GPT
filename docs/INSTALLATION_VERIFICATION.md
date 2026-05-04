# Installation Verification

Steps to verify IGRIS_GPT is correctly installed and working.

## 1. Python Import Check

```bash
python -c "from igris.web.server import create_app; app=create_app(); print(app.title)"
# Expected output: IGRIS_GPT
```

## 2. Test Suite

```bash
python -m pytest -q
# Expected: 77 passed
```

## 3. Server Startup

```bash
python -c "from igris.web.server import create_app, run_app; run_app(create_app())"
```

Open http://localhost:7778 — you should see the agentic console with 11 tabs.

## 4. Health and Readiness

```bash
curl -s http://localhost:7778/api/health | python -m json.tool
# Expected: {"status": "ok", "version": "0.1.0", "time": ...}

curl -s http://localhost:7778/api/readiness | python -m json.tool
# Expected: all checks true (ollama_available may be false)
```

## 5. Endpoint Verification

```bash
# Core endpoints
curl -s http://localhost:7778/api/status
curl -s http://localhost:7778/api/project/context
curl -s http://localhost:7778/api/safety/status

# Tasks
curl -s -X POST http://localhost:7778/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"description": "test task"}'

curl -s http://localhost:7778/api/tasks

# A2A
curl -s http://localhost:7778/.well-known/agent-card.json
curl -s http://localhost:7778/api/a2a/capabilities

# Chat (creates session then sends message)
SESSION=$(curl -s -X POST http://localhost:7778/api/sessions | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X POST "http://localhost:7778/api/sessions/$SESSION/messages" \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'

# Cost/Routing
curl -s http://localhost:7778/api/cost/summary
curl -s http://localhost:7778/api/routing/explain

# Teacher
curl -s -X POST http://localhost:7778/api/teacher/remediate \
  -H "Content-Type: application/json" \
  -d '{}'

# Outcome
curl -s http://localhost:7778/api/outcome/recent
```

## 6. Safety Checks

```bash
# Arbitrary command must be rejected (only command_id allowed)
curl -s -X POST http://localhost:7778/api/terminal/run \
  -H "Content-Type: application/json" \
  -d '{"command": "rm -rf /"}' | python -m json.tool
# Expected: error or ignores 'command' field

# .env preview must be blocked
curl -s "http://localhost:7778/api/files/preview?path=.env"
# Expected: 400 or 403 error

# Path traversal must be blocked
curl -s "http://localhost:7778/api/files/preview?path=../../../etc/passwd"
# Expected: 400 error

# Agent card must not contain secrets
curl -s http://localhost:7778/.well-known/agent-card.json | grep -i "key\|secret\|password\|token"
# Expected: no output (no secrets)
```

## 7. Git Status Clean

```bash
git status
# .igris/, logs/, .env should be in .gitignore
# No runtime artifacts should be tracked
```

## 8. Smoke Test Script

```bash
bash scripts/smoke_test.sh
# Expected: all checks pass, exit code 0
```

## 9. Ubuntu Scripts (Linux only)

```bash
bash scripts/start_igris.sh
bash scripts/status_igris.sh
bash scripts/stop_igris.sh
```
