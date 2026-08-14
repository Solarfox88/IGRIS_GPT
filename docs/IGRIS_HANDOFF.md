# IGRIS Handoff

The exact point where work resumes. Updated by every agent at the end of each task.

Last updated: 2026-08-14 (mandatory 10-pass rule + quality hardening added)

## Mandatory process before next task

Before starting any next task, every agent must:

1. sync `main`
2. read `AGENTS.md`
3. read all `docs/IGRIS_*.md` memory files
4. read the GitHub issue/PR and comments
5. apply the **mandatory 10-pass completion rule** (see `AGENTS.md`)
6. follow the quality hardening rules (GitHub-state verification, no fake "no behavior change", centralized-logic reuse, VM validation, measurable before/after, memory consistency)
7. update memory files before PR/merge/close
8. validate on VM when runtime-impacting

Skipping this process is not allowed.

## Current next issue

**Process upgrade: 5-pass → 10-pass mandatory completion rule + quality hardening rules.**

The mandatory 10-pass completion rule replaces the previous 5-pass rule. Quality hardening rules added to prevent false completion, duplicated centralized logic, missing VM validation, and inconsistent memory state. See `AGENTS.md` and ADR-IGRIS-0009.

**Next code issue: #1356 — supervisor split Phase 3** (after process upgrade is merged).

**Roadmap primary items addressed in Phase 1/2. Follow-up issues open: #1353, #1355, #1356.**

The roadmap is NOT "complete" — it is "primary phases merged, follow-up phases pending":
- #1296 and #1291 are completed and closed.
- #1345 is merged.
- #1353 Phase 2 merged (PR #1360 `8ed5ac0`); parent #1314 still open (535 `except Exception` remain, target <50).
- #1354 Phase 2 merged (PR #1361 `6131bb9`); parent #1315 acceptance criteria met.
- #1355 Phase 2 merged (PR #1359 `7d2181f`); parent #1316 still open (91 pyright errors remain, CI `|| true`).
- #1312 was closed on GitHub but work is incomplete; follow-up #1356 tracks Phase 3.

## Follow-up issues (created 2026-08-14)

| Issue | Title | Parent |
|---|---|---|
| #1353 | Continue except Exception cleanup — replace with specific exceptions | #1314 Phase 2 |
| #1354 | Structured logging rollout — remaining modules + hardening | #1315 Phase 2 |
| #1355 | Pyright enforcement — fix type errors, progress to standard mode | #1316 Phase 2 |
| #1356 | Finish supervisor split — self_repair_supervisor.py below 2,000 lines | #1312 Phase 3 |

## Completed: #1296 (fully closed)

PR #1347 merged as `8fa9d8e`. Issue #1296 closed 2026-08-14T13:19:05Z.
- Task engine worker step (`process_one_pending_task`)
- Safe validate endpoint (405/422, never 500)
- Honest diagnostics (`task_engine_state`)
- Context aggregator wires `task_engine` from `app.state`
- Gauntlet check `task_engine_reliability` (15th)
- VM validated at http://192.168.1.253:7778

## Completed: #1291 (fully closed)

PR #1348 merged as `19a1dc4`. Issue #1291 closed 2026-08-14T13:29:06Z.
- `/api/chat/intent` now uses `JarvisRequestRouter` to classify messages
- Limited users get `blocked=true, scope_denied=true` on code_change/patching
- Admin users get `approval_required=true` (not blocked) on code_change
- VM validated: limited → blocked=true, admin → approval_required=true

## Completed: #1345 (merged)

PR #1345 merged as `54b6b60`. 13 guard tests + docs/auth-contract.md.
No runtime changes — codifies auth/preflight contract as executable invariants.

## Partial: #1314 Phase 1 (merged, Phase 2 pending — follow-up #1353)

PR #1349 merged as `0ac7a7b`. Issue #1314 still open.
- Phase 1: Added `logger.debug(..., exc_info=True)` to 46 silent catches in 16 `igris/core/` files
- Phase 2 pending: Replace `except Exception` with specific exception types (476 → <50 target)

## Partial: #1315 Phase 1 (merged, Phase 2 pending — follow-up #1354)

PR #1350 merged as `79fe072`. Issue #1315 still open.
- Phase 1: `StructuredFormatter` + logging in 7 priority modules
- Phase 2 pending: Rollout to remaining ~30 modules, wire into server startup

## Partial: #1316 Phase 1 (merged, Phase 2 pending — follow-up #1355)

PR #1351 merged as `9866bf5`. Issue #1316 still open.
- Phase 1: Pyright config (basic mode) + CI job (non-blocking)
- Phase 2 pending: Fix type errors, make CI blocking, progress to standard mode

## Partial: #1312 Phase 2 (merged, Phase 3 pending — follow-up #1356)

PR #1352 merged as `67c3783`. Issue #1312 closed on GitHub but incomplete.
- Phase 1: 8 sub-modules extracted (dataclasses, backend, analysis, API, etc.)
- Phase 2: 36 static methods extracted to `supervisor_helpers.py` (576 lines)
- `self_repair_supervisor.py` still 6,013 lines (target <2,000)
- Phase 3 pending: Extract ~4,000 more lines (mission planning, repair cycle, decomposition, completion)

## Gauntlet fix (this checkpoint)

Fixed `task_engine_reliability` gauntlet check — `mkdir(parents=True)` without `exist_ok=True`
caused `[Errno 17] File exists` on Linux when TaskEngine.__init__ pre-creates directories.
Fix: added `exist_ok=True` to mkdir calls in `jarvis_core_gauntlet.py`.

VM gauntlet result after fix: **15/15 PASSED** (Linux, via `.venv/bin/python`).

## Hyper-V VM status (2026-08-14, latest checkpoint)

| Field | Value |
|---|---|
| VM | IGRIS-GPT |
| IP | 192.168.1.253 (static, on IGRIS External Switch) |
| URL | http://192.168.1.253:7778 |
| Branch | main |
| Commit | 84b39ef (latest) |
| Service | igris.service (systemd, active, `.venv/bin/python` uvicorn on 0.0.0.0:7778) |
| Python env | `/home/igris/IGRIS_GPT/.venv/bin/python` (Python 3.12.3, fastapi 0.136.1) |
| Gauntlet | 15/15 PASSED (via `.venv/bin/python -m igris.core.jarvis_core_gauntlet`) |
| diagnostics | HTTP 200 — task_engine_state present, starvation_detected=true (3 old pending tasks) |
| os/brief | HTTP 200 — ok=true, backends: unified_memory=ok, git=ok, rank_gauntlet=ok |
| chat/intent | limited+code_change → blocked=true, scope_denied=true; admin → approval_required=true |

VM access: SSH (user=igris, password=igris) to 192.168.1.253.
Network: IGRIS External Switch, static IP 192.168.1.253/24, gateway 192.168.1.1.

## Do next

1. Pick a follow-up issue (#1353, #1354, #1355, or #1356)
2. Follow the standard procedure: sync main, read memory files, create branch, diagnose, fix, test, gauntlet, VM validate, PR, merge
3. Do NOT declare issues complete until acceptance criteria are fully met
