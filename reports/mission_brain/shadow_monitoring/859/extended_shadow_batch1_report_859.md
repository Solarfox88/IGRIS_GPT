# Extended Shadow Monitoring Batch 1 — #859

- batch_cycles: 10
- cumulative_cycles: 20  (10 from #845 + 10 here)
- agreement_rate: 0.0
- disagreement_rate: 1.0
- disagreement_by_class: {'safe_more_optimistic_mission_brain': 10}
- dominant_mismatch_classes: ['safe_more_optimistic_mission_brain']
- prevented_error_candidates: 10
- risk_introduced_candidates: 0
- potential_false_completed: 0
- potential_critical_false_completed: 0
- potential_false_partial: 0
- potential_false_failed: 0
- report_usefulness_score: 0.8
- latency_overhead.mean_ms: 1.9
- latency_overhead.p95_ms: 5.0
- cost_overhead.total_usd: 0.0
- rollback_path_status: ok
- final_readiness_trend: stable
- sample_representativeness_score: 1.0
- sample_representativeness_notes: Batch 1 covers 10 distinct goal_class categories per protocol #858.
- decision_distribution_mission_brain: {'partial': 10}
- decision_distribution_current_loop: {'failed': 10}

## Evaluation: passed
- No stop conditions triggered
- Next: #860 Run extended shadow batch 2 (cycles 21–30)
