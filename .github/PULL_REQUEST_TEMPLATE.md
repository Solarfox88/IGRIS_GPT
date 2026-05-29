# Pull Request — MBOP Summary

**Issue**: closes #NNN  
**Mode**: Compact / Full *(delete as appropriate)*

---

## MBOP Compact *(use this section for compact-mode tasks)*

### Intent
<!-- 1–3 sentences: what, why, where. -->

### Requirements
<!-- Verifiable bullets. No vague language. -->
- 

### Checklist
<!-- Binary items derived from requirements. All must be checked before merging. -->
- [ ] 
- [ ] 

### Tests
<!-- What was run, result. -->
```
pytest <test_file> → N PASS
```

### Quality Gate
<!-- PASS or FAIL + evidence -->
PASS / FAIL — 

### Satisfaction Gate
<!-- PASS or FAIL — did we build the RIGHT thing? -->
PASS / FAIL — 

### Advisory not modified
YES

---

## MBOP Full *(use this section for full-mode tasks; delete compact section above)*

### Phase 1 — Intake
- **What**: 
- **Where**: 
- **Why**: 
- **Constraints**: 
- **Output**: 
- **Unknowns resolved**: 

### Phase 2 — Intent Decomposition
1. 
2. 

### Phase 3 — Requirements
- REQ-1: [system] MUST [behavior] WHEN [condition] SO THAT [goal]
- REQ-2: 

### Phase 4 — Plan
<!-- Files created/modified with rationale. Risk assessment. Rollback path. -->

### Phase 5 — Checklist
- [ ] 
- [ ] 

### Phase 6–7 — Actions + Execution
<!-- Ordered list of actions taken. Note any deviations from plan. -->
1. 

### Phase 8 — Verification
| REQ | Test/Check | Result |
|-----|-----------|--------|
| REQ-1 | | |

### Phase 9 — Quality Gate
PASS / FAIL

| Item | Status | Evidence |
|------|--------|----------|
| All checklist items done | ✅/❌ | |
| All tests pass | ✅/❌ | |
| No regressions | ✅/❌ | |
| No silent TODO | ✅/❌ | |
| No placeholder | ✅/❌ | |

### Phase 10 — Satisfaction Gate
PASS / FAIL

<!-- Verify acceptance criteria one by one: -->
- [ ] AC-1: 
- [ ] AC-2: 

### Phase 11 — Post-Task Evaluation
<!-- What worked, what caused delays, lessons for future. -->

### Phase 12 — Next-Step Propagation
<!-- Issues opened: #NNN — title -->
<!-- Or: None needed -->

---

## Safety Invariants *(required in every PR)*

- [ ] **No runtime loop behavior changed**
- [ ] **Mission Brain Advisory remains advisory-only** (never a gate, never auto-execution)
- [ ] **#942 recovery proposals were not implemented in this PR**
- [ ] No global defaults changed
- [ ] No mandatory gate introduced
