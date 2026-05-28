# Mission Brain Shadow Comparison — #837

- total_runs: 3
- agreement_count: 1
- disagreement_count: 2
- agreement_rate: 0.333
- risky_mismatch_count: 1
- safe_mismatch_count: 1
- quality_gate_pass_rate: 0.0
- satisfaction_gate_pass_rate: 1.0

## Mismatch classes
- agreement: 1
- risky_false_completed_candidate: 1
- safe_more_optimistic_mission_brain: 1

## Thresholds
- risky_mismatch_count must remain 0 for rollout candidate
- agreement_rate target >= 0.80 for stronger confidence
- no behavior switch in this phase (analysis-only)
