# AGENTS.md — IGRIS_GPT Operating Rules

Rules for all future agents: Devin, Claude, Codex, or any local assistant.

## Source of truth

GitHub `main` and the repository memory files are the source of truth.

- repo: `Solarfox88/IGRIS_GPT`
- default branch: `main`
- memory files: `docs/IGRIS_PROJECT_MEMORY.md`, `docs/IGRIS_HANDOFF.md`, `docs/IGRIS_WORKLOG.md`, `docs/IGRIS_DECISIONS.md`, `docs/IGRIS_OPEN_ITEMS.md`

Local working directories (including clones from previous Codex/Claude sessions) are NOT authoritative. Always verify against GitHub `main`.

## Before every task

1. sync `main`: `git fetch origin && git checkout main && git pull --ff-only origin main`
2. read `AGENTS.md` (this file)
3. read `docs/IGRIS_PROJECT_MEMORY.md`
4. read `docs/IGRIS_HANDOFF.md`
5. read `docs/IGRIS_OPEN_ITEMS.md`
6. check open issues and PRs (`gh issue list`, `gh pr list`)
7. never trust stale local context — verify the current `main` commit
8. never work directly on `main` — create a feature/fix branch

## After every task

1. update `docs/IGRIS_WORKLOG.md` (append a row)
2. update `docs/IGRIS_HANDOFF.md` (set the new "current next issue" / "do next")
3. update `docs/IGRIS_OPEN_ITEMS.md` (mark resolved items, add new ones)
4. update `docs/IGRIS_DECISIONS.md` if architecture/security decisions changed
5. update `docs/IGRIS_PROJECT_MEMORY.md` if completed work / security baseline changed
6. include memory file updates in the same PR as the code change (or in a dedicated docs PR)

## Hard guardrails — non-regression constraints

These must NEVER be weakened by any agent:

- **write_auth** — all write/side-effect endpoints require authentication (PR #1293 / #1311)
- **dangerous_intent_routing** — dangerous intents (`rm -rf`, issue create, sudo, etc.) are never classified `chat_only` / `low` risk (PR #1332 / #1295)
- **memory_cross_session** — memory/preferences persist across logout/login (PR #1335 / #1294)
- **centralized redaction** — secret redaction is centralized, not duplicated (PR #1334 / #1313)
- **auth sessions / approval policies / memory isolation** — do not bypass

## Out-of-scope context — do NOT use

The following is cross-project contamination from a different project and must never be used as IGRIS context:

- LENOVO-TEST
- physical partition preflight
- disk resize
- approval package
- DeviceId/AgentId from external physical agent
- WinRE/BCD/BitLocker physical disk operations
- SSH to LENOVO-TEST
- physical Create

## Commit hygiene

- no runtime artifacts in commits (`.igris/`, `conversations/`, `logs/`, `__pycache__/`, `.venv/`, `.local/`)
- no secrets or keys in commits
- commit messages reference the issue/PR number
- use Conventional Commits style when possible (`fix(#NNNN):`, `feat(#NNNN):`, `docs(#NNNN):`, `refactor(#NNNN):`)
- never force-push, never rewrite history on shared branches
- never commit directly to `main`

## Verification

Before considering a task complete:

- run the relevant test suite (see `docs/IGRIS_WORKLOG.md` for known commands)
- run the gauntlet: `python -m igris.core.jarvis_core_gauntlet`
- prove failures are pre-existing on clean `origin/main` if regression is suspected
- never ignore failures in: `task_engine`, `mission_first`, `diagnostics`, `write_auth`, `dangerous_intent_routing`, `memory_cross_session`, `redaction`, `gauntlet`
