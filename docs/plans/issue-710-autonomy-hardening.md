# Issue #710 - Autonomy Hardening Plan

Status: queued (execute after current active run completion)

## Scope
1. Replace fragile boolean parsing in supervisor config with `_as_bool(...)` for all bool flags.
2. Raise autonomous default `max_rank_attempts` (policy/env-driven) so watchdog runs do not stop after a single failed attempt.
3. Harden `_infer_dry_run` to use normalized booleans only.
4. Add anti-recursion guard to prevent repeated decomposition for already-focused sub-mission goals.

## Implementation Notes
- Primary files:
  - `igris/core/self_repair_supervisor.py`
  - `igris/web/server.py` (only if watchdog default wiring needed)
- Config knobs (if added/updated):
  - `IGRIS_MAX_RANK_ATTEMPTS_DEFAULT`
  - `IGRIS_ALLOW_AUTO_SUBISSUES_DEFAULT` (already introduced)

## Test Plan
- Extend `tests/test_self_repair_supervisor.py` with:
  - string-boolean parsing matrix (`"false"`, `"0"`, `"no"`, etc.)
  - default attempts behavior for watchdog-like payload
  - `dry_run` inference correctness with string inputs
  - decomposition anti-recursion for sub-mission lineage goals

## Acceptance Criteria Mapping
- AC1 -> bool parsing tests and config defaults.
- AC2 -> default attempts tests.
- AC3 -> dry_run inference tests.
- AC4 -> anti-recursion decomposition tests.
- AC5 -> regression suite updates.

