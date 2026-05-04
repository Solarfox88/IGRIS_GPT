# IGRIS_GPT

**A2A-ready AI Engineering Agent** — local-first, safety-first, repo-aware, cost-aware.

IGRIS_GPT is a personal AI engineering agent designed as a controllable,
self-hosted alternative to cloud coding assistants. It runs a FastAPI server
with a tabbed web console, a safe terminal (command-id only), persistent task
engine, A2A protocol support, anti-loop heuristics and cost-aware routing.

---

## Quick Start

```bash
git clone https://github.com/Solarfox88/IGRIS_GPT.git
cd IGRIS_GPT
python -m pip install -e ".[dev]"
python -m pytest -q            # 69 tests
python -c "from igris.web.server import create_app; create_app()"
```

## Installation

### Ubuntu / Linux

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git
git clone https://github.com/Solarfox88/IGRIS_GPT.git
cd IGRIS_GPT
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
```

### Windows

```powershell
git clone https://github.com/Solarfox88/IGRIS_GPT.git
cd IGRIS_GPT
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest -q
```

## Configuration

Create a `.env` file (never committed):

```env
OPENAI_API_KEY=sk-...          # optional
VASTAI_API_KEY=...             # optional
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=phi4-mini
PROJECT_ROOT=./project         # path to the repo you want IGRIS to manage
```

## Running the Server

```bash
python -c "
from igris.web.server import create_app, run_app
app = create_app()
run_app(app)
"
```

Open `http://localhost:7778` in your browser.

## Tests

```bash
python -m pytest -q
```

## Security

- **No free shell** — terminal accepts only pre-defined `command_id` values.
- **No .env preview** — file browser blocks `.env` and secret-named files.
- **Secret redaction** — output is scanned for OpenAI/GitHub/AWS keys and redacted.
- **Path traversal blocked** — file browser rejects `..` and symlinks outside root.
- **No arbitrary command execution** from UI or API.

See [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md).

## Safe Terminal

The terminal MVP accepts only commands from a fixed allowlist identified by
`command_id`. Available commands: `git_status`, `git_log`, `run_tests`,
`list_files`.

See [docs/SAFE_TERMINAL_MVP_PLAN.md](docs/SAFE_TERMINAL_MVP_PLAN.md).

## File Browser

Read-only file browser with:
- Tree view of project files.
- Text preview with secret redaction.
- Blocks: path traversal, `.env`, binary files, sensitive filenames.

## Task Engine

Persistent task storage under `.igris/tasks/` (git-ignored).

- Create, list, complete, block tasks via `/api/tasks`.
- Timeline events under `.igris/timeline/`.
- Tasks carry `family`, `priority`, `risk`, `semantic_fingerprint`.

See [docs/TASK_ENGINE.md](docs/TASK_ENGINE.md).

## A2A Readiness

IGRIS_GPT implements the Agent-to-Agent protocol:

- `GET /.well-known/agent-card.json` — agent card with skills.
- `POST /api/a2a/tasks` — create tasks from external agents.
- `GET /api/a2a/tasks/{id}` — query task status.
- `POST /api/a2a/tasks/{id}/messages` — append messages.
- `GET /api/a2a/capabilities` — list capabilities.

See [docs/A2A_READY_ARCHITECTURE.md](docs/A2A_READY_ARCHITECTURE.md).

## Agent Registry

Default agents: Git Agent, Test Runner Agent, Terminal Agent.
Capabilities: `git.status`, `validation.run_tests`, `execution.run_safe_command`.

## Teacher Governance

The teacher module validates agent assignments against:
- Family saturation (anti-loop).
- Missing differentiators.
- Observation loops.
- Success criteria requirements.

See [docs/TEACHER_GOVERNANCE.md](docs/TEACHER_GOVERNANCE.md).

## Anti-Loop

Detects when the agent is stuck repeating the same family of tasks.
`compute_family_counts()` and `saturated_families()` track repetition.
`required_strategy_shift_family()` suggests alternatives.

## Cost Routing

Routes tasks to the cheapest suitable provider:
1. Local Ollama (free).
2. VAST.ai (low cost).
3. OpenAI (fallback).

`/api/routing/history` and `/api/cost/summary` expose routing data.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/status` | GET | Provider and model info |
| `/api/health` | GET | Health check |
| `/api/readiness` | GET | Readiness checks |
| `/api/project/context` | GET | Project snapshot |
| `/api/git/status` | GET | Git branch/dirty/changed |
| `/api/files/tree` | GET | File tree |
| `/api/files/preview` | GET | File content preview |
| `/api/terminal/commands` | GET | List available commands |
| `/api/terminal/run` | POST | Execute command by ID |
| `/api/tests/run` | POST | Run pytest |
| `/api/tasks` | GET/POST | List/create tasks |
| `/api/tasks/{id}` | GET | Get task details |
| `/api/tasks/{id}/complete` | POST | Complete a task |
| `/api/tasks/{id}/block` | POST | Block a task |
| `/api/reports/recent` | GET | Recent execution reports |
| `/api/reports/{id}` | GET | Single report |
| `/api/agent/timeline` | GET | Agent timeline events |
| `/api/safety/status` | GET | Safety/anti-loop status |
| `/api/routing/history` | GET | Routing decisions |
| `/api/routing/explain` | GET | Routing explanation |
| `/api/cost/summary` | GET | Cost summary |
| `/api/a2a/tasks` | POST | Create A2A task |
| `/api/a2a/tasks/{id}` | GET | Get A2A task |
| `/api/a2a/tasks/{id}/messages` | POST | A2A messages |
| `/api/a2a/capabilities` | GET | Agent capabilities |
| `/.well-known/agent-card.json` | GET | A2A agent card |
| `/api/logs` | GET | Application logs |

## What's Implemented

- FastAPI backend with all endpoints above.
- Tabbed web UI (11 tabs) connected to real endpoints.
- Persistent task engine with JSON files.
- Execution reports with secret redaction.
- Safety module: path access, secret detection, output truncation.
- A2A protocol: agent card, task lifecycle, messages.
- Teacher governance with assignment validation.
- Anti-loop heuristics with family saturation detection.
- Semantic deduplication of tasks.
- Cost-aware provider routing.
- 69 passing tests.

## What's Placeholder

- LLM chat responses (returns placeholder text).
- Outcome router suggests actions but doesn't auto-execute.
- Teacher governance is validation-only (no auto-plan generation).
- VAST.ai integration (routing logic present, no real API calls).

## Roadmap

1. Real LLM integration (Ollama chat completions).
2. Auto-execution of teacher remediation plans.
3. WebSocket live updates for task progress.
4. Plugin system for custom agents.
5. Multi-repo management.
6. Persistent memory with vector search.

## License

Private — Solarfox88
