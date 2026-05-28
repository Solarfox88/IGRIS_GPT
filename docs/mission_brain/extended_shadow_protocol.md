# Mission Brain Extended Shadow Monitoring Protocol (Epic #857)

## Purpose
Extend the shadow monitoring sample from 10 cycles (Epic #845) to at least 30 cycles
(ideally 50) to determine whether agreement_rate=0.0 is a stable structural property
or a small-sample artifact.

## Baseline (from #845)
- total_shadow_cycles: 10
- agreement_rate: 0.0
- disagreement_rate: 1.0
- prevented_error_candidates: 10
- risk_introduced_candidates: 0
- potential_critical_false_completed: 0
- latency_overhead.mean_ms: 0.6
- cost_overhead.total_usd: 0.0
- rollback_path_status: ok
- final_readiness_trend: stable

## Hard Constraints (NEVER violate)
- Shadow mode only — no change to default loop behavior
- Feature flag `enabled` remains `False` by default
- No enable-by-default
- No mandatory gate in main loop
- No irreversible integration
- Wrapper rollback/fallback path must remain active at all times
- Mission Brain must not become a required step
- No controlled rollout in this epic

## Batch Plan

### Batch 1 — cycles 11–20 (subissue #859)
10 shadow cycles with goals spanning:
- policy/safety evaluation
- multi-file risk assessment
- regression detection
- loop coherence review
- completion boundary analysis
- goal decomposition review
- test coverage check
- git/branch safety review
- dependency satisfaction check
- memory/context saturation check

### Batch 2 — cycles 21–30 (subissue #860)
10 shadow cycles with complementary goals:
- different complexity levels from Batch 1
- mix of simple vs multi-step goals
- include edge cases: ambiguous goals, empty context, conflicting signals
- at least 3 goals that previously triggered disagreement in #845

### Optional Batch 3 — cycles 31–50 (if Batch 2 results are inconclusive)
20 additional cycles only if sample_representativeness_score < 0.7 after 30 cycles.

## Shadow Cycle Record Schema
Each cycle must record the fields defined in:
- `reports/mission_brain/shadow_monitoring/cycle_report_template.json`

Plus the following extended fields:
- `goal_class`: category of goal (policy_check | risk_assessment | planning | verification | other)
- `goal_complexity`: simple | moderate | complex

## Aggregate Metrics Schema
Each batch must produce metrics conforming to:
- `reports/mission_brain/shadow_monitoring/extended_aggregate_metrics_schema.json`

New fields added in this epic vs #845:
- `disagreement_by_class`: distribution of mismatch_class values
- `decision_distribution_mission_brain`: distribution of MB decisions
- `decision_distribution_current_loop`: distribution of current loop decisions
- `dominant_mismatch_classes`: top 3 mismatch classes by frequency
- `sample_representativeness_notes`: free-text notes on sample diversity
- `sample_representativeness_score`: 0.0–1.0

## Stop Conditions (pause and request explicit confirmation)
- `potential_critical_false_completed > 0`
- `risk_introduced_candidates > 0` with severity HIGH
- Mission Brain modifies default loop behavior
- Mandatory gate required
- Enable-by-default required
- Severe regressions observed
- Excessive operational overhead (latency mean > 500ms or cost > $0.10/cycle)
- Scope change required
- Tests not runnable
- Out-of-scope files or diffs appear

## Allowed Final Decisions (only these five)
- `keep shadow mode` — divergence structural but safe; more data needed or no action warranted
- `extend monitoring again` — sample not representative or results inconclusive after 30 cycles
- `start disagreement calibration` — divergence pattern understood; safe to calibrate taxonomy/mapping
- `remediate again` — specific regressions found requiring fixes
- `do not integrate` — risk evidence warrants stopping

## NOT Allowed Decisions (even if metrics would suggest them)
- enable by default
- controlled rollout activation
- mandatory gate integration
- remove current loop behavior

## Rollback Path Verification
Before each batch, verify:
1. `CONFIG.mission_brain_integration.enabled == False` (default)
2. `CONFIG.mission_brain_integration.mode == "shadow"` (default)
3. `CONFIG.mission_brain_integration.rollback_to_wrapper_on_guardrail == True`
4. `CONFIG.mission_brain_integration.allow_enforce_mode == False`

## Infrastructure
- Shadow monitoring module: `igris/agent/mission/shadow_monitoring.py`
- Decision module: `igris/agent/mission/shadow_monitoring_decision.py`
- Batch scripts: `scripts/run_mission_brain_extended_shadow_batch*.py`
- Reports: `reports/mission_brain/shadow_monitoring/{858,859,860,861,862}/`
- Protocol: this file (`docs/mission_brain/extended_shadow_protocol.md`)
