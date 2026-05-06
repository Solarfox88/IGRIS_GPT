# Agent Action Schema & Prompt Contract — Epic #58

## Overview

The Agent Action Schema defines the structured contract between the LLM reasoning loop and IGRIS execution engine. Every LLM proposal must conform to this schema before it can be validated, risk-classified, and executed.

**Core principle:** The LLM proposes, IGRIS governs.

```text
LLM proposes structured action (JSON)
  → IGRIS validates schema
  → Risk classifier assesses risk
  → Safety policy checks approval
  → Rollback resolver prepares backup if needed
  → Tool Runtime executes
  → Verifier checks success
  → Governor checks for loops
  → Memory records outcome
```

## Action Schema

Every LLM response must be a single JSON object:

```json
{
  "mode": "coder",
  "action_type": "read_file_range",
  "reason": "Need to inspect existing FastAPI route pattern",
  "parameters": {"path": "igris/web/server.py", "start": 1, "end": 80},
  "expected_effect": "Find correct place to add /api/ping",
  "risk_hint": "low",
  "confidence": 0.82,
  "required_preconditions": [],
  "success_check": {"has_content": true},
  "fallback_if_blocked": "find_files"
}
```

## Action Types

| Action Type | Category | Description |
|---|---|---|
| `search_code` | Navigation | Search for patterns in codebase |
| `find_files` | Navigation | Find files by name/pattern |
| `list_directory` | Navigation | List directory contents |
| `read_file_range` | Navigation | Read specific lines from a file |
| `write_file` | Modification | Write/create a file |
| `propose_patch` | Modification | Propose a code patch |
| `apply_patch` | Modification | Apply a validated patch |
| `run_tests` | Testing | Execute test suite |
| `git_status` | Git | Check git status |
| `git_diff` | Git | View git diff |
| `shell_template` | Shell | Run pre-approved command template |
| `raw_shell_proposal` | Shell (gated) | Propose arbitrary command |
| `http_check` | HTTP | Health/status check |
| `update_plan` | Planning | Update mission plan |
| `record_memory` | Memory | Record decision/lesson |
| `ask_user` | Human | Request human input |
| `finish` | Terminal | Declare complete |
| `blocked` | Terminal | Declare unable to proceed |

## Agent Roles (Registry)

| Role | Responsibility | Max Risk |
|---|---|---|
| coordinator | Mission focus, plan, step tracking | high |
| planner | Goal decomposition, preconditions | low |
| researcher | Explore repo, docs, logs (read-only) | low |
| coder | Modify code and workspace files | medium |
| tester | Execute tests, interpret failures | low |
| reviewer | Review diff, quality, regressions | low |
| devops | Deploy, server, nginx, Docker, systemd | high |
| security_guard | Risk, secrets, policy evaluation | low |
| memory_manager | Save/retrieve lessons and patterns | low |
| cost_guardian | Provider selection, budget management | low |
| reporter | Final reports, artifacts, next steps | low |

## Model Orchestrator

All LLM calls go through the Model Orchestrator. No component calls providers directly.

### Profiles

| Profile | Use Case | Provider Chain |
|---|---|---|
| deterministic | Safety, policy, routing | No LLM |
| local_light | Chat, synthesis, classification | Ollama → DeepSeek → OpenAI |
| local_coder | Code reasoning (local) | Ollama → DeepSeek → OpenAI |
| cheap_cloud_reasoning | Coding/reasoning | DeepSeek → OpenAI → Ollama |
| strong_cloud_reasoning | Hard debug, architecture | Anthropic → OpenAI → DeepSeek |
| risk_reviewer | Risk analysis | DeepSeek → OpenAI → Ollama |
| embedding_memory | Semantic retrieval | Ollama → OpenAI |

## Command Risk Engine Integration

Actions are routed based on type:

```text
Navigation actions → Code Navigation Tools (safe, no gate)
Tool Runtime actions → Tool Runtime with risk classification
Shell actions → Command Risk Engine (full pipeline)
Planning actions → Mission Controller
Memory actions → Memory Layer
Human actions → Human Gate (blocks for input)
Terminal actions → Mission state update
```

### Shell Command Policy

Order of preference:
1. **Structured tool** — always preferred
2. **Shell template** — parameterized, pre-approved
3. **Raw shell proposal** — escape hatch, always gated by Command Risk Engine

## Validation

Every action is validated before execution:

1. `action_type` must be in the known set
2. `mode` must be a registered agent role
3. `risk_hint` must be valid
4. `confidence` must be in [0, 1]
5. Role must be permitted to perform the action
6. Required parameters must be present
7. No secret content in parameters
8. `reason` should be non-empty

## Connection to Existing Components

| Component | Connection |
|---|---|
| Mission Controller | `update_plan`, `finish`, `blocked` update mission state |
| GOAP Planner | Preconditions/effects from planner feed into action selection |
| Tool Runtime | All execution actions dispatched through Tool Runtime |
| Safety/Rollback | Risk classification and rollback applied to write actions |
| Teacher/Governor | Governor checks for loops after each action |
| Decision Memory | Every action outcome recorded in memory |
| Command Risk Engine | `shell_template` and `raw_shell_proposal` must pass risk analysis |

## API Endpoints

- `GET /api/agent/schema` — returns the action JSON schema
- `GET /api/agent/roles` — lists all registered agent roles
- `GET /api/agent/examples` — returns example scenarios
- `POST /api/agent/validate` — validates an action against the schema
- `GET /api/orchestrator/providers` — lists configured providers
- `GET /api/orchestrator/profiles` — lists task→profile mappings
- `GET /api/orchestrator/cost` — returns cost tracking summary
