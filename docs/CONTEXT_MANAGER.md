# Context Manager — Epic #60

## Overview

The Context Manager decides what the LLM sees at each reasoning step.
It builds a token-budget-aware context packet containing mission info,
relevant files, recent actions, errors, memory, and world state.

The Context Manager does NOT call LLM providers. It produces a
`ContextPacket` consumed by the Model Orchestrator via the Reasoning Loop.

## Architecture

```
Goal + State + History + Errors + Memory
        ↓
  ContextManager.build_context()
        ↓
    ContextPacket
        ↓
  Model Orchestrator (Reasoning Loop)
```

## Token Budgets

| Profile | Budget (chars) | ~Tokens |
|---|---|---|
| local_light | 8,000 | ~2K |
| local_coder | 16,000 | ~4K |
| cheap_cloud_reasoning | 64,000 | ~16K |
| strong_cloud_reasoning | 200,000 | ~50K |
| risk_reviewer | 16,000 | ~4K |

4,000 chars reserved for system prompt + schema overhead.

## Context Sections (by priority)

1. **Mission context** — goal, mission ID, status (always included)
2. **Error context** — recent errors, test failures (high priority)
3. **Recent actions** — condensed action history (loop prevention)
4. **State context** — world state summary
5. **Memory context** — relevant lessons and past decisions
6. **File context** — scored file snippets (uses remaining budget)

## File Relevance Scoring

Files are scored 0.0–1.0 based on:
- Keyword match in path (+0.3 per keyword)
- Recently accessed (+0.2)
- Mentioned in errors (+0.4)
- Entry point file (+0.1)

## API Endpoints

### POST /api/context/build
Build a context packet.

### GET /api/context/budgets
List token budgets for all profiles.

### POST /api/context/score-files
Score file relevance for a task.

## Key Properties

- Secret redaction on all output
- Graceful degradation (empty sections, not crashes)
- Budget always respected (truncation tracked)
- Build time measured in milliseconds
