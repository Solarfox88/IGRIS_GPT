# Migration from IGRIS

This document describes the evolution from the original IGRIS concept to
IGRIS_GPT's current architecture.

## Key Changes

1. **Persistent task engine** — Tasks are stored as JSON files under `.igris/tasks/`
   instead of in-memory only.
2. **A2A protocol** — Agent card and task lifecycle endpoints follow the A2A spec.
3. **Safety module** — Comprehensive secret detection, path validation, and output
   redaction replace the original basic checks.
4. **Teacher governance** — Assignment validation with saturation and duplication
   checks.
5. **Anti-loop** — Family saturation detection prevents the agent from repeating
   the same strategy.
6. **Cost routing** — Provider selection based on cost (Ollama → VAST.ai → OpenAI).
7. **Web UI** — 11-tab agentic console replaces the original simple chat interface.

## File Structure

```
igris/
├── a2a/           # A2A protocol (agent card, schemas)
├── agents/        # Agent registry and base classes
├── core/          # Core logic (safety, task engine, teacher, etc.)
├── layers/        # Execution, advisory, git layers
├── models/        # Data models (config, task, report)
└── web/           # FastAPI server, templates, static assets
```

## Migration Steps

If migrating from a previous IGRIS installation:

1. Ensure Python 3.12+ is installed.
2. Run `pip install -e ".[dev]"` from the repo root.
3. Existing `.igris/` data is preserved (tasks, timeline, reports).
4. Update your `.env` to include any new configuration variables.
5. Run `python -m pytest -q` to verify everything works.
