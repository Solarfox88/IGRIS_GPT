# IGRIS Project Memory

Stable project state — source of truth for all agents.

Last updated: 2026-08-27 (#1322 Phase 3 subprocess governance lint)

## Repository

- repo: `Solarfox88/IGRIS_GPT` (public)
- default branch: `main`
- current `main` commit: `ec8a358` (post-#1322 Phase 3, subprocess governance lint)

## Mandatory operating method

IGRIS uses a mandatory 20-pass quality gate for all tasks.

No task, issue, PR, refactor, test change, CI change, runtime fix, VM validation, or security hardening may be declared complete before twenty review/improvement passes.

The full rule is canonical in `AGENTS.md`.

Summary:

1. memory and task intake
2. GitHub reality check
3. acceptance criteria extraction
4. prior decisions and architecture check
5. baseline and measurable evidence
6. risk classification
7. minimal implementation plan
8. first focused implementation
9. local smoke and import check
10. self-review against issue and diff
11. existing-pattern and duplication review
12. edge cases and negative paths
13. security and privacy review
14. behavior-change honesty check
15. test expansion and full local validation
16. VM branch validation
17. memory and open-items update
18. PR creation with proof
19. post-merge GitHub and VM verification
20. final honesty gate

If full acceptance criteria are not satisfied after twenty passes, the task must be marked:

```text
Phase completed, parent issue not complete.
```

and a follow-up issue must be created or updated.

## Quality hardening rules

The following quality hardening rules are mandatory (full text in `AGENTS.md`):

1. GitHub reality beats local claims — verify GitHub state before claiming merge/closure/completion
2. Open issue means not complete unless explicitly explained
3. Phase complete is not parent complete
4. Acceptance criteria must not be reinterpreted silently
5. Do not duplicate centralized logic — reuse canonical modules
6. No fake "no behavior change" — use accurate wording for behavior-impacting changes
7. VM is the runtime truth for runtime-impacting changes
7a. Traceable validation evidence is required — VM commit, branch, service status, gauntlet command+result, diagnostics/os-brief endpoints, post-merge VM proof
8. Tests must prove the actual claim — prefer behavioral tests over source-string checks
9. Record measurable before/after evidence
10. Update VM after every merge
11. PR body must include proof, not only narrative
12. Memory files must be internally consistent before merge
13. Never commit directly on `main` — verify branch before every commit (ADR-IGRIS-0012). **Violated on Block 29 (commit 590d978, docs-only). Process correction documented.**
14. VM branch validation is mandatory for runtime-impacting work and cannot be replaced by post-merge validation (ADR-IGRIS-0012)
15. Final roadmap reports must use a per-block compliance matrix with complete/partial/missing/not applicable/blocked (ADR-IGRIS-0012)
16. Import graph validation required for core refactors — compileall + import smoke tests + supervisor module imports (ADR-IGRIS-0013)

## Import graph validation

Core refactors must include compile/import graph validation before merge.

Required for supervisor, task engine, memory, routing, diagnostics, auth/security, logging, and shared helper/model modules.

Supervisor refactors must import every `igris.core.supervisor*.py` module before merge.

A runtime refactor with missing import graph evidence is not complete.

## Process correction hardening

The 20-pass quality gate now includes hard correction rules (ADR-IGRIS-0012):

- never commit directly on `main`
- verify branch before every commit
- runtime-impacting work requires VM branch validation before merge
- post-merge VM validation does not replace branch validation
- if VM/SSH validation is unavailable, runtime-impacting work is blocked unless the user explicitly approves an exception
- final roadmap reports must include a per-block compliance matrix

## Traceable validation evidence

Runtime-impacting work must include traceable VM evidence, not only narrative claims.

Required evidence includes:

- VM commit
- branch
- service status
- exact gauntlet command
- gauntlet result
- diagnostics endpoint result
- os/brief endpoint result
- post-merge VM update proof

A task cannot be considered production-complete if VM evidence is missing.

## Completed

| Area | Issue/PR | Status | Merge commit | Notes |
|---|---|---|---|---|
| Security — write auth | #1293 | done | `359df90` | P0 auth gate on all write/side-effect endpoints |
| Security — git commit gate | #1311 / PR #1311 | done | `f603e04` | gated `POST /api/tools/git/commit` and `POST /api/git/commit` with write auth |
| Safety — dangerous intent routing | #1295 / PR #1332 | done | `d453add` | never `chat_only` for `rm -rf`, issue create, sudo |
| Security — centralized redaction | #1313 / PR #1334 | done | `7d8d4c0` | secret redaction centralized (19 files touched) |
| Reliability — memory cross-session | #1294 / PR #1335 | done | `e716f68` | memory/preferences persist across sessions (23 files touched) |
| Refactor — supervisor C1 | #1312 / PR #1331 | **PARTIAL** | `ea3d70b` | extracted 4 sub-modules but `self_repair_supervisor.py` still 6208 lines (target <2000) |
| Supervisor split Phase 3 | #1356 / PR #1364 | **PARTIAL** (Phase 3) | `18bc8d8` | extracted mission planning to `supervisor_mission_planning.py` (523 lines); 6327→6011 lines |
| Supervisor split Phase 4 | #1356 / PRs #1366-#1370 | **PARTIAL** (Phase 4) | `235d5e7` | extracted completion/cleanup, repair helpers, decomposition (part 1+2), audit/persistence; 6011→4874 lines; still >2000 (target <2000); follow-up #1371 |
| Pyright Phase 3 | #1355 / PR #1373 | **PARTIAL** (Phase 3) | `08d44a4` | fixed 24 type errors (94→70); supervisor errors 19→0; 70 remain (target 0) |
| Except Exception Phase 3 | #1353 / PR #1374 | **PARTIAL** (Phase 3) | `be88695` | narrowed 29 broad catches (535→506); 506 remain (target <50) |
| Structured logging closure | #1315 / PR #1375 | **PARTIAL** | `4877168` | aligned StructuredFormatter with centralized safety.redact_secrets; #1315 and #1354 remain open |
| Task engine reliability | #1296 / PR #1347 | done | `8fa9d8e` | worker step, safe validate, honest diagnostics, gauntlet check |
| Code change gating | #1291 / PR #1348 | done | `19a1dc4` | /api/chat/intent gates code_change for limited users |
| Auth contract guard | #1301-PR5A / PR #1345 | done | `54b6b60` | 13 guard tests + docs/auth-contract.md |
| Except Exception cleanup | #1314 / PR #1349 | **PARTIAL** (Phase 1) | `0ac7a7b` | logging added to 46 silent catches; Phase 2 in progress (#1353: 627→535, 92 narrowed) |
| Structured logging | #1315 / PR #1350 | **PARTIAL** (Phase 1) | `79fe072` | StructuredFormatter + 7 priority modules; Phase 2 in progress (#1354: wired into server startup, redaction added, 12 new tests) |
| Pyright type checking | #1316 / PR #1351 | **PARTIAL** (Phase 1) | `9866bf5` | basic mode config + CI job; Phase 2 in progress (#1355: 174→91 errors, 48% reduction) |
| Supervisor split Phase 2 | #1312 / PR #1352 | **PARTIAL** (Phase 2) | `67c3783` | 36 static methods extracted to supervisor_helpers.py; still 6,013 lines (follow-up #1356) |
| Gauntlet mkdir fix | — | done | (pending merge) | fix `exist_ok=True` in gauntlet task_engine_reliability check |
| Auth — project root | #1286 | done | `914a665` | project_root mismatch fix |
| Auth — auth-first onboarding | #1278 | done | `a18b32b` | unauthenticated users gated before LLM |
| Auth — browser auth gate | #1285 | done | `59a90ed` | real browser auth gate |
| Auth — post-login state | #1283/#1284 | done | `e881ab5` | sidebar/chat state after login |
| Rate limiter | #1281 | done | `f8da9d7` | rate limiter on static assets/LAN fix |
| Debug registration | #1280 | done | `2d6fc3a` | normalize FastAPI errors |
| Auth root lazy | #1301-PR1 | done | `8cfc172` | eliminate import-time IGRIS_PROJECT_ROOT |
| Config.igris_dir | #1301-PR2 | done | `07a6885` | canonical `.igris` path property |
| igris_dir alignment | #1301-PR3 | done | `659adda` / `f1402ee` | replace CONFIG.project_root / ".igris" with CONFIG.igris_dir; InterlocutorAudit accepts project_root |
| Root consistency guard | #1301-PR4A | done | `f65210e` / `7878a7c` | root guard tests + auth-root-model.md |
| Decomp policy REDACTED | #1337 Cat-B | done | `5094626` | detect `<REDACTED>` marker in secret check |
| Write-auth test bypass | #1337-A | done | `cad25e4` | bypass write-auth gate in integration tests — 401 → 200 |
| Supervisor subprocess import | — | done | `b1b3f64` | missing subprocess import fix |
| Supervisor split complete | #1371 / PRs #1390-#1396 | done | `1d51957` | 3125→1844 lines (below 2,000); #1371 closed, #1356 closed, #1395 created |
| Pyright Phase 4 + CI blocking | #1355 / PRs #1383-#1384 | done | `bc435e5` | 102→0 errors; CI made blocking; #1355 closed |
| Except Exception Phase 6 | #1353 / PR #1397 | **PARTIAL** | `a547a8e` | narrowed 41 in 5 core files (394→353) |
| Except Exception Phase 7 | #1353 / PR #1398 | **PARTIAL** | `8f2ff1e` | narrowed 67 in 8 memory/task/diagnostics files (353→286) |
| Except Exception Phase 8 | #1353 / PR #1399 | **PARTIAL** | `4f80984` | narrowed 107 in 27 core/api/web/agent files (286→179); fixed 4 regressions; VM validated 15/15 |
| Except Exception Phase 9 | #1353 / PR #1413 | **PARTIAL** (Phase 9) | `e1a1797` | narrowed 103 broad catches (179→76); 75 annotated # noqa: BLE001; 0 narrowable remaining; 0 except Exception: pass; VM 15/15; post-merge VM e1a1797 15/15 |
| #1417 logging narrowed catches | #1417 / PR #1419 | done | `b23a0a0` | 141 narrowed catches now log; 13 silent pass kept (ImportError etc.) |
| #1314 parent closure | #1314 / PR #1420 | done | (docs) | all 5 criteria MET; #1314 closed |
| #1316 pyright CI | #1316 / PR #1421 | done | (docs) | pyright CI already configured; #1316 closed |
| #1289 API aliases | #1289 / PR #1422 | done | (squash) | backward-compatible API path aliases added |
| #1297 verifier payload | #1297 / PR #1423 | done | (squash) | verifier/reflection error messages + payload schemas |
| #1317 router rename | #1317 / PR #1424 | done | (squash) | anonymous web routers renamed by domain |
| #1395 loop split | #1395 / PR #1425 | done | `403e2e0` | agent_reasoning_loop.py 2477→1968 lines; 2 modules extracted |
| #1318 app.js modularization | #1318 / PR #1426 | done | `68c5818` | app.js 2401→170 lines; 13 ES modules; tests/_js_helpers.py |
| #1319 SQLite migrations | #1319 / PR #1427 | done | `1357ea5` | SchemaManager + per-component migration registries; 12 tests |
| #1321 graceful shutdown | #1321 / PR #1428 | done | `6aa78e3` | LoopCheckpointManager + GracefulShutdownHandler + StepWatchdog; 17 tests |
| #1430 VM pyright fix | #1430 | done | (VM env) | installed libatomic1 on VM; VM pyright now runs (0 errors, 910 warnings) |
| #1330 backup .igris | #1330 / PR #1431 | done | `6f98d4b` | BackupManager with backup/restore/retention; 13 tests |
| #1320 integration tests | #1320 / PR #1432 | done | `35ef021` | tests/integration/ with 4 files, 13 gated tests |
| #1322 subprocess audit | #1322 / PR #1433 | **PARTIAL** (Phase 1) | `75a9127` | 79 calls classified (55 INFRA, 18 MIGRATE); 10 tests |
| #1329 rate limiting per-user | #1329 / PR #1434 | done | `b69a68b` | UserRateLimiter + role-based limits + /api/rate-limit/status; 18 tests |
| #1324 trace context | #1324 / PR #1435 | **PARTIAL** (Phase 1) | `b69a68b` | TraceContext + TraceSpan + trace_span; 20 tests |
| #1328 Playwright E2E | #1328 / PR #1436 | **PARTIAL** (Phase 1) | `b69a68b` | tests/e2e/ with 4 files, 15 gated tests |
| #1323 WebSocket | #1323 / PR #1437 | **PARTIAL** (Phase 1) | `b69a68b` | /ws/chat + /ws/loop with auth; 9 tests |
| #1325 plugin system | #1325 / PR #1438 | **PARTIAL** (Phase 1) | `5b66d0c` | ToolPlugin + PluginRegistry + discovery; 20 tests |
| #1307 EPIC reliability | #1307 / PR #1439 | **PARTIAL** (evaluation) | `b69a68b` | 2/7 scope done, 4/7 partial, 1/7 not started |

## Security baseline

- write endpoints require auth (#1293)
- git commit endpoints require write auth (#1311)
- dangerous intents are never `chat_only` / `low` risk (#1295)
- redaction is centralized, not duplicated (#1313)
- memory cross-session works — preferences persist across logout/login (#1294)
- auth-first onboarding gate (#1278)
- browser auth gate — unauthenticated users cannot reach LLM (#1285)

## Current gauntlet

Expected gauntlet count: **15/15 jarvis-core-ready** (after gauntlet mkdir fix).

- On **Linux (VM — KVM/QEMU)**: 15/15 PASSED via `.venv/bin/python -m igris.core.jarvis_core_gauntlet`
- On **Windows (host)**: 14/15 — `memory_cross_session` fails with `[WinError 32]` SQLite graph.db file lock (pre-existing, Windows-only, NOT a regression)

Run: `python -m igris.core.jarvis_core_gauntlet`

VM is now KVM/QEMU (Ubuntu 24.04 cloud image, 4GB RAM, 4 vCPU) at 192.168.122.65 (KVM NAT network).
Previous Hyper-V VM at 192.168.1.253 is no longer in use (VHDX could not boot on KVM — EFI bootloader missing).

## Known caveats

- **#1353 CLOSED** — `except Exception` count reduced 627→76→49→47 (Phases 3-9 + final cleanup + #1314 eval). 47 remain, all annotated # noqa: BLE001. 0 without noqa, 0 except Exception: pass. Target <50 achieved. #1353 closed 2026-08-26.
- **#1314 CLOSED** — All 5 criteria MET. except Exception: 47 (<50). 0 except Exception:pass. Criterion 2: 141 catches now log, 13 silent pass (ImportError etc, explicitly allowed). Tests: 7072 passed. CI: green. #1314 closed 2026-08-26.
- **#1417 CLOSED** — 141 narrowed catches now log with debug level. 13 silent patterns kept (ImportError, FileNotFoundError, etc.). PR #1419 merged b23a0a0.
- **#1354 is closed** — structured logging criteria met by architecture (Blocks 31-34). All `igris.*` child loggers inherit structured JSON formatting from root logger.
- **#1395 CLOSED** — `agent_reasoning_loop.py` split from 2,477 to 1,968 lines via PR #1425. Extracted `agent_loop_edit_mixin.py` and `agent_loop_insertion_helpers.py`.
- **#1318 CLOSED** — `app.js` modularized from 2,401 to 170 lines via PR #1426. 13 ES modules extracted, all under 500 lines. Tests updated via `tests/_js_helpers.py`.
- **#1319 CLOSED** — SQLite schema versioning added via PR #1427. `SchemaManager` in `igris/core/schema_manager.py` with per-component migration registries.
- **#1321 CLOSED** — Graceful shutdown and crash recovery added via PR #1428. `LoopCheckpointManager`, `GracefulShutdownHandler`, `StepWatchdog` in `igris/core/loop_checkpoint_manager.py`.
- **Post-roadmap audit (2026-08-26)**: 7113 tests passed, 0 failed. pyright 0 errors. Gauntlet 15/15. VM healthy. All 14 JS modules load (200). SQLite migration smoke OK. Checkpoint smoke OK. Import graph OK.
- **Second roadmap audit (2026-08-27)**: 7203 tests passed, 0 failed. pyright 0 errors/908 warnings. VM pyright 0 errors/910 warnings (libatomic1 installed). Gauntlet 15/15. VM healthy. Backup/restore smoke OK. Rate limit smoke OK. WebSocket smoke OK. Plugin safety smoke OK. 4 issues closed, 6 phase-complete (open). 128 new tests added.
- **#1290 is closed** — diagnostics starvation false positive fixed (Block 37, PR #1408). 3 stale tasks processed (Block 38). VM diagnostics now healthy=true.
- **#1312, #1371, #1356, #1355, #1315, #1296, #1291 are closed** — supervisor split complete (1,844 lines), pyright 0 errors with CI blocking, structured logging foundation complete, task engine worker, chat intent auth.
- **`memory_cross_session` gauntlet check fails on Windows** with `[WinError 32]` SQLite graph.db file lock — pre-existing, NOT a regression. Passes on Linux VM. Tests now skip on Windows with pytest.skip().
- CI type-check PASSES on main (0 pyright errors). CI tests now PASS (24 pre-existing failures fixed in CI test health baseline PR). Fixes: RuntimeError added to 15 degraded boundaries, source-text tests updated for supervisor extraction, gauntlet count 14→15, devops mock side_effect extended, diagnostics timezone fix (calendar.timegm), caplog propagation helper for structured logging tests.
- `gh` CLI may not be installed/authenticated on all agent machines — verify before PR operations.
- VM Python environment: `/home/igris/IGRIS_GPT/.venv/bin/python` (Python 3.12.3, fastapi 0.136.1). NOT system `python3`.
- VM SSH: `sshpass -p igris ssh igris@192.168.122.65` (password auth, KVM NAT network). Key-based auth not configured.
- VM service uses `PROJECT_ROOT=/home/igris/IGRIS_TEST` (from environment), NOT `IGRIS_PROJECT_ROOT=/home/igris/IGRIS_GPT` (from .env). Task storage is at `/home/igris/IGRIS_TEST/.igris/tasks/`.
- The `.local/` directory is used for local-only agent reports (e.g. `DEVIN_IGRIS_HANDOFF_CONTEXT.md`) and should NOT be committed. Added to `.gitignore` on 2026-08-26 (was causing 3 local test_git_status_clean failures).
- **Ubuntu migration (2026-08-20)**: Development environment migrated from Windows to Ubuntu to bypass HP 250 G7 firmware CPU throttle (Event ID 37, CPU locked at 991 MHz on Windows via intelppm). Ubuntu uses intel_pstate driver, not intelppm, so firmware throttle is not enforced. CPU now runs at full speed (up to 3.6 GHz turbo). VM migrated from Hyper-V to KVM/QEMU (Ubuntu 24.04 cloud image). See ADR-IGRIS-0014.

## Local clones audited (2026-08-14)

| Path | Remote | Status |
|---|---|---|
| `C:\Dev\IGRIS_GPT` | `Solarfox88/IGRIS_GPT` | **primary** — clean, aligned with `origin/main` at `7878a7c` |
| `C:\Users\Admin\Downloads\IGRIS_GPT_READY\IGRIS_GPT_READY` | `Solarfox88/IGRIS_GPT` | stale — at MVP baseline `110afad` (PR #1, tag v0.1.0), only mode-bit diffs on shell scripts, no useful work |
| `C:\Users\Admin\IGRIS_CODEX` | `Solarfox88/IGRIS_CODEX` | different project (IGRIS_CODEX), not relevant |
| `C:\Users\Admin\IGRIS_FINAL\IGRIS_CODEX` | `Solarfox88/IGRIS_CODEX` | different project, not relevant |
| `C:\Users\Admin\Desktop\IGRIS_OH_RECOVERY_20260502_090237` | no git | not a repo |
| `C:\Users\Admin\Desktop\TestIGRIS` | no git | not a repo |
| `C:\Users\Admin\Documents\Claude\Projects\IGRIS_GPT` | no git | Claude project metadata, not a repo |
| `C:\Users\Admin\Downloads\IGRIS_GPT_FINAL` | no git | not a repo |

No unpushed Codex/Claude work found on host. No stashes. No useful work to port.

## Hyper-V VM audit (2026-08-14)

| VM | State | Repo found | Branch | Relation to GitHub main | Action |
|---|---|---|---|---|---|
| `IGRIS-GPT` (Hyper-V Gen2, 4CPU, 4GB RAM, disk `C:\HyperV\IGRIS-GPT\disks\IGRIS-GPT-os.vhdx` 60GB) | **Off** (not started — inspected via read-only VHDX mount in WSL) | `/home/igris/IGRIS_GPT` (Ubuntu 24.04, LVM `ubuntu-vg/ubuntu-lv` 58GB) | `fix/1301-pr5a-auth-contract-guard` @ `b7c7e74` (2026-07-13) | `main` @ `7878a7c` = aligned with `origin/main`. HEAD branch = PR #1345 (already pushed to origin). 119 git worktrees (mostly `prunable`). 3 old stashes on `main`/`rank-*` branches. | none — no unpushed work, no newer state than GitHub |

### VM findings detail

- **Most advanced state**: VM `IGRIS-GPT` repo `/home/igris/IGRIS_GPT`, branch `fix/1301-pr5a-auth-contract-guard` @ `b7c7e74` (2026-07-13). This is exactly PR #1345 (open on GitHub). **No newer state than GitHub.**
- **Unpushed work**: none. All local branches with commits ahead of origin are older lineages of already-merged work (e.g. `fix/1293-write-endpoint-auth-gate` has `ac7498b` which is the pre-squash version of main's `359df90` — same work, different commit hash).
- **Stashes**: 3 old stashes on `main`/`rank-*` branches (WIP from June 2026, superseded).
- **Worktrees**: 119, almost all `prunable` (Codex/Claude session worktrees from issues #947–#1251 era).
- **Gauntlet report** (`reports/jarvis_core/jarvis_core_gauntlet_report.md`, modified in working tree): **14/14 PASSED** (2026-06-11T12:39:30Z, post-#1294). Matches expected state.
- **Other VM**: `C:\HyperV\IGRIS-UBUNTU\IGRIS-UBUNTU.vhdx` (30GB) exists on disk but is **not registered** as a Hyper-V VM (orphaned VHDX). Not inspected.
- **VM was NOT started** — inspected via read-only VHDX mount in WSL (`wsl --mount --vhd ... --bare` + LVM activation + `mount -o ro`). No runtime state mutated. VHDX unmounted safely after audit.

## Preview VM runtime (2026-08-14)

VM `IGRIS-GPT` is now **running** as the mandatory runtime validation/preview environment.

| Field | Value |
|---|---|
| Switch | IGRIS External Switch (bound to WiFi via network bridge) |
| VM IP | 192.168.1.253 (static, netplan) |
| URL | http://192.168.1.253:7778 |
| Branch | main @ 553b6f0 (post-PR #1346) |
| Service | igris.service (systemd, enabled, uvicorn 0.0.0.0:7778) |
| SSH | igris@192.168.1.253 (password: igris) |
| Health | DEGRADED — 3 pending tasks, starvation=1, task_engine=null in /api/os/brief (this is #1296, expected on main) |

Network config: /etc/netplan/01-static.yaml with static IP 192.168.1.253/24, gateway 192.168.1.1, DNS 192.168.1.1+8.8.8.8.
The IGRIS External Switch is bound to WiFi (Realtek RTL8822CE) via a Microsoft network bridge — VM is directly reachable on the LAN.

**Conclusion**: Hyper-V VM audit performed; no newer IGRIS work found. GitHub `main` is the most advanced state. The VM's only non-main branch is PR #1345 which is already on GitHub.

## Stabilization audit after third roadmap

Main commit: `b362778`
Roadmap PRs verified: #1441, #1442, #1443, #1444, #1445, #1449 (all MERGED)
Issues verified: #1322, #1324, #1325, #1323, #1328, #1307 (all OPEN, phase-complete)
Child issues verified: #1446, #1447, #1448 (all OPEN)
CI: all green (8 recent runs success)
Local tests: 7217 passed, 40 skipped, 0 failed. pyright 0 errors, 915 warnings.
VM: `b362778`, gauntlet 15/15, healthy=true, os/brief ok=true
VM pyright: 0 errors, 910 warnings
Subprocess governance: 4 migrated modules clean (no subprocess import, use governed_run). 25 unauthorized modules still import subprocess (INFRASTRUCTURE class). #1322 acceptance criteria NOT fully met.
Trace middleware: X-Trace-Id and X-Request-Id on every response. Incoming propagation verified.
Plugin API: GET /api/plugins read-only, no execution, no secret leakage.
WebSocket streaming: word-by-word fallback simulation (streaming_mode=word_split). Auth enforced.
Playwright E2E: 25 tests, all skip by default (IGRIS_E2E_TESTS=1 gate).
#1307 child issues: #1446 (worktree recovery), #1447 (provider degraded states), #1448 (partial restore) — all OPEN.
Open concerns: 25 unauthorized subprocess imports remain. Memory files were not updated during third roadmap (fixed in this audit).
Recommended next roadmap: #1322 Phase 3 (lint rule + INFRASTRUCTURE migration), #1324 Phase 3 (OTel SDK), #1325 Phase 3 (UI), #1323 Phase 3 (real token streaming), #1328 (broader coverage), #1446/#1447/#1448 (reliability children).

## #1322 Phase 3 subprocess governance lint

Main commit: `ec8a358`
Before: no automated check to prevent subprocess import regression
After: AST-based governance check with explicit allowlist + 13 pytest tests
Lint rule: scripts/check_subprocess_governance.py (306 lines)
CI: pytest enforcement (test_subprocess_governance_1322.py). CI workflow job pending (OAuth scope).
Remaining subprocess policy: 3 always-allowed + 25 infrastructure-allowed (with rationale) + 4 forbidden (migrated)
Remaining INFRASTRUCTURE calls: 25 modules still import subprocess (pending Phase 4)
Issue state: #1322 OPEN (Phase 3 complete, Phase 4 needed)
Follow-up: Phase 4 — evaluate/migrate 25 INFRASTRUCTURE subprocess imports
