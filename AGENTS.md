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

## Mandatory 10-pass completion rule

Every IGRIS task must follow the mandatory 10-pass completion rule before it can be called complete, ready to merge, ready to close, production-ready, or fully resolved.

This applies to every type of work:

- issues
- pull requests
- bugfixes
- refactors
- tests
- CI changes
- documentation that affects operation
- memory updates
- VM/runtime validation
- security hardening
- logging/observability
- type checking
- roadmap items
- follow-up phases

No agent may mark work as complete after one narrow implementation pass.

### Pass 1 — Memory and task intake

Before coding:

- sync latest `main`
- read `AGENTS.md`
- read all `docs/IGRIS_*.md` memory files
- read the GitHub issue/PR and all comments
- identify parent issue, follow-up issue, linked PRs, and previous phases
- report explicitly that memory files were read

Required report:

```text
Memory files read before task: yes
10-pass completion rule loaded: yes
Issue/PR read: yes
Current main commit: <commit>
```

### Pass 2 — Acceptance criteria extraction

Extract the issue into explicit acceptance criteria.

For each criterion define:

- what would prove it complete
- what tests or runtime checks are required
- what would make it only phase-complete
- what must not be changed
- what related prior decisions/ADRs apply

Do not rely on vague wording like "looks good" or "should be fine".

### Pass 3 — Baseline and evidence collection

Before modifying code:

- establish current baseline
- capture counts, failures, endpoint behavior, tests, config, file sizes, or other measurable evidence
- identify whether failures are pre-existing
- identify runtime/VM state when applicable

Examples:

- type errors count
- except Exception count
- structured logging coverage
- gauntlet result
- endpoint smoke result
- VM commit and health
- file line counts

### Pass 4 — First focused implementation

Implement the smallest safe improvement.

Rules:

- keep scope focused
- do not rewrite unrelated systems
- do not weaken safety guardrails
- add or update tests
- do not declare completion

### Pass 5 — Self-review against issue and diff

Reread:

- the original issue
- acceptance criteria
- your full diff
- changed tests
- related memory files

Find gaps.

You must apply at least one improvement or explicitly justify why no improvement exists.

### Pass 6 — Architecture and existing-pattern review

Check whether the work duplicates or violates existing architecture.

Mandatory checks:

- is there already a centralized helper/module for this?
- am I duplicating security, redaction, auth, routing, logging, memory, or config logic?
- am I bypassing an existing guardrail?
- am I introducing a parallel implementation instead of using the canonical one?
- do I need an ADR if I intentionally diverge?

If the project already has a central implementation, use it unless there is a documented reason not to.

### Pass 7 — Edge cases, negative paths, and regression review

Check:

- happy path
- negative path
- missing/invalid input
- auth/session/trust-level interaction
- filesystem and OS differences
- Windows/Linux differences
- stale data
- concurrency/locking
- logging/redaction
- failure modes
- unexpected exceptions

Add or update regression tests.

### Pass 8 — Runtime, VM, and integration validation

If the change affects runtime, API, UI, auth, memory, diagnostics, task engine, logging, startup, routing, tool execution, or service behavior, validate on VM.

VM:

- URL: http://192.168.1.253:7778
- Gauntlet Python: /home/igris/IGRIS_GPT/.venv/bin/python

Required VM flow:

```bash
ssh <VM_USER>@192.168.1.253
cd /home/igris/IGRIS_GPT
git fetch origin
git checkout <branch>
git pull --ff-only origin <branch> || true
sudo systemctl restart igris.service
/home/igris/IGRIS_GPT/.venv/bin/python -m igris.core.jarvis_core_gauntlet
```

Then from host:

```bash
curl.exe -s http://192.168.1.253:7778/api/diagnostics/summary
curl.exe -s http://192.168.1.253:7778/api/os/brief
```

Docs-only changes may skip runtime VM validation, but after merge the VM must still be updated to latest main.

### Pass 9 — GitHub state and closure verification

Before saying complete or parent issue complete:

- verify PR state on GitHub
- verify issue state on GitHub
- verify linked parent issue/follow-up issue
- verify whether the issue is actually closed if you claim closed
- verify whether acceptance criteria are truly met, not just partially addressed
- verify whether follow-up is needed

Do not say "parent issue complete" if:

- GitHub issue remains open
- acceptance criteria remain unmet
- you only completed a phase
- tests are incomplete
- VM validation is missing when required
- memory files still say pending
- follow-up work is known

### Pass 10 — Final honesty gate and memory update

Final review:

- reread the issue one final time
- reread the diff one final time
- compare against acceptance criteria
- update memory files
- update worklog
- update open-items
- update ADRs if needed
- decide honest status

Allowed statuses:

- Complete
- Phase completed, parent issue not complete
- Blocked
- Needs follow-up
- Rejected / superseded

Forbidden unless fully true:

- roadmap complete
- parent issue complete
- production-complete
- ready to close
- done
- fully resolved

If anything remains, create or update follow-up issue before moving on.

### Forbidden before pass 10

Before completing Pass 10, agents must not say or write:

- done
- completed
- production-complete
- ready to merge
- ready to close
- issue resolved
- roadmap complete
- parent issue complete

unless explicitly marked as a temporary note inside the 10-pass checklist.

### Honest completion rule

If after 10 passes the full acceptance criteria are not satisfied, the correct status is:

```text
Phase completed, parent issue not complete.
```

In that case, create or update a follow-up issue and record it in:

