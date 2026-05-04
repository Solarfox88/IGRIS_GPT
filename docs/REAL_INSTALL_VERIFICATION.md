# Real Install Verification

## Overview

IGRIS_GPT has been verified to install and run from a completely clean
state — fresh clone, no pre-existing runtime artifacts, no Ollama.

## Verified Install Procedure

```bash
# 1. Fresh clone
git clone https://github.com/Solarfox88/IGRIS_GPT.git
cd IGRIS_GPT

# 2. Create virtualenv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Run tests
python -m pytest -q

# 4. Configure
cp .env.example .env
# Edit .env with your settings (optional)

# 5. Start server
bash scripts/start_igris.sh

# 6. Verify
curl http://127.0.0.1:7778/api/health
curl http://127.0.0.1:7778/api/readiness
curl http://127.0.0.1:7778/api/status
bash scripts/status_igris.sh

# 7. Open UI
# http://localhost:7778

# 8. Stop
bash scripts/stop_igris.sh
```

## Verification Results

| Check | Result |
|---|---|
| Fresh clone | OK |
| venv creation | OK |
| pip install -e ".[dev]" | OK, no errors |
| python -m pytest -q | 559 passed |
| cp .env.example .env | OK |
| bash scripts/start_igris.sh | Server started (PID tracked) |
| bash scripts/status_igris.sh | PID running, health OK, readiness OK |
| curl /api/health | `{"status":"ok"}` |
| curl /api/readiness | `{"ollama_available":false}` (expected without Ollama) |
| curl /api/status | `{"provider":"local","model":"phi4-mini","safe":true}` |
| bash scripts/stop_igris.sh | Server stopped cleanly |
| git status | Clean (no untracked, no modified) |

## Runtime Artifacts

All runtime artifacts are git-ignored:

| Path | Purpose | Git Status |
|---|---|---|
| `.igris/` | Tasks, timeline, memory, reports | Ignored |
| `logs/` | Server logs, PID file | Ignored |
| `.venv/` | Python virtual environment | Ignored |
| `.env` | Environment config (from .env.example) | Ignored |
| `*.egg-info/` | Python build metadata | Ignored |
| `__pycache__/` | Python bytecode cache | Ignored |

## Behavior Without Ollama

When Ollama is not installed or not running:
- Server starts normally
- `/api/readiness` reports `ollama_available: false`
- Chat uses deterministic fallback (keyword-based responses)
- No crash, no error, fully functional in fallback mode
- Clear message: "deterministic fallback mode"

## Scripts

| Script | Purpose | Idempotent |
|---|---|---|
| `install_ubuntu.sh` | System packages + venv + pip install | Yes |
| `start_igris.sh` | Start server (background, PID tracked) | No (fails if already running) |
| `stop_igris.sh` | Stop server (graceful, then SIGKILL) | Yes |
| `status_igris.sh` | Check PID + health + readiness + logs | Yes |
| `smoke_test.sh` | Quick import + pytest + server checks | Yes |
| `setup_ollama.sh` | Install Ollama + pull model | Yes |
