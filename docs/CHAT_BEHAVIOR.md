# Chat Behavior and Capability Grounding

## Overview

IGRIS_GPT chat is **IGRIS-aware**: it responds as an installed local engineering agent, not as a generic chatbot.

When a user asks operational questions (machine info, network, GitHub access, capabilities), IGRIS answers with:

1. What it **can** inspect safely through its APIs
2. What it **cannot** inspect without a dedicated safe command or token
3. Which safe action/tab/endpoint can help
4. Optionally proposes creating a task to add missing capabilities

## Chat Personality

The chat uses a dedicated IGRIS system prompt (`igris/core/chat_personality.py`) that:

- Identifies IGRIS as a local engineering agent
- Lists current capabilities (missions, tasks, patches, git, tests, etc.)
- Enforces safety rules (no free shell, no secrets, no unrestricted access)
- Prefers "I can do X safely through endpoint Y" over generic refusal

## Intent Detection

The personality module detects common operational intents:

| Intent | Example Prompts | Response Style |
|--------|----------------|----------------|
| `machine_info` | "dammi info sulla macchina", "CPU/RAM info" | Lists safe endpoints, suggests `system_info` command_id |
| `network_info` | "info sulla rete", "su che porta?" | Conservative, no IP dump, mentions security |
| `github_access` | "riesci a vedere il mio GitHub?" | Explains gated workflow, mentions approval |
| `capabilities` | "cosa puoi fare?", "what can you do?" | Structured capability categories |
| `testing` | "esegui i test" | Mentions `run_tests` command_id |
| `git_local` | "mostrami git status" | Lists git endpoints |
| `patching` | "crea una patch" | Explains patch workflow |
| `missions` | "crea una missione" | Explains mission lifecycle |
| `memory` | "mostrami i fallimenti" | Lists memory endpoints |
| `shell_request` | "esegui un comando bash" | Denies safely, offers alternatives |

## Capability Grounding

Each grounded response:

- References actual IGRIS endpoints
- Never suggests free shell as primary action
- Never claims unrestricted access
- Mentions approval gates where required (`I_APPROVE_GITHUB_WRITE`, `I_APPROVE_VASTAI_COSTS`)
- Is bounded in length (< 1500 chars)
- Contains no secrets

## API Endpoints

### GET /api/chat/capabilities

Returns structured capability summary:

```json
{
  "identity": "IGRIS_GPT — Local Engineering Agent",
  "version": "v0.5-real-world-candidate",
  "capabilities": {
    "missions": {"label": "Missioni e Planning", "safe": true, ...},
    "github_gated": {"label": "GitHub (Gated)", "approval_required": "I_APPROVE_GITHUB_WRITE", ...},
    ...
  },
  "safety": {
    "no_free_shell": true,
    "secrets_redacted": true,
    "approval_gates": ["I_APPROVE_GITHUB_WRITE", "I_APPROVE_VASTAI_COSTS"],
    "no_auto_merge": true,
    "no_auto_push": true
  }
}
```

### POST /api/chat/intent

Detect intent from a message:

```json
// Request
{"message": "dammi info sulla macchina"}

// Response
{
  "intent": "machine_info",
  "grounded_response": "Posso mostrarti lo stato visibile da IGRIS...",
  "has_response": true
}
```

## Examples

### Machine Info

User: "dammi info sulla macchina su cui ti trovi"

```
Posso mostrarti lo stato visibile da IGRIS.
Non uso shell libera, ma posso usare endpoint e command_id sicuri.

Disponibile ora:
- /api/status — stato del server
- /api/readiness — readiness con provider/model check
- /api/routing/explain — routing e disponibilità provider
- /api/git/status — stato del repository
- command_id: git_status, git_log, run_tests, list_files

Per info OS/CPU/RAM/GPU complete serve un endpoint dedicato `system_info`.
Posso creare una task per implementarlo in modo sicuro.
```

### GitHub Access

User: "riesci a vedere il mio GitHub?"

```
Posso lavorare con Git locale e con il workflow GitHub gated.

Ora posso:
- leggere git status/diff/branch locali (/api/git/status, /api/git/diff)
- generare commit proposal (/api/git/commit-proposal)
- preparare PR dry-run (/api/github/pr/prepare)
- creare PR solo con approval `I_APPROVE_GITHUB_WRITE`

Non posso:
- fare push/merge automatici
- accedere a GitHub remoto senza token configurato
- fare force push o merge su branch protetti

Il workflow è: commit proposal → safety check → PR prepare → gated PR create.
```

## Architecture

```
User message
    │
    ▼
detect_intent() ─── known intent? ──→ get_grounded_response() → direct response
    │                                    (IGRIS-aware, no LLM needed)
    │ no match
    ▼
IGRIS_SYSTEM_PROMPT + LLM ─── available? ──→ LLM response (with IGRIS personality)
    │                              │ no
    │                              ▼
    │                        deterministic fallback (still IGRIS-aware)
    ▼
Response with metadata (provider, model, intent_detected, routing_reason)
```

## Safety Guarantees

- No free shell execution suggested as primary action
- No claim of unrestricted system access
- No secrets in responses
- All responses bounded in length
- Approval gates explicitly mentioned for gated operations
- Conservative stance on network/system information
