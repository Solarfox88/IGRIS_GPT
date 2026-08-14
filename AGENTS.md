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

## Mandatory 5-pass completion rule

Every IGRIS task must follow the 5-pass completion rule before it can be called complete, ready to merge, ready to close, or production-ready.

This applies to:

- issues
- PRs
- bugfixes
- refactors
- tests
- CI changes
- documentation that affects project operation
- VM/runtime validation
- security hardening
- memory updates
- roadmap items
- follow-up phases

No agent may mark work as complete after a single pass.

### Required passes

#### Pass 1 — Understand and implement first version

- read `AGENTS.md`
- read all `docs/IGRIS_*.md` memory files
- read the GitHub issue/PR and comments
- define acceptance criteria
- create a dedicated branch
- implement the first safe version
- add initial tests
- do not declare completion

#### Pass 2 — Reread issue and review own diff

- reread the original issue/PR
- reread the produced diff
- compare the work against acceptance criteria
- find missing cases, weak spots, test gaps, docs gaps, or cleanup opportunities
- apply at least one improvement, or explicitly justify why no improvement exists

#### Pass 3 — Edge cases and regression review

- check edge cases
- check negative paths
- check interactions with auth, routing, memory, diagnostics, task engine, logging, redaction, CI, VM, and gauntlet where relevant
- add or improve regression tests
- verify the fix is not only a happy-path patch

#### Pass 4 — Safety, VM, memory, and integration

- verify security guardrails
- run relevant tests
- run local gauntlet when applicable
- perform VM validation when runtime-impacting
- update memory files
- update open items and worklog
- do not close parent issues if only a phase was completed

#### Pass 5 — Final acceptance review

- reread the issue one final time
- reread the complete diff one final time
- verify acceptance criteria
- verify tests and gauntlet
- verify VM state when applicable
- verify memory files are updated
- decide honestly: complete, phase-complete, blocked, or follow-up required

### Forbidden before pass 5

Before completing Pass 5, agents must not say or write:

- done
- completed
- production-complete
- ready to merge
- ready to close
- issue resolved
- roadmap complete
- parent issue complete

unless explicitly marked as a temporary note inside the 5-pass checklist.

### Honest completion rule

If after 5 passes the full acceptance criteria are not satisfied, the correct status is:

```text
Phase completed, parent issue not complete.
```

In that case, create or update a follow-up issue and record it in:

- `docs/IGRIS_OPEN_ITEMS.md`
- `docs/IGRIS_HANDOFF.md`
- `docs/IGRIS_WORKLOG.md`

### Mandatory PR section

Every non-trivial PR must include:

```markdown
## 5-pass completion review

### Pass 1
- Issue/memory reread:
- Work done:
- Tests:

### Pass 2
- Issue reread:
- Diff reread:
- Gaps found:
- Improvements:

### Pass 3
- Edge cases:
- Regressions:
- Improvements:

### Pass 4
- Safety:
- VM validation:
- Memory files:

### Pass 5
- Acceptance criteria:
- Final tests:
- Honest status:
```

### Memory-first requirement

Before every task, the agent must read:

- `AGENTS.md`
- `docs/IGRIS_PROJECT_MEMORY.md`
- `docs/IGRIS_HANDOFF.md`
- `docs/IGRIS_OPEN_ITEMS.md`
- `docs/IGRIS_DECISIONS.md`
- `docs/IGRIS_WORKLOG.md`

The agent must explicitly state in its report that these files were read before starting work.

Skipping memory reading is a process violation.

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
