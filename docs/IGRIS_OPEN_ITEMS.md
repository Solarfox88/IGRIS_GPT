# IGRIS Open Items

Open issues and tech debt for IGRIS_GPT. Updated after every task.

Last updated: 2026-08-17 (Block 31 — #1354 acceptance criteria met by architecture)

## Completion policy

Items in this file are not considered complete just because a PR was merged.

An item is complete only when:

- the issue acceptance criteria are satisfied
- the **mandatory 20-pass quality gate** has been completed
- tests/gauntlet pass
- VM validation is done when applicable — with traceable evidence (VM commit, branch, service status, gauntlet command+result, diagnostics/os-brief endpoints)
- memory files are updated
- no hidden follow-up remains
- GitHub issue state verified (open issue = not complete unless explicitly explained)

If only part of the work was done, mark the item as:

```text
Phase complete, follow-up pending.
```

## Process correction hardening

The 20-pass quality gate now includes hard correction rules (ADR-IGRIS-0012):

- never commit directly on `main`
- verify branch before every commit
- runtime-impacting work requires VM branch validation before merge
- post-merge VM validation does not replace branch validation
- if VM/SSH validation is unavailable, runtime-impacting work is blocked unless the user explicitly approves an exception
- final roadmap reports must include a per-block compliance matrix

## Process violations

| Date | Block | Violation | Impact | Repair | Status |
|---|---|---|---|---|---|
| 2026-08-16 | Block 29 | Post-merge docs update committed directly on `main` (`590d978`) | docs-only, no runtime impact | Process correction PR + compliance matrix update; direct-main guard reinforced | documented |

## Import graph validation

Core refactors must include compile/import graph validation before merge (ADR-IGRIS-0013).

Required for supervisor, task engine, memory, routing, diagnostics, auth/security, logging, and shared helper/model modules.

Supervisor refactors must import every `igris.core.supervisor*.py` module before merge.

A runtime refactor with missing import graph evidence is not complete.

## Priority issues

| Priority | Issue | Status | Next action |
|---|---|---|---|
| P1 | #1296 | **closed** (PR #1347 merged `8fa9d8e`) | Fixed — task engine worker, safe validate, honest diagnostics |
| P0 | #1300 | open (EPIC) | Live Acceptance Harness — browser/runtime E2E validation |
| P0 | #1301 | open (EPIC, active) | Auth & Session SSOT — PR1–PR5A merged (#1345 merged `54b6b60`) |
| P2 | #1291 | **closed** (PR #1348 merged `19a1dc4`) | Fixed — /api/chat/intent now gates code_change for limited users |
| P2 | #1290 | **closed** (PR #1408 Block 37 + Block 38 maintenance) | Fixed — starvation false positive corrected, 3 stale tasks processed, diagnostics now healthy=true |
| P2 | #1289 | open | API path inconsistency — `/api/github/prs`, `/api/github/issues`, `/api/git/log` do not exist |
| P2 | #1297 | open | Verifier/Reflection payload contract undocumented, misleading error |

## Tech debt

| Priority | Issue | Status | Next action |
|---|---|---|---|
| Critical | #1314 | **open** — Phase 1 merged (PR #1349 `0ac7a7b`), Phase 2 merged (PR #1360 `8ed5ac0`) | Follow-up: **#1353** — except Exception count reduced 627→178 (Phases 3-8 complete), target <50; 178 remain |
| Critical | #1315 | **closed** — foundation complete (PR #1375 `4877168`) | Follow-up: **#1354 CLOSED** — structured logging acceptance criteria met by architecture (all 107 loggers inherit StructuredFormatter from root "igris" logger) |
| Critical | #1316 | **closed** — pyright 0 errors, CI blocking (PR #1384 `bc435e5`) | Follow-up: **#1355** CLOSED — pyright errors 174→0, CI made blocking |
| Tech debt | #1312 | **closed** — supervisor split complete | Follow-up: **#1371** CLOSED — `self_repair_supervisor.py` 1,844 lines (below 2,000 target); #1356 CLOSED; follow-up **#1395** for `agent_reasoning_loop.py` (2,477 lines) |
| Refactor | #1317 (I1) | open | router anonymous routes `routes_01..10` — rename by domain |
| Refactor | #1318 (I2) | open | `app.js` monolithic 2401 lines — modularize into ES modules |
| Feature | #1319 (I4) | open | SQLite migration system / schema versioning |
| Testing | #1320 (I5) | open | integration tests with real LLM |
| Reliability | #1321 (I6) | open | graceful shutdown / crash recovery of loop state |
| Safety | #1322 (I3) | open | 80 direct subprocess calls bypass ToolRuntime |

## Milestones (M1–M8)

| Milestone | Issue | Status |
|---|---|---|
| M1 WebSocket streaming | #1323 | open |
| M2 OpenTelemetry / distributed tracing | #1324 | open |
| M3 Plugin system for extensible tools | #1325 | open |
| M4 Multi-tenancy with RBAC | #1326 | open |
| M5 Docker Compose production-ready | #1327 | open |
| M6 Playwright E2E tests | #1328 | open |
| M7 Rate limiting per-user | #1329 | open |
| M8 Backup automatico `.igris/` | #1330 | open |

## EPICs (P1)

| EPIC | Issue | Status |
|---|---|---|
| Memory Governance | #1302 | open |
| People Catalog | #1303 | open |
| Mission Control UX / Approval Center / Evidence Viewer | #1304 | open |
| Verifier Hard Gates / Capability Manifest | #1305 | open |
| Observability / Health Dashboard | #1306 | open |
| Reliability / Crash Recovery / Backup / Migration Safety | #1307 | open |
| Jarvis Red-Team Gauntlet | #1308 | open |
| Model Role Matrix / Benchmarking | #1309 | open |
| Product Documentation / Operator Runbooks | #1310 | open |

## Feature / research

| Issue | Status | Notes |
|---|---|---|
| #1333 | open | Live Graph Reactor UI |
| #682 | open | model role definition (Planner/Implementer/Critic/Escalation) |
| #625 | open | Vast.ai V100/GV100/RTX3090/RTX4090 tests |
| #620 | open | evaluate PrintingPress.dev |
| #527 | open | IGRIS as Personal OS paradigm |
| #352 | open | evaluate candidate reasoning models |
| #1271 | open | People Catalog / Person Registry — separate from identity/auth |
| #1355 | **CLOSED** — pyright 0 errors, CI blocking (PR #1384) | Closed 2026-08-15 |
| #1353 | Except Exception Phase 8 complete (286→179, PR #1399 merged `4f80984`); **179 remain (target <50)**. Phase 9 (Block 30): final count done — 63 boundaries (`# noqa: BLE001`), 116 narrowable. No `except Exception: pass` remaining. Progress comment posted. Issue remains OPEN. | Continue narrowing 116 non-boundary occurrences in future phases after roadmap Blocks 31-40 |
| #1371 | **CLOSED** — supervisor split complete, 1,844 lines (below 2,000) | Closed 2026-08-15 |
| #1395 | `agent_reasoning_loop.py` 2,477 lines (target <2,000) | Split agent_reasoning_loop.py |