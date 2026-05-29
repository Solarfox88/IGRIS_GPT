# MBOP Examples

**Issue**: #936  
**Version**: 1.0  
**Purpose**: Practical examples of the Mission Brain Operating Protocol applied to real tasks.

---

## Example 1: Compact Mode — Simple Feature Fix

**Issue**: #617 — Cache baseline tests for sub-missions on same branch  
**Mode**: Compact (single concern, < 2h, clear scope)

```markdown
## MBOP Compact

### Intent
Cache baseline test results per branch+commit to avoid repeating 355s test run for
sub-missions on the same branch with no code changes.

### Requirements
- Cache keyed on (branch, head_sha); stored in .igris/baseline_cache.json
- Skip baseline if cache valid (same SHA, age < 30min, previous run passed)
- Invalidate on new commit or test failure
- No change to baseline run behavior when cache is cold

### Checklist
- [x] _load_valid_baseline_cache() implemented with SHA + TTL check
- [x] _save_baseline_cache() saves on success
- [x] Cache miss path runs baseline as before
- [x] Cache hit path emits "skipped" event in run
- [x] Unit tests for hit/miss/stale/sha-mismatch paths

### Tests
pytest tests/test_self_repair_supervisor.py -k "baseline_cache" → 4 PASS

### Quality gate
PASS — all tests green, no regressions

### Satisfaction gate
PASS — sub-missions reuse cache on same branch; 6 min per run recovered

### Advisory not modified
YES — no Advisory changes
```

**What makes this compact mode valid:**
- Narrow scope (one function pair)
- Clear acceptance criteria
- Tests exist
- Satisfaction verifiable by measurement

---

## Example 2: Full Mode — Complex New Module

**Issue**: #614 — DependencyChecker — dependency model and launch-gate rules  
**Mode**: Full (new module, multi-file, architectural decision)

```markdown
## MBOP Full

### Phase 1 — Intake
- **What**: Build DependencyChecker that reads depends-on-NNN labels from GitHub issues
  and blocks supervisor runs on issues with unsatisfied dependencies.
- **Where**: New igris/core/dependency_checker.py; hook into _run_preflight_phase()
- **Why**: Issue cascades currently start work on issues whose dependencies aren't merged.
  Wastes 18+ min per cycle on blocked work.
- **Constraints**:
  - dep check must be best-effort (never crash the supervisor)
  - VastAI excluded from chains
  - no advisory changes
  - no loop decision changes
- **Output**: DependencyChecker class, preflight integration, 20+ tests
- **Unknowns**: Does gh CLI handle rate limits gracefully? → resolved: yes, with timeout

### Phase 2 — Intent Decomposition
1. PARSE: Extract issue numbers from depends-on-NNN labels or .igris/dependencies.json
2. CHECK: For each dependency, verify GitHub state (open/closed/merged)
3. GUARD: Circular dependency detection via visited set
4. GATE: If any dependency unsatisfied, return blocked result in preflight
5. SKIP: In roadmap selection, skip issues with open deps

### Phase 3 — Requirements
- REQ-1: DependencyChecker.check(N) MUST return (False, [list]) WHEN issue N has
  open dependencies SO THAT supervisor does not start work on blocked issues
- REQ-2: Circular deps MUST not cause infinite loops WHEN dep graph has cycles
- REQ-3: dep check MUST be best-effort WHEN gh CLI unavailable, logging error without
  blocking the supervisor
- REQ-4: RankSupervisorConfig MUST expose issue_number field for dep lookup

### Phase 4 — Plan
Files:
- CREATE igris/core/dependency_checker.py — DependencyChecker class
- MODIFY igris/core/self_repair_supervisor.py — wire into _run_preflight_phase()
- MODIFY igris/core/self_repair_supervisor.py — _maybe_autoselect_next_roadmap()
Risk: gh CLI subprocess may hang → mitigation: timeout=10s per call
Rollback: dep check is inside try/except, never blocks on error

### Phase 5 — Checklist
- [ ] DependencyChecker class created with check(), parse_depends_on_labels()
- [ ] Circular dep guard via visited set (not {issue_number})
- [ ] preflight blocks on dep_not_satisfied
- [ ] roadmap selector skips issues with open deps
- [ ] 20+ tests with mocked gh CLI
- [ ] best-effort: exception in dep check → logs, continues

### Phase 6 — Actions (ordered)
1. CREATE igris/core/dependency_checker.py
2. MODIFY self_repair_supervisor.py — RankSupervisorConfig.issue_number
3. MODIFY self_repair_supervisor.py — _run_preflight_phase() dep check block
4. MODIFY self_repair_supervisor.py — _maybe_autoselect_next_roadmap() skip
5. CREATE tests/test_dependency_checker.py
6. CREATE tests/test_dependency_validator_preflight.py
7. RUN pytest tests/test_dependency_checker.py tests/test_dependency_validator_preflight.py

[execution trace omitted for brevity]

### Phase 8 — Verification
| REQ | Test/Check | Result |
|-----|-----------|--------|
| REQ-1 | test_preflight_blocks_when_dep_open | PASS |
| REQ-2 | test_circular_dep_does_not_loop | PASS |
| REQ-3 | test_dep_check_exception_does_not_block | PASS |
| REQ-4 | test_config_issue_number_parsed | PASS |

### Phase 9 — Quality Gate
PASS — 22/22 tests, 0 regressions, no TODO stubs

### Phase 10 — Satisfaction Gate
PASS — supervisor blocks on open deps, circular deps handled, best-effort preserved,
no Advisory change, no loop change

### Phase 11 — Post-Task Evaluation
- Circular dep bug found during testing (visited set was wrong) — fixed before PR
- gh CLI timeout not tested in unit tests (mocked only) → future integration test
- Lessons: always test circular dep separately from transitive dep

### Phase 12 — Next-Step Propagation
- Opened #616: Dependency observability + /api/memory/summary integration
- Opened #615: Pre-run dependency validator in supervisor
- Both issues have intake sections and link back to #614
```

