# Local LLM phi4-mini Hardening

## Overview

IGRIS_GPT defaults to phi4-mini as its local LLM via Ollama, with
transparent degradation to OpenAI fallback or deterministic responses.

## Configuration

```env
LOCAL_LLM_PROVIDER=ollama
LOCAL_LLM_MODEL=phi4-mini
LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
```

## Model Alias Normalization

Common misspellings and shorthand are auto-corrected:

| Input | Normalized |
|---|---|
| `phi4mini` | `phi4-mini` |
| `phi4_mini` | `phi4-mini` |
| `phi-4-mini` | `phi4-mini` |
| `phi4` | `phi4-mini` |
| `llama3` | `llama3.2` |
| `llama32` | `llama3.2` |

## Fallback Chain

```
local (Ollama/phi4-mini)
  → fallback (OpenAI, if API key configured)
    → deterministic (keyword-based, always available)
```

## Readiness Checks

`GET /api/readiness` now reports:

| Field | Description |
|---|---|
| `ollama_available` | Ollama service reachable |
| `local_model_configured` | Model name from config (e.g., `phi4-mini`) |
| `local_model_available` | Model actually pulled in Ollama |
| `fallback_active` | OpenAI API key configured |
| `fallback_reason` | Why fallback is/isn't active |

## Routing Availability

`GET /api/routing/availability` now reports per-provider:

| Provider | Fields |
|---|---|
| ollama | reachable, model_configured, model_available, status |
| openai | available, key_present, status |
| vastai | available, key_present, status |
| fallback_chain | Full chain description |

Status values:
- `"online + model ready"` — Ollama running, model pulled
- `"online (model not pulled)"` — Ollama running, model needs pull
- `"offline"` — Ollama not reachable

## Without Ollama

IGRIS_GPT works fully without Ollama:
- No crash, no error
- Chat uses deterministic keyword-based fallback
- All endpoints functional
- Readiness clearly indicates `ollama_available: false`

## Setup

```bash
bash scripts/setup_ollama.sh
```

This installs Ollama, starts the service, and pulls phi4-mini.
If any step fails, IGRIS remains functional in fallback mode.
