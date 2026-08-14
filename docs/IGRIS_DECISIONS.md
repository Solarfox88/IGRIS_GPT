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

**Decision**: PR #1331 did not fully close the C1 monolith criterion because `igris/core/self_repair_supervisor.py` remained 6208 lines (target <2000). Issue #1312 is closed on GitHub, but the work is incomplete. A follow-up issue should be filed to finish the split.

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