---

## Example 3: Issue Chain with Next-Subissue Propagation

**Parent**: #526 — Interlocutor-Aware Interaction  
**Children propagated correctly**:

```
#526 (parent — closed)
  → #526-auth: AuthorizationGate tests with delegation keys
  → #526-judgment: JudgmentLayer night-time and CI advisory
  → #526-proactive: ProactiveEngine scope filtering
```

Each child issue includes:
```markdown
## MBOP Intake (sub-issue of #526)
- **Parent**: #526
- **What**: [specific sub-feature]
- **Why**: broke out from #526 due to complexity
- **Constraint**: must be mergeable independently
- **Acceptance criteria**: [specific list]
```

**Anti-pattern (wrong propagation)**:
```
PR comment: "We should also add scope filtering to ProactiveEngine"
→ No issue opened
→ Gets forgotten
→ 3 weeks later someone asks why scope filtering is missing
```

---

## Example 4: Post-Task Evaluation

After completing #532 (ReflectionHook):

```markdown
## Post-Task Evaluation — #532 ReflectionHook

### What worked well
- Complexity trigger (tool_count + response_len) is simple and effective
- Mock-based tests covered all failure modes without needing real LLM
- Per-session counter rollback on empty output was the right design

### What caused delays
- First test run failed because hook was initialized inside try/except block,
  so the import error was swallowed — took 10 min to debug
- Fix: add logging.getLogger().debug() in the except block even for best-effort code

### Were requirements accurate?
- Yes, but "silent on LLM failure" needed clarification: it means return None,
  not raise, not log at WARNING level

### Follow-up issues
- #532-eval: Add eval harness to measure reflection quality offline
  (not opened yet — low priority)

### Lessons for future
- Always test the "hook raises, step continues" path explicitly
- "Best-effort" code should still log at DEBUG level for traceability
```

---

## Example 5: Quality Gate

