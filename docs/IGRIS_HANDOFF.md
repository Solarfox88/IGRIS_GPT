# IGRIS Handoff

The exact point where work resumes. Updated by every agent at the end of each task.

Last updated: 2026-08-27 (#1322 Phase 3 subprocess governance lint)

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

**Third roadmap COMPLETE. 6 PRs merged, 6 issues advanced to Phase 2 (all remain open). 3 child issues created for #1307. Stabilization audit passed: 7217 tests, 0 errors pyright, 15/15 gauntlet, VM healthy.**

### Third roadmap completed (2026-08-27)

| # | Issue | PR | State | Phase |
|---|---|---|---|---|
| 1 | #1322 | #1441 | OPEN | Phase 2 (migrate 16 calls). Phase 3 (lint rule + INFRASTRUCTURE) pending |
| 2 | #1324 | #1442 | OPEN | Phase 2 (trace middleware). Phase 3 (OTel SDK) pending |
| 3 | #1325 | #1443 | OPEN | Phase 2 (plugin API). Phase 3 (UI + sandboxing) pending |
| 4 | #1323 | #1444 | OPEN | Phase 2 (word streaming). Phase 3 (real token streaming) pending |
| 5 | #1328 | #1445 | OPEN | Phase 2 (interaction tests). Broader coverage pending |
| 6 | #1307 | #1449 | OPEN | Child issues #1446, #1447, #1448 created |

### Third roadmap audit results (2026-08-27)

- compileall: PASS
- pyright: 0 errors, 915 warnings
- pytest: 7217 passed, 40 skipped, 0 failed
- targeted suites: 184 passed, 25 skipped (E2E gated)
- VM gauntlet: 15/15 PASSED
- VM pyright: 0 errors, 910 warnings
- VM diagnostics: healthy=true, 0 findings
- VM os/brief: ok=true
- VM trace headers: x-trace-id, x-request-id on every response
- VM plugin API: {"plugins":[],"count":0}
- Subprocess governance: 4 migrated modules clean. 25 unauthorized INFRASTRUCTURE imports remain.
- Trace middleware: X-Trace-Id propagation verified
- Plugin API: read-only, no execution, no secret leakage
- WebSocket streaming: word_split fallback, auth enforced
- Playwright E2E: 25 tests, all skip by default
- #1307 children: #1446, #1447, #1448 all OPEN

### Next roadmap priority

1. #1322 Phase 3 — lint rule + INFRASTRUCTURE migration
2. #1324 Phase 3 — OTel SDK bridge/export
3. #1325 Phase 3 — plugin UI integration
4. #1323 Phase 3 — real token streaming
5. #1328 — broader interaction coverage
6. #1446 — worktree recovery
7. #1447 — provider degraded states
8. #1448 — partial restore
- WebSocket smoke: OK (auth integration, admin-only /ws/loop, error handling)
- Plugin safety smoke: OK (discovery limited to configured dirs, no sandboxing yet)
- Integration gating: 13 skipped (IGRIS_INTEGRATION_TESTS=1)
- E2E gating: 15 skipped (IGRIS_E2E_TESTS=1)

### Next recommended roadmap (Phase 2 focus)

| Priority | Issue | Scope | Risk |
|---:|---|---|---|
| 1 | #1322 Phase 2 | Migrate 18 subprocess calls to ToolRuntime | Medium |
| 2 | #1324 Phase 2 | FastAPI middleware auto-inject trace_id | Low |
| 3 | #1325 Phase 2 | Plugin API endpoint (/api/plugins) | Low |
| 4 | #1323 Phase 2 | Token-by-token LLM streaming via WebSocket | Medium |
| 5 | #1328 Phase 2 | Playwright interaction tests (login, chat, task) | Low |
| 6 | #1307 follow-up | Worktree recovery / provider degraded states | Medium |
| 7 | #1327 | Docker Compose production-ready | Medium |
| 8 | #1326 | Multi-tenancy RBAC | High |
| 9 | #1306 | Observability health dashboard | Medium |
| 10 | pyright warnings | Bounded warning reduction (unused imports/vars) | Low |

## Final 20-block audit summary

| Block | PR | Result |
|---|---|---|
| Part A | #1389 | Circular-import hardening + ADR-IGRIS-0013 |
| 21-26 | #1390-#1396 | Supervisor extraction (3125→1844 lines) |
| 27-30 | #1397-#1401 | except Exception cleanup (286→179, target <50) |
| 29 correction | #1400 | Direct-main process deviation repaired |
| 31-34 | #1402-#1405 | Structured logging — criteria met by architecture, #1354 closed |
| 35 | #1406 | Pyright standard mode assessment — not ready (65 vs 7 errors) |
| 36 | #1407 | CI health fix — 7 pyright errors → 0, RuntimeError catches |
| 37 | #1408 | Diagnostics starvation false positive fixed, #1290 closed |
| 38 | #1409 | Task starvation remediation — 3 stale tasks processed |
| 39 | #1410 | Final repo health audit |
| 40 | (this PR) | Final 20-block audit and memory consolidation |

## Process compliance

- No direct-main commits (except Block 29 deviation, repaired by PR #1400)
- No force-pushes
- No security regressions
- All runtime-impacting changes VM-validated (15/15 gauntlet)
- All memory updates through feature branches and PRs
- Block 29 process rating: not 10/10 (direct-main deviation)
- All other blocks: 10/10 process compliance

## Final metrics

| Metric | Value |
|---|---|
| pyright errors | 0 |
| pyright warnings | 897 |
| except Exception count | 47 (target <50, achieved) |
| supervisor lines | 1844 (target <2000, achieved) |
| agent_reasoning_loop lines | 1968 (target <2000, achieved) |
| app.js lines | 170 (from 2401, modularized into 13 ES modules) |
| Open issues | 27 |
| Open PRs | 0 |
| VM gauntlet | 15/15 PASSED |
| Full pytest | 7113 passed, 2 skipped, 0 failed |
| VM diagnostics | healthy=true |
| VM os/brief | ok=true |

## Remaining work (deferred)

- #1353: except Exception cleanup — 76 remain (75 annotated boundaries, 1 docstring; target <50 not met — future phases needed to reduce boundary count or accept 76 as practical minimum).
- #1395: agent_reasoning_loop.py 2,477 lines (target <2,000). Refactor needed.
- #1300, #1301: EPICs (live acceptance harness, auth SSOT).
- #1317-1330: M1-M8 improvement issues.
- Pre-existing CI test failures (caplog/structured-logging, RuntimeError mocks, source-text assertions).
- Pyright standard mode not ready (65 errors vs 7 in basic).

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

## VM status (2026-08-20, latest checkpoint — KVM/QEMU)

| Field | Value |
|---|---|
| VM | KVM/QEMU (Ubuntu 24.04 cloud image, 4GB RAM, 4 vCPU) |
| IP | 192.168.122.65 (KVM NAT network) |
| URL | http://192.168.122.65:7778 |
| Branch | fix/1353-except-exception-phase9 |
| Commit | 60e80d8 |
| Service | igris.service (systemd, active, uvicorn on 0.0.0.0:7778) |
| Python env | `.venv/bin/python` (Python 3.12.3) |
| Gauntlet | 15/15 PASSED (via `.venv/bin/python -m igris.core.jarvis_core_gauntlet`) |
| diagnostics | healthy=true |
| os/brief | ok=true |

VM access: `sshpass -p igris ssh igris@192.168.122.65` (password auth, KVM NAT network).
Previous Hyper-V VM at 192.168.1.253 is no longer in use (VHDX could not boot on KVM — EFI bootloader missing).

## Do next

1. ~~Merge PR for Phase 9 of #1353~~ — DONE (PR #1413 merged e1a1797)
2. ~~Post-merge VM validation~~ — DONE (VM e1a1797, gauntlet 15/15, healthy=true, ok=true)
3. ~~CI test health cleanup~~ — DONE (CI already green via PR #1412; .local/ gitignore fix aligns local with CI, PR #1415 merged)
4. ~~#1353 final cleanup~~ — DONE (76→49→47, target <50 MET, #1353 CLOSED, PR #1416 merged)
5. ~~#1314 parent evaluation~~ — DONE (all 5 criteria MET, #1314 CLOSED)
6. ~~#1417 follow-up~~ — DONE (141 catches now log, 13 silent pass kept, #1417 CLOSED)
7. Continue #1395 (agent_reasoning_loop.py split — 2,477 lines, target <2,000)
8. Do NOT declare issues complete until acceptance criteria are fully met

### #1322 Phase 3 completed (2026-08-27)

- PR #1451 merged: subprocess governance lint rule
- AST-based check: scripts/check_subprocess_governance.py
- 13 pytest tests: tests/test_subprocess_governance_1322.py
- Policy: 3 always-allowed + 25 infrastructure-allowed + 4 forbidden
- #1322 remains OPEN (Phase 4: INFRASTRUCTURE migration)
- Next: #1322 Phase 4 or next roadmap priority