- `docs/IGRIS_OPEN_ITEMS.md`
- `docs/IGRIS_HANDOFF.md`
- `docs/IGRIS_WORKLOG.md`

### Mandatory PR body section

Every non-trivial PR must include:

```markdown
## 10-pass completion review

### Pass 1 — Memory and task intake
- Memory files read:
- Issue/PR read:
- Current main commit:

### Pass 2 — Acceptance criteria extraction
- Criteria:
- Proof required:
- Non-goals:

### Pass 3 — Baseline and evidence
- Baseline:
- Pre-existing failures:
- Metrics:

### Pass 4 — First focused implementation
- Work done:
- Tests added:

### Pass 5 — Self-review against issue and diff
- Diff reread:
- Gaps found:
- Improvements made:

### Pass 6 — Architecture and existing-pattern review
- Central modules checked:
- Duplication avoided:
- ADR needed:

### Pass 7 — Edge cases and regressions
- Edge cases:
- Negative paths:
- Regression tests:

### Pass 8 — Runtime, VM, and integration validation
- VM required:
- VM result:
- Integration checks:

### Pass 9 — GitHub state and closure verification
- PR state:
- Issue state:
- Parent/follow-up state:

### Pass 10 — Final honesty gate
- Acceptance criteria met:
- Honest status:
- Follow-up needed:
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

## Quality hardening rules

These rules exist to prevent repeated autonomous-agent mistakes.

### 1. GitHub reality beats local claims

Never rely only on local output or a previous report.

Before claiming something is merged, closed, complete, or current, verify GitHub state.

Required checks when relevant:

```bash
gh pr view <PR> --json state,mergedAt,mergeCommit,files,title,body
gh issue view <ISSUE> --comments
gh pr list --state open
gh issue list --state open
```

If `gh` is unavailable, use the GitHub API.

### 2. Open issue means not complete unless explicitly explained

If the GitHub issue is still open, do not say it is complete.

Allowed wording:

```text
Implementation appears complete, but GitHub issue is still open.
```

Then either close it with a technical comment or explain why it remains open.

### 3. Phase complete is not parent complete

A merged PR does not automatically complete the parent issue.

Use:

```text
Phase completed, parent issue not complete.
```

when any acceptance criterion remains.

### 4. Acceptance criteria must not be reinterpreted silently

If you satisfy an acceptance criterion by architecture rather than literal implementation, document it.

Example:

```text
The issue asked to update each module. We instead configured the parent logger so all child loggers inherit structured logging. This satisfies the runtime outcome through logging hierarchy.
```

If this is a non-obvious interpretation, record it in `docs/IGRIS_DECISIONS.md`.

### 5. Do not duplicate centralized logic

Before adding logic for:

- redaction
- auth
- routing
- approval
- memory
- logging
- diagnostics
- task state
- config

search for existing canonical modules.

If a central function exists, use it.

For redaction, prefer the centralized redaction function unless there is a documented layered reason.

If adding a local fallback or regex layer, document:

- why central logic is insufficient
- how divergence is prevented
- which tests prove consistency

### 6. No fake "no behavior change"

Do not say "no behavior change" if the change can alter runtime behavior.

Examples of behavior-impacting changes:

- narrowing exceptions
- changing logging handler behavior
- making file logging opt-in
- changing startup wiring
- fixing wrong method/attribute names
- changing auth/session/routing paths
- changing defaults or environment variables

Use accurate wording:

```text
Behavior intentionally hardened.
Expected failures are still handled; unexpected failures now surface.
Operational behavior changed: file logging is now opt-in.
Runtime bug fixed: previous code referenced a non-existent method.
```

### 7. VM is the runtime truth for runtime-impacting changes

Local tests are not enough for runtime-impacting work.

VM must be updated and checked when touching:

- API
- UI
- startup
- service
- logging startup
- task engine
- diagnostics
- auth/session
- routing
- memory
- file operations
- integrations

### 8. Tests must prove the actual claim

A test that only checks a string exists in source is weak.

Prefer tests that execute behavior.

Weak:

```text
source contains "configure_structured_logging"
```

Strong:

```text
create_app() configures logger and emitted log is JSON/redacted
```

Weak tests are allowed only as supplementary checks, not primary proof.

### 9. Record measurable before/after

Every non-trivial task must record before/after evidence.

Examples:

```text
pyright errors: 174 → 91
except Exception: 627 → 535
gauntlet: 14/15 Windows, 15/15 VM
self_repair_supervisor.py: 6013 lines → <new count>
```

### 10. Update VM after every merge

After every merge, even docs-only unless impossible:

```bash
ssh <VM_USER>@192.168.1.253
cd /home/igris/IGRIS_GPT
git fetch origin
git checkout main
git pull --ff-only origin main
sudo systemctl restart igris.service
/home/igris/IGRIS_GPT/.venv/bin/python -m igris.core.jarvis_core_gauntlet
```

If docs-only and restart is unnecessary, still update repo and run gauntlet when practical.

### 11. PR body must include proof, not only narrative

Every non-trivial PR must include:

- 10-pass completion review
- acceptance criteria table
- tests with command names and results
- VM validation when applicable
- before/after metrics
- honest status
- follow-up needed yes/no

### 12. Memory files must be internally consistent

Before merging, check that:

- `PROJECT_MEMORY`
- `HANDOFF`
- `OPEN_ITEMS`
- `WORKLOG`
- `DECISIONS`

do not contradict each other.

If a PR says an issue is complete but `OPEN_ITEMS` still says pending, fix the inconsistency before merge.

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
