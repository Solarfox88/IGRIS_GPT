# IGRIS Decisions

Architecture, security, and process decisions for IGRIS_GPT. Append a new ADR when a non-obvious decision is made.

## ADR-IGRIS-0001 — GitHub main + memory files are source of truth

**Date**: 2026-08-14
**Status**: accepted

**Decision**: All agents must reconstruct project state from GitHub `main` and the repository memory files (`AGENTS.md`, `docs/IGRIS_PROJECT_MEMORY.md`, `docs/IGRIS_HANDOFF.md`, `docs/IGRIS_WORKLOG.md`, `docs/IGRIS_DECISIONS.md`, `docs/IGRIS_OPEN_ITEMS.md`) before coding. Local working directories from previous sessions are not authoritative.

**Rationale**: Previous Codex/Claude sessions left multiple local clones with stale state. Relying on local context caused confusion and cross-project contamination. A single, versioned source of truth prevents this.

## ADR-IGRIS-0002 — Security guardrails are non-regression constraints

**Date**: 2026-08-14
**Status**: accepted

**Decision**: The following must never be weakened by any agent or PR:
- `write_auth` (PR #1293 / #1311)
- `dangerous_intent_routing` (PR #1332 / #1295)
- `centralized redaction` (PR #1334 / #1313)
- `memory_cross_session` / memory isolation (PR #1335 / #1294)
- auth sessions / approval policies

**Rationale**: These are the core security/safety baseline of IGRIS. Regression here would re-introduce vulnerabilities that were explicitly fixed in P0/P1 issues.

## ADR-IGRIS-0003 — #1312 C1 was partial

**Date**: 2026-08-14
**Status**: accepted

**Decision**: PR #1331 did not fully close the C1 monolith criterion because `igris/core/self_repair_supervisor.py` remained 6208 lines (target <2000). Issue #1312 is closed on GitHub, but the work is incomplete. Follow-up issue #1356 tracks Phase 3.

## ADR-IGRIS-0006 — Phase-merged ≠ complete; follow-up issues required

**Date**: 2026-08-14
**Status**: accepted

**Decision**: When a large issue (#1314, #1315, #1316, #1312) is addressed in phases, merging a Phase 1 or Phase 2 PR does NOT close the parent issue. The parent issue remains open (or a follow-up issue is created) until ALL acceptance criteria are met.

**Rationale**: Declaring "roadmap complete" when only Phase 1 is merged is misleading. The original issues have specific acceptance criteria (e.g., <50 `except Exception`, all modules with structured logging, pyright standard mode, <2,000 lines) that are NOT met by Phase 1 alone.

**Current follow-up issues**:
- #1353 → #1314 Phase 2 (except Exception → specific types)
- #1354 → #1315 Phase 2 (structured logging rollout)
- #1355 → #1316 Phase 2 (pyright enforcement + standard mode)
- #1356 → #1312 Phase 3 (supervisor split <2,000 lines)

## ADR-IGRIS-0007 — VM gauntlet must use .venv Python, not system python3

**Date**: 2026-08-14
**Status**: accepted

**Decision**: The IGRIS VM gauntlet must be run with `/home/igris/IGRIS_GPT/.venv/bin/python -m igris.core.jarvis_core_gauntlet`, not system `python3`. The `igris.service` systemd unit uses `.venv/bin/python` (Python 3.12.3 with fastapi 0.136.1). System `python3` lacks fastapi and cannot import `igris.web.server`.

**Rationale**: Running the gauntlet with the wrong Python produces false failures (ModuleNotFoundError: No module named 'fastapi') that do not reflect the actual runtime state. The service's venv is the authoritative environment.

**Rationale**: The handoff explicitly required the file to be split below 2000 lines. The merge only extracted 4 sub-modules but did not reduce the main file enough. Calling it "done" would hide real tech debt.

## ADR-IGRIS-0004 — No direct work on main

**Date**: 2026-08-14
**Status**: accepted

**Decision**: All work must happen on feature/fix branches (`fix/NNNN-*`, `feat/NNNN-*`, `docs/...`, `chore/...`) and merge via PR. Never commit directly to `main`.

**Rationale**: Direct commits to `main` bypass review and make regression hard to isolate. The project has an active PR-based workflow (EPIC #1301 is using PR1–PR5A).

## ADR-IGRIS-0005 — .local/ is for agent-local reports, never committed

**Date**: 2026-08-14
**Status**: accepted

**Decision**: The `.local/` directory holds agent-local handoff/context reports (e.g. `DEVIN_IGRIS_HANDOFF_CONTEXT.md`) and must never be committed to the repository. Persistent memory lives in `AGENTS.md` and `docs/IGRIS_*.md` (which ARE committed).

**Rationale**: Local reports are agent-specific and may contain transient state. The repo memory files are the shared, versioned source of truth.

## ADR-IGRIS-0008 — Mandatory 5-pass completion rule

**Date**: 2026-08-14
**Status**: superseded by ADR-IGRIS-0009

**Decision**: Every IGRIS task must follow the mandatory 5-pass completion rule before being declared complete, ready to merge, ready to close, or production-ready.

The rule applies to all work types: issues, PRs, bugfixes, refactors, tests, docs affecting operations, CI, VM validation, security hardening, and roadmap items.

**Rationale**: Previous autonomous work sometimes marked roadmap items as complete after a single phase even when follow-up work remained. The 5-pass rule forces rereading the issue, reviewing the diff, checking edge cases, validating safety/VM/memory, and making an honest final acceptance decision.

**Consequences**:

- Agents must read memory files before starting any task.
- Agents must explicitly report that memory files were read.
- Every non-trivial PR must include a 5-pass completion review.
- Parent issues cannot be closed when only a phase is complete.
- Follow-up issues must be created when acceptance criteria remain unmet.

## ADR-IGRIS-0009 — Mandatory 10-pass completion and quality hardening

**Date**: 2026-08-14
**Status**: superseded by ADR-IGRIS-0011

**Decision**: The previous mandatory 5-pass rule is replaced by a stricter mandatory 10-pass completion rule for all IGRIS work.

The 10 passes are:

1. memory and task intake
2. acceptance criteria extraction
3. baseline and evidence collection
4. first focused implementation
5. self-review against issue and diff
6. architecture and existing-pattern review
7. edge cases, negative paths, and regression review
8. runtime, VM, and integration validation
9. GitHub state and closure verification
10. final honesty gate and memory update

**Rationale**: The 5-pass process improved quality, but recent work still showed recurring weaknesses: claiming parent completion while GitHub issues remained open, loosely interpreting acceptance criteria, duplicating redaction logic instead of clearly using the centralized implementation, and describing runtime-impacting changes as "no behavior change".

**Consequences**:

- No work can be called complete before all 10 passes are performed.
- GitHub state must be verified before claiming merge/closure/completion.
- Acceptance criteria must be satisfied literally or any architectural interpretation must be documented.
- Centralized logic must be reused where available.
- Runtime-impacting work requires VM validation.
- PR bodies and final reports must include a 10-pass review and honest status.
- Quality hardening rules (GitHub reality, no fake "no behavior change", centralized-logic reuse, VM validation, measurable before/after, memory consistency) are mandatory.

## ADR-IGRIS-0010 — Traceable validation evidence required

**Date**: 2026-08-14
**Status**: accepted

**Decision**: Runtime-impacting PRs must include traceable VM/runtime validation evidence. A narrative claim such as "VM validated" or "gauntlet passed" is not sufficient.

**Required evidence**:

- VM name/IP/URL
- VM branch and commit SHA
- service status result
- exact gauntlet command and summary
- diagnostics endpoint result
- os/brief endpoint result
- post-merge VM update proof

**Rationale**: Previous work correctly performed VM validation, but the evidence was sometimes only present in conversational reports, not in a reliably auditable PR body or memory record. To reach 10/10 quality, runtime validation must be reproducible and traceable.

**Consequences**:

- Runtime-impacting PRs without validation evidence are not complete.
- VM validation must be reported with commands and results.
- Memory files must record post-merge VM state when relevant.

## ADR-IGRIS-0011 — Mandatory 20-pass quality gate

**Date**: 2026-08-14
**Status**: accepted

**Decision**: The mandatory 10-pass rule is superseded by a stricter mandatory 20-pass quality gate for all IGRIS work.

The 20-pass gate expands the previous process with explicit GitHub reality checks, architecture checks, risk classification, local smoke validation, security/privacy review, behavior-change honesty, VM branch validation, post-merge VM verification, and final status control.

**Rationale**: The 10-pass process produced significantly better work, but the project now requires a larger autonomous roadmap. To safely execute multiple consecutive blocks without user review after every PR, each block must include stronger self-checking and traceable validation.

**Consequences**:

- No non-trivial task may be declared complete before all 20 passes are performed.
- Runtime-impacting work requires VM branch validation and post-merge VM verification.
- GitHub state must be verified before claiming merge, closure, or completion.
- Memory files must remain internally consistent.
- Every block in a roadmap must have measurable before/after evidence.
- Parent issues cannot be closed when only a phase is complete.

## ADR-IGRIS-0012 — Process correction hardening

**Date**: 2026-08-15
**Status**: accepted

**Decision**: The 20-pass quality gate is extended with hard process-correction rules.

The new hard rules are:

1. Never commit directly on `main`.
2. Runtime-impacting work must complete VM branch validation before merge.
3. Post-merge VM validation does not replace branch validation.
4. If VM branch validation is unavailable, the block must be marked `Blocked`, not merged.
5. Final roadmap reports must use a per-block compliance matrix with `complete`, `partial`, `missing`, `not applicable`, or `blocked`.

**Rationale**: The previous roadmap produced useful work, but it included process deviations: an accidental direct commit to `main` and at least one runtime-impacting merge after SSH/VM branch-validation timeout. These deviations must be prevented before continuing autonomous multi-block work.

**Consequences**:

- Direct commits to `main` prevent a 10/10 quality rating.
- Runtime-impacting PRs without branch VM validation are incomplete unless explicitly approved as exceptions.
- Final reports must distinguish full compliance from partial compliance.
- Roadmap progress must remain honest even when useful code was merged.

## ADR-IGRIS-0013 — Import graph validation required for core refactors

**Date**: 2026-08-15
**Status**: accepted

**Decision**: Core refactors must include import graph validation before merge. This is mandatory for supervisor, memory, task engine, routing, diagnostics, auth/security, logging, and shared helper/model modules.

**Rationale**: A previous supervisor extraction introduced a circular import that was caught and fixed in a follow-up PR. Future refactors must detect this class of error before merge.

**Consequences**:

- Runtime-impacting refactors must run compileall and import graph smoke tests.
- Supervisor refactors must import every `igris.core.supervisor*.py` module before merge.
- Circular import fixes must be documented and validated on VM.
- A PR missing import graph evidence is not complete.
