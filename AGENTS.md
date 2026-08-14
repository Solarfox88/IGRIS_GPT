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

## Mandatory 20-pass quality gate

Every IGRIS task must follow the mandatory 20-pass quality gate before it can be called complete, ready to merge, ready to close, production-ready, or fully resolved.

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

## The 20 mandatory passes

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
20-pass quality gate loaded: yes
Issue/PR read: yes
Current main commit: <commit>
```

### Pass 2 — GitHub reality check

Verify GitHub state before trusting local memory.

Check when relevant:

```bash
gh pr list --state open --repo Solarfox88/IGRIS_GPT
gh issue list --state open --repo Solarfox88/IGRIS_GPT
gh issue view <ISSUE> --repo Solarfox88/IGRIS_GPT --comments
gh pr view <PR> --repo Solarfox88/IGRIS_GPT --json state,mergedAt,mergeCommit,files,title,body
```

If `gh` is unavailable, use GitHub API.

GitHub reality beats local claims.

### Pass 3 — Acceptance criteria extraction

Extract the issue into explicit acceptance criteria.

For each criterion define:

- what proves completion
- required tests
- required runtime/VM evidence
- non-goals
- safety constraints
- what makes the work only phase-complete

### Pass 4 — Prior decisions and architecture check

Read relevant ADRs and existing architecture.

Check:

- centralized redaction
- auth/write guardrails
- dangerous intent routing
- memory isolation
- task engine behavior
- diagnostics
- logging
- VM validation rules
- existing helper modules

Do not duplicate central logic without a documented reason.

### Pass 5 — Baseline and measurable evidence

Before modifying code, record measurable baseline.

Examples:

- file line counts
- method counts
- error counts
- failing tests
- gauntlet state
- endpoint behavior
- VM commit
- current issue state
- current PR state
- current open-items state

### Pass 6 — Risk classification

Classify the work as:

- docs-only
- test-only
- config-only
- low-risk runtime
- medium-risk runtime
- high-risk runtime
- security-impacting
- architecture/refactor-impacting

Define required validation level.

Runtime, security, startup, API, memory, supervisor, auth, task engine, diagnostics, and logging changes require VM validation.

### Pass 7 — Minimal implementation plan

Write a small plan before editing.

Include:

- files to touch
- expected diff shape
- tests to add
- what will not be touched
- rollback idea
- expected honest status

Do not start broad rewrites without this plan.

### Pass 8 — First focused implementation

Implement the smallest safe improvement.

Rules:

- one cohesive scope
- no unrelated cleanup
- no broad rewrite
- no hidden behavior change
- no guardrail weakening
- tests added or updated

### Pass 9 — Local smoke and import check

Run fast local checks immediately after first implementation.

At minimum when relevant:

```bash
python -m compileall igris
pytest <targeted-tests> -q
```

Fix import/circular/dependency errors before continuing.

### Pass 10 — Self-review against issue and diff

Reread:

- original issue
- acceptance criteria
- full diff
- tests
- memory files

Find gaps. Apply at least one improvement or explicitly justify why no improvement exists.

### Pass 11 — Existing-pattern and duplication review

Search for existing canonical implementation.

Mandatory checks:

- am I duplicating redaction?
- am I duplicating auth?
- am I duplicating logging?
- am I duplicating routing?
- am I duplicating memory behavior?
- am I bypassing guardrails?
- am I creating a parallel API?

If a central module exists, use it.

### Pass 12 — Edge cases and negative paths

Check:

- invalid input
- missing files
- empty state
- stale state
- Windows/Linux differences
- locked files
- permission errors
- subprocess failures
- JSON parse failures
- network failures
- auth/session/trust failures
- unexpected exceptions

Add regression tests.

### Pass 13 — Security and privacy review

Verify:

- no secrets in logs
- no token/cookie/header leakage
- redaction uses central logic where possible
- write endpoints still gated
- dangerous operations still require approval
- limited users remain blocked where required
- no new unsafe default
- no weakening of safety checks

Run relevant safety tests.

### Pass 14 — Behavior-change honesty check

Do not say "no behavior change" unless literally true.

Use accurate wording:

```text
Behavior intentionally hardened.
Expected failures are still handled; unexpected failures now surface.
Operational behavior changed and documented.
Runtime bug fixed.
Docs-only change.
```

If behavior changes, document it.

### Pass 15 — Test expansion and full local validation

Run targeted tests and broader regression.

Use relevant commands, for example:

```bash
pytest tests/test_supervisor_split.py -q
pytest tests/test_task_engine_reliability.py -q
pytest tests/test_write_endpoint_auth_gate.py -q
pytest tests/test_dangerous_intent_routing.py -q
pytest tests/test_redaction_centralized.py -q
python -m igris.core.jarvis_core_gauntlet
```

Record exact results.

### Pass 16 — VM branch validation

For runtime-impacting work, validate the branch on VM before merge.

Required VM evidence:

```bash
ssh <VM_USER>@192.168.1.253
cd /home/igris/IGRIS_GPT
git fetch origin
git checkout <branch>
git pull --ff-only origin <branch> || true
git rev-parse HEAD
git branch --show-current
sudo systemctl restart igris.service
systemctl status igris.service --no-pager
/home/igris/IGRIS_GPT/.venv/bin/python -m igris.core.jarvis_core_gauntlet
curl -s http://127.0.0.1:7778/api/diagnostics/summary
curl -s http://127.0.0.1:7778/api/os/brief
```

From host:

```bash
Test-NetConnection 192.168.1.253 -Port 7778
curl.exe -s http://192.168.1.253:7778/api/diagnostics/summary
curl.exe -s http://192.168.1.253:7778/api/os/brief
```

### Pass 17 — Memory and open-items update

Update memory files before PR/merge:

- `docs/IGRIS_PROJECT_MEMORY.md`
- `docs/IGRIS_HANDOFF.md`
- `docs/IGRIS_OPEN_ITEMS.md`
- `docs/IGRIS_WORKLOG.md`
- `docs/IGRIS_DECISIONS.md` if architecture/process changed

Memory must be internally consistent.

Do not leave "pending merge" after merge.

### Pass 18 — PR creation with proof

Every non-trivial PR must include:

- acceptance criteria table
- before/after metrics
- 20-pass review
- tests with exact commands/results
- VM evidence when runtime-impacting
- GitHub issue state
- honest status
- follow-up needed yes/no

### Pass 19 — Post-merge GitHub and VM verification

After merge:

- verify PR merged on GitHub
- verify issue state on GitHub
- sync local main
- update VM to latest main
- restart service when relevant
- run VM gauntlet
- run diagnostics/os brief

Required post-merge VM evidence:

```text
Post-merge main commit:
VM commit:
VM branch:
Service status:
Gauntlet command:
Gauntlet result:
diagnostics/summary:
os/brief:
```

### Pass 20 — Final honesty gate

Final status must be one of:

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

If anything remains, create or update follow-up before moving on.

### Forbidden before pass 20

Before completing Pass 20, agents must not say or write:

- done
- completed
- production-complete
- ready to merge
- ready to close
- issue resolved
- roadmap complete
- parent issue complete

unless explicitly marked as a temporary note inside the 20-pass checklist.

### Honest completion rule

If after 20 passes the full acceptance criteria are not satisfied, the correct status is:

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
## 20-pass quality gate review

### Pass 1 — Memory and task intake
### Pass 2 — GitHub reality check
### Pass 3 — Acceptance criteria extraction
### Pass 4 — Prior decisions and architecture check
### Pass 5 — Baseline and measurable evidence
### Pass 6 — Risk classification
### Pass 7 — Minimal implementation plan
### Pass 8 — First focused implementation
### Pass 9 — Local smoke and import check
### Pass 10 — Self-review against issue and diff
### Pass 11 — Existing-pattern and duplication review
### Pass 12 — Edge cases and negative paths
### Pass 13 — Security and privacy review
### Pass 14 — Behavior-change honesty check
### Pass 15 — Test expansion and full local validation
### Pass 16 — VM branch validation
### Pass 17 — Memory and open-items update
### Pass 18 — PR creation with proof
### Pass 19 — Post-merge GitHub and VM verification
### Pass 20 — Final honesty gate
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

### 7a. Traceable validation evidence is required

A report saying "VM validated" or "gauntlet passed" is not enough.

Every runtime-impacting PR must include traceable validation evidence in the PR body and final report.

Required evidence:

- VM hostname/name
- VM IP/URL
- VM branch
- VM commit SHA
- service status command and result summary
- exact gauntlet command
- gauntlet result summary
- `diagnostics/summary` HTTP result
- `os/brief` HTTP result
- post-merge VM commit SHA
- post-merge gauntlet result

Required command examples:

```bash
# On VM
git rev-parse HEAD
git branch --show-current
systemctl status igris.service --no-pager
/home/igris/IGRIS_GPT/.venv/bin/python -m igris.core.jarvis_core_gauntlet
curl -s http://127.0.0.1:7778/api/diagnostics/summary
curl -s http://127.0.0.1:7778/api/os/brief
```

From host:

```bash
Test-NetConnection 192.168.1.253 -Port 7778
curl.exe -s http://192.168.1.253:7778/api/diagnostics/summary
curl.exe -s http://192.168.1.253:7778/api/os/brief
```

For docs-only PRs, VM runtime validation may be skipped, but the VM repository should still be updated to latest main after merge when practical.

If validation evidence is missing, the work cannot receive a 10/10 quality rating.

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
