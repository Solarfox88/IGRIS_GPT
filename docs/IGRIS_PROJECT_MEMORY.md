# IGRIS Project Memory

Stable project state — source of truth for all agents.

Last updated: 2026-08-14 (mandatory 5-pass rule added)

## Repository

- repo: `Solarfox88/IGRIS_GPT` (public)
- default branch: `main`
- current `main` commit: `bac942c` (docs: align roadmap and VM validation status + fix gauntlet mkdir)

## Mandatory operating method

IGRIS uses a mandatory 5-pass completion rule for all tasks.

No task, issue, PR, refactor, test change, CI change, runtime fix, VM validation, or security hardening may be declared complete before five review/improvement passes.

The full rule is canonical in `AGENTS.md`.

Summary:

1. understand and implement first version
2. reread issue and review own diff
3. check edge cases and regressions
4. verify safety, VM, integration, and memory
5. final acceptance review

If full acceptance criteria are not satisfied after five passes, the task must be marked:

```text
Phase completed, parent issue not complete.
```

and a follow-up issue must be created or updated.

## Completed

| Area | Issue/PR | Status | Merge commit | Notes |
|---|---|---|---|---|
| Security — write auth | #1293 | done | `359df90` | P0 auth gate on all write/side-effect endpoints |
| Security — git commit gate | #1311 / PR #1311 | done | `f603e04` | gated `POST /api/tools/git/commit` and `POST /api/git/commit` with write auth |
| Safety — dangerous intent routing | #1295 / PR #1332 | done | `d453add` | never `chat_only` for `rm -rf`, issue create, sudo |
| Security — centralized redaction | #1313 / PR #1334 | done | `7d8d4c0` | secret redaction centralized (19 files touched) |
| Reliability — memory cross-session | #1294 / PR #1335 | done | `e716f68` | memory/preferences persist across sessions (23 files touched) |
| Refactor — supervisor C1 | #1312 / PR #1331 | **PARTIAL** | `ea3d70b` | extracted 4 sub-modules but `self_repair_supervisor.py` still 6208 lines (target <2000) |
| Task engine reliability | #1296 / PR #1347 | done | `8fa9d8e` | worker step, safe validate, honest diagnostics, gauntlet check |
| Code change gating | #1291 / PR #1348 | done | `19a1dc4` | /api/chat/intent gates code_change for limited users |
| Auth contract guard | #1301-PR5A / PR #1345 | done | `54b6b60` | 13 guard tests + docs/auth-contract.md |
| Except Exception cleanup | #1314 / PR #1349 | **PARTIAL** (Phase 1) | `0ac7a7b` | logging added to 46 silent catches; Phase 2 pending (follow-up #1353) |
| Structured logging | #1315 / PR #1350 | **PARTIAL** (Phase 1) | `79fe072` | StructuredFormatter + 7 priority modules; Phase 2 pending (follow-up #1354) |
| Pyright type checking | #1316 / PR #1351 | **PARTIAL** (Phase 1) | `9866bf5` | basic mode config + CI job; Phase 2 pending (follow-up #1355) |
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

- On **Linux (VM)**: 15/15 PASSED via `.venv/bin/python -m igris.core.jarvis_core_gauntlet`
- On **Windows (host)**: 14/15 — `memory_cross_session` fails with `[WinError 32]` SQLite graph.db file lock (pre-existing, Windows-only, NOT a regression)

Run: `python -m igris.core.jarvis_core_gauntlet`

## Known caveats

- **#1312 is only partially complete** — `self_repair_supervisor.py` is still 6,013 lines (target <2000). Follow-up issue #1356 tracks Phase 3.
- **#1314, #1315, #1316 are open** — Phase 1 merged but Phase 2 pending. Follow-up issues: #1353, #1354, #1355.
- **`memory_cross_session` gauntlet check fails on Windows** with `[WinError 32]` SQLite graph.db file lock — pre-existing, NOT a regression. Passes on Linux VM.
- CI may have pre-existing auth/server failures; prove on clean `origin/main` before claiming regression.
- `gh` CLI may not be installed/authenticated on all agent machines — verify before PR operations.
- VM Python environment: `/home/igris/IGRIS_GPT/.venv/bin/python` (Python 3.12.3, fastapi 0.136.1). NOT system `python3`.
- The `.local/` directory is used for local-only agent reports (e.g. `DEVIN_IGRIS_HANDOFF_CONTEXT.md`) and should NOT be committed.

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
