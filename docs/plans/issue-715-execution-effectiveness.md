# Issue #715 - Execution Effectiveness Hardening Plan

Status: queued

## Goals
1. Write-first mode for focused technical sub-missions.
2. Adaptive retry ladder (non-redundant strategies).
3. Telemetry-driven autonomy controls.

## Work Breakdown

### A. Write-first guard
- Add `time_to_first_diff` guard in supervisor loop.
- For focused goals (single module/contract), require explicit `file_targets`.
- If no write action within threshold steps, trigger strategy switch (not decomposition first).
- Add anti-recursion check for already-focused sub-mission goals.

### B. Adaptive retry ladder
- Retry #1: micro-patch mode (`single_file_single_test` objective).
- Retry #2: strong profile + different `task_type` than retry #1.
- If both fail with no diff, block with structured technical report (`no_diff_terminal_report`).

### C. Telemetry
- Persist run-level metrics:
  - `time_to_first_diff_s`
  - `no_diff_rate`
  - `decompose_rate`
  - `attempt_outcome`
- Expose in `run.report` for policy decisions.

## Target Files
- `igris/core/self_repair_supervisor.py`
- `igris/core/agent_reasoning_loop.py` (if step-level write telemetry needed)
- `tests/test_self_repair_supervisor.py`

## Acceptance Test Matrix
- focused goal produces first diff before threshold or changes strategy automatically
- retries use distinct strategy/profile/task_type combinations
- no recursive decomposition for already-focused sub-mission goals
- telemetry fields present and consistent in final report

