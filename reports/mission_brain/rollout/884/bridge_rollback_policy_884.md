# Bridge Rollback & Fallback Policy — #884
## EPIC #880

## Rollback Steps

**Step 1:** Set BRIDGE_DIAGNOSTIC_ENABLED=false (or unset the env var)
- Effect: BridgeConfig.enabled=False, should_emit=False
- Loop impact: none

**Step 2:** Restart the IGRIS service
- Effect: bridge_reporter.enrich_report() returns original reports unchanged
- Loop impact: none

**Step 3:** Optionally strip existing bridge_diagnostics from stored reports
- Effect: strip_bridge_diagnostics() removes the key; dict otherwise identical
- Loop impact: none

## Rollback Properties

- Reversible: ✅
- Data loss: ✅ None
- Immediate: ✅
- Loop decision impact: none

## Fallback Policies

| scenario | policy | loop_impact |
|----------|--------|-------------|
| Bridge computation raises an exception | Return original report unchanged (non-blocking) | none |
| Bridge exceeds latency budget (max_latency_budget_ms) | Return original report unchanged (skip enrichment silently) | none |
| BRIDGE_DIAGNOSTIC_ENABLED env var not set | DEFAULT_BRIDGE_CONFIG (disabled) — no enrichment ever | none |
| Invalid run_status or goal_status input | Normalized to 'unknown' → insufficient_context (safe fallbac | none |

## Evaluation: passed
