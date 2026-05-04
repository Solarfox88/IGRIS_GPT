# Agent Contract

This document defines the operational contract for IGRIS_GPT agents.

## Capabilities

Each agent registers a set of **capabilities** — discrete, safe operations it can perform.
A capability has:

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique identifier (e.g. `git.status`) |
| `name` | string | Human-readable name |
| `description` | string | What this capability does |
| `safe` | bool | Whether it can be executed without teacher approval |
| `risk` | string | `low`, `medium`, or `high` |

## Execution Rules

1. Only capabilities registered in the agent registry may be executed.
2. `command_id` must match an entry in `ALLOWED_COMMANDS`.
3. Arbitrary shell commands are **never** accepted.
4. Output is truncated and secret-redacted before storage.

## Task Assignment

Tasks are assigned a `family` (testing, editing, writing, etc.) and tracked
for saturation. The teacher validates assignments before execution when risk
is medium or high.

## Reports

Every execution produces a persistent report under `.igris/reports/` with:
- `report_id`, `command_id`, `returncode`, `stdout_truncated`, `stderr_truncated`
- `success`, `failure_type`, `next_recommendation`
