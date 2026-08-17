# IGRIS Handoff

The exact point where work resumes. Updated by every agent at the end of each task.

Last updated: 2026-08-17 (Block 31 — #1354 acceptance criteria met by architecture)

## Process violation recorded (2026-08-16)

Block 29 post-merge docs update was committed directly on `main` (commit `590d978`), violating ADR-IGRIS-0012 and the "never commit on main" rule.

- Content: docs-only (4 memory markdown files)
- Runtime impact: none
- Force-push: no
- Remote history rewrite: no
- Repair: process correction PR + compliance matrix update
- Block 29 process rating: **not 10/10**

**The next agent MUST verify `git branch --show-current` returns a feature branch (not `main`) before every commit, including post-merge docs updates. No commit is "too small for a branch."**

See: `docs/PROCESS_CORRECTION_BLOCK29_DIRECT_MAIN.md`

## Mandatory process before next task

Before starting any next task, every agent must:

1. sync `main`
2. read `AGENTS.md`
3. read all `docs/IGRIS_*.md` memory files
4. read the GitHub issue/PR and comments
5. apply the **mandatory 20-pass quality gate** (see `AGENTS.md`)
6. follow the quality hardening rules (GitHub-state verification, no fake "no behavior change", centralized-logic reuse, VM validation, measurable before/after, memory consistency, traceable validation evidence)
7. update memory files before PR/merge/close
8. validate on VM when runtime-impacting — include traceable evidence (VM commit, branch, service status, gauntlet command+result, diagnostics/os-brief endpoints, post-merge proof)

Skipping this process is not allowed.

## Process correction hardening

The 20-pass quality gate now includes hard correction rules (ADR-IGRIS-0012):

- never commit directly on `main`
- verify branch before every commit
- runtime-impacting work requires VM branch validation before merge
- post-merge VM validation does not replace branch validation
- if VM/SSH validation is unavailable, runtime-impacting work is blocked unless the user explicitly approves an exception
- final roadmap reports must include a per-block compliance matrix

## Import graph validation

Core refactors must include compile/import graph validation before merge (ADR-IGRIS-0013).

Required for supervisor, task engine, memory, routing, diagnostics, auth/security, logging, and shared helper/model modules.

Supervisor refactors must import every `igris.core.supervisor*.py` module before merge.

A runtime refactor with missing import graph evidence is not complete.

## Current next issue

**Block 32 complete (pending merge) — #1354 Phase 4 web routers N/A (all inherit structured logging).**

20-block roadmap (Blocks 21-40) progress:
- Blocks 21-26: supervisor extraction complete (3125→1844 lines). #1371 closed, #1356 closed, #1395 created.
- Block 27: except Exception Phase 6 (394→353, PR #1397 merged `a547a8e`)
- Block 28: except Exception Phase 7 (353→286, PR #1398 merged `8f2ff1e`)
- Block 29: except Exception Phase 8 (286→179, PR #1399 merged `4f80984`) — complete, process deviation documented (PR #1400)
- Block 30: #1353 final count — 179 remain, issue OPEN (PR #1401 merged `97d5b88`)
- Block 31: #1354 Phase 3 — acceptance criteria met by architecture (PR #1402 merged `09d92c9`)
- Block 32: #1354 Phase 4 — web routers N/A, all web loggers inherit from "igris" root — **pending merge**
- Block 33: #1354 Phase 5 — event naming and log-level hardening
- Block 34: #1354 closure check
- Block 35: post-pyright standard mode assessment
- Block 36: CI health and workflow audit
- Block 37: VM diagnostics starvation investigation
- Block 38: task starvation remediation if safe
- Block 39: final repo health audit
- Block 40: final 20-block audit and memory consolidation

**Open issues:**
- #1353: except Exception cleanup — 178 remain (target <50). Phase 8 complete, Phase 9 pending.
- #1354: structured logging rollout — broader scope, foundation complete.
- #1395: agent_reasoning_loop.py 2,477 lines (target <2,000).
- #1290: diagnostics starvation — deferred to Block 37.
- #1300, #1301: EPICs still open.

**Closed issues:**
- #1371 (supervisor split, 1844<2000), #1356 (same), #1355 (pyright 0 errors, CI blocking), #1315 (structured logging foundation complete), #1296 (task engine), #1291 (chat intent auth).

Previous 10-block roadmap (#1) complete:
- #1356 Phase 4: supervisor 6011→4874 lines (5 PRs #1366-#1370)
- #1355 Phase 3: pyright 94→70 errors (PR #1373); supervisor errors 19→0
- #1353 Phase 3: except Exception 535→506 (PR #1374)
- #1315/#1354: StructuredFormatter aligned with centralized redaction (PR #1375)

**Roadmap primary items addressed in Phase 1/2/3. Follow-up issues open: #1353, #1355, #1356.**

The roadmap is NOT "complete" — it is "primary phases merged, follow-up phases pending":
- #1296 and #1291 are completed and closed.
- #1345 is merged.
- #1353 Phase 2 merged (PR #1360 `8ed5ac0`); parent #1314 still open (535 `except Exception` remain, target <50).
- #1354 Phase 2 merged (PR #1361 `6131bb9`); parent #1315 acceptance criteria met.
- #1355 Phase 2 merged (PR #1359 `7d2181f`); parent #1316 still open (91 pyright errors remain, CI `|| true`).
- #1312 was closed on GitHub but work is incomplete; follow-up #1356 Phase 3 in progress (6,011 lines, target <2,000).

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

1. Blocks 31-34: #1354 structured logging adoption (core modules, web routers, event naming, closure check)
2. Block 35: post-pyright standard mode assessment
3. Block 36: CI health and workflow audit (CI is currently failing on main — pre-existing pyright unused-import errors + test ordering issues)
4. Block 37: VM diagnostics starvation investigation
5. Block 38: task starvation remediation if safe
6. Block 39: final repo health audit
7. Block 40: final 20-block audit, compliance matrix, memory consolidation
8. After Block 40: continue #1353 narrowing (116 narrowable remaining, target <50)
9. Do NOT declare issues complete until acceptance criteria are fully met