**Scenario**: New `StateCalibration` module (#526 sub-task)

```markdown
## Quality Gate Evaluation

| Item | Status | Evidence |
|------|--------|----------|
| All checklist items done | ✅ | See Phase 5 checklist above |
| All tests pass | ✅ | pytest tests/test_state_calibration.py → 12/12 |
| No regressions | ✅ | Full suite: 133 pass, 1 skip (psutil) |
| No silent TODO | ✅ | grep "TODO\|FIXME\|HACK" igris/core/state_calibration.py → 0 |
| No placeholder | ✅ | All methods implemented |
| Conventions followed | ✅ | Docstrings, type hints, dataclasses |

**Quality gate: PASS**
```

---

## Example 6: Satisfaction Gate

**Scenario**: Same `StateCalibration` module

```markdown
## Satisfaction Gate Evaluation

Acceptance criteria from #526 (Layer 6 — State Calibration):
- [x] Detects urgency from keywords + multi-punct + caps
- [x] Detects frustration from "ancora", "di nuovo", "non funziona" patterns
- [x] Detects confusion from question marks + confusion words
- [x] Maps state to ResponseMode (verbosity, tone, lead_with_action)
- [x] Routine state returns correct verbosity per expertise_level
- [x] Silent on any exception (detect() never raises)

Strategic intent: IGRIS must calibrate responses to the interlocutor's emotional state.
→ All 6 criteria verified. State→Mode mapping tested with real examples. ✅

No scope creep: no changes to authorization or identity layer.
No Advisory changes.

**Satisfaction gate: PASS**
Technical success AND strategic success confirmed.
```

---

## Example 7: PR Not Acceptable — Cosmetic/Wrapper

**Scenario**: Developer creates a file `igris/core/improved_memory.py` that does:

```python
# improved_memory.py
from igris.core.memory_graph import MemoryGraph  # just re-exports
ImprovedMemoryGraph = MemoryGraph
```

**Why this fails MBOP:**

```
❌ F-WRAP: Wrapper/Cosmetic Work detected

- No new behavior
- No new test
- No new acceptance criterion covered
- Intent = unclear (why is this "improved"?)
- Quality gate: FAIL (what does this change?)
- Satisfaction gate: FAIL (what issue does this address?)

Reviewer verdict: REJECT — reopen with real requirements
```

---

## Example 8: Real Refactor — Acceptable

**Scenario**: `MemoryGraph.add_node()` is refactored to validate confidence range [0,1]:

```markdown
## MBOP Compact

### Intent
add_node() currently accepts confidence=99.0 without error, silently producing
corrupt memory graph entries. Add input validation.

### Requirements
- confidence MUST be clamped to [0.0, 1.0] with ValueError on out-of-range
- All existing callers MUST pass valid values (audit required)
- Backward compatibility: callers that pass 0.0 and 1.0 unchanged

### Checklist
- [x] ValueError raised for confidence < 0 or > 1
- [x] Audit of 23 callers: all in [0.0, 1.0] range
- [x] Test: confidence=1.5 → ValueError
- [x] Test: confidence=0.85 → accepted

### Tests
pytest tests/test_memory_graph.py → 8/8 PASS

### Quality gate: PASS
### Satisfaction gate: PASS — real bug fixed, no cosmetic drift
### Advisory not modified: YES
```

**Why this is acceptable refactor:**
- Real bug fixed (not cosmetic)
- Clear requirement (no vague "improve")
- Tests prove behavior
- Caller audit done
- Satisfaction gate addresses "was the real intent met?" = yes, data integrity improved

---

## Example 9: Advisory Recovery Proposal Treated as MBOP Input

**Scenario** (future, after #942 is implemented):

Advisory generates:
```json
{
  "proposal_type": "recovery",
  "action": "restart_service",
  "target": "igris_api",
  "reason": "healthcheck failed 3 times",
  "confidence": 0.85
}
```

**Correct MBOP treatment:**

```markdown
## MBOP Intake — Advisory Recovery Proposal

### What
Advisory proposes restarting igris_api service due to 3 consecutive healthcheck failures.

### Where
igris/scripts/restart_igris.sh → igris_api process

### Why
Advisory detected 3 failures; restart may resolve transient crash.

### Constraints
- This is a PROPOSAL, not a command
- Requires human approval before execution
- Advisory system does NOT execute this — IGRIS agent does, after MBOP
- Irreversible action (restart causes 5s downtime)

### Unknowns
- Is the healthcheck failure due to code bug or infra issue?
- Has this pattern occurred before?
→ Check logs before deciding to restart

### Plan
1. Review recent logs for error pattern
2. If transient: restart and monitor
3. If code bug: do NOT restart — open a fix issue instead

[... continues through full MBOP ...]
```

**What makes this correct:**
- Proposal enters at Phase 1 (intake) — not executed automatically
- IGRIS evaluates it through MBOP (plan, risk, rollback)
- Advisory is the signal, MBOP is the process, human confirms
- Advisory system itself is unchanged (advisory-only remains)

**What is WRONG (never do this):**
```python
# WRONG: Advisory executes directly
if advisory.confidence > 0.8 and advisory.action == "restart_service":
    subprocess.run(["./restart_igris.sh"])  # NO! This is auto-execution
```
This violates the advisory-only constraint and bypasses MBOP entirely.
