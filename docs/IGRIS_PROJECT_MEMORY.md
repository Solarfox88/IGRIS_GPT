# IGRIS Project Memory

Stable project state — source of truth for all agents.

Last updated: 2026-08-14 (Devin desktop handoff bootstrap)

## Repository

- repo: `Solarfox88/IGRIS_GPT` (public)
- default branch: `main`
- current `main` commit: `7878a7c` (Merge PR #1344 — root consistency guard, EPIC #1301 PR4A)

## Completed

| Area | Issue/PR | Status | Merge commit | Notes |
|---|---|---|---|---|
| Security — write auth | #1293 | done | `359df90` | P0 auth gate on all write/side-effect endpoints |
| Security — git commit gate | #1311 / PR #1311 | done | `f603e04` | gated `POST /api/tools/git/commit` and `POST /api/git/commit` with write auth |
| Safety — dangerous intent routing | #1295 / PR #1332 | done | `d453add` | never `chat_only` for `rm -rf`, issue create, sudo |
| Security — centralized redaction | #1313 / PR #1334 | done | `7d8d4c0` | secret redaction centralized (19 files touched) |
| Reliability — memory cross-session | #1294 / PR #1335 | done | `e716f68` | memory/preferences persist across sessions (23 files touched) |
| Refactor — supervisor C1 | #1312 / PR #1331 | **PARTIAL** | `ea3d70b` | extracted 4 sub-modules but `self_repair_supervisor.py` still 6208 lines (target <2000) |
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

Expected gauntlet count after #1294: **14/14 jarvis-core-ready**.

If `task_engine_reliability` is added as a mandatory check (planned for #1296), update expected count to **15/15**.

Run: `python -m igris.core.jarvis_core_gauntlet`

## Known caveats

- **#1312 is only partially complete** — `self_repair_supervisor.py` is still 6208 lines (target <2000). PR #1331 extracted 4 sub-modules but the main file was not reduced enough. Issue is closed on GitHub but the criterion is NOT met. A follow-up issue or reopen is needed.
- CI may have pre-existing auth/server failures; prove on clean `origin/main` before claiming regression.
- `gh` CLI may not be installed/authenticated on all agent machines — verify before PR operations.
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

**Conclusion**: Hyper-V VM audit performed; no newer IGRIS work found. GitHub `main` is the most advanced state. The VM's only non-main branch is PR #1345 which is already on GitHub.
