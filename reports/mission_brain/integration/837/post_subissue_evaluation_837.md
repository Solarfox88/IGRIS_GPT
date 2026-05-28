# Post-subissue Evaluation — #837

Status: `passed`

## What changed
- Added comparison module:
  - `igris/agent/mission/shadow_comparison.py`
- Added reporting script:
  - `scripts/run_mission_brain_shadow_comparison_837.py`
- Added test coverage:
  - `tests/test_mission_shadow_comparison.py`
- Produced comparison artifacts:
  - `reports/mission_brain/integration/837/shadow_comparison_837.json`
  - `reports/mission_brain/integration/837/shadow_comparison_837.md`

## Metrics (current shadow sample)
- total_runs: 3
- agreement_count: 1
- disagreement_count: 2
- agreement_rate: 0.333
- risky_mismatch_count: 1
- safe_mismatch_count: 1

Mismatch classes:
- `risky_false_completed_candidate`: 1
- `safe_more_optimistic_mission_brain`: 1
- `agreement`: 1

## Threshold policy declared
- risky mismatches must be `0` for rollout candidacy
- agreement target for stronger confidence: `>= 0.80`
- analysis-only phase: no behavior switch permitted

## Verification executed
- `.venv/bin/pytest -q tests/test_mission_shadow_comparison.py tests/test_mission_shadow_integration.py tests/test_agent_reasoning_loop.py tests/test_mission_orchestrator.py`
  - `56 passed`

## Next-subissue propagation (#838)
- Confirmed unchanged.
- #838 must enforce explicit rollback/fallback policy when shadow mismatches cross risk thresholds.
- Current loop remains authoritative.
