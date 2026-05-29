# MBOP Checklist Reference

**Issue**: #936  
**Version**: 1.0  
**Purpose**: Practical verification checklist for IGRIS agents, Claude, reviewers, and watchdog.

Use this document to verify whether a task/PR has genuinely followed the Mission Brain
Operating Protocol. Check each item: ✅ = met, ❌ = not met, ⚠️ = partially met.

---

## A. Compact Mode Checklist

Use for: single-file changes, < 2h effort, clear scope, no architectural impact.

```
MBOP COMPACT CHECKLIST
======================

[ ] C1. Intent documented (1–3 sentences: what, why, where)
[ ] C2. Requirements listed (at least 2 verifiable bullets)
[ ] C3. Pre-execution checklist written (items to verify after work)
[ ] C4. All checklist items marked complete after execution
[ ] C5. Tests run (unit or integration, at minimum existing suite)
[ ] C6. Quality gate: all checklist items done + tests green
[ ] C7. Satisfaction gate: issue intent actually addressed (not just literal words)
[ ] C8. No cosmetic/wrapper changes without real value
[ ] C9. Mission Brain Advisory NOT enabled as gate or auto-execution
[ ] C10. No #942 recovery proposals implemented
```

**Compact mode minimum PR section:**
```markdown
## MBOP Compact
- Intent: <1 sentence>
- Requirements: <bullets>
- Checklist: <done/todo list>
- Tests: <what was run>
- Quality gate: PASS / FAIL
- Satisfaction gate: PASS / FAIL
- Advisory not modified: YES
```

---

## B. Full Mode Checklist

Use for: new modules, multi-file changes, architectural decisions, epics, > 2h effort.

```
MBOP FULL CHECKLIST
===================

PHASE 1 — INTAKE
[ ] F1.  "What" documented (issue request stated clearly)
[ ] F2.  "Where" documented (files/modules/APIs affected)
[ ] F3.  "Why" documented (strategic context)
[ ] F4.  Constraints listed (hard rules that must not be violated)
[ ] F5.  Output expected documented (deliverables + acceptance criteria)
[ ] F6.  Unknowns identified and either resolved or explicitly accepted

PHASE 2 — INTENT DECOMPOSITION
[ ] F7.  Issue broken into sub-intents with action verbs
[ ] F8.  Each sub-intent is independently testable
[ ] F9.  Each sub-intent maps to at least one acceptance criterion

PHASE 3 — REQUIREMENTS
[ ] F10. At least 3 verifiable requirements (REQ-N format or equivalent)
[ ] F11. No vague language ("better", "more robust", "improved")
[ ] F12. Requirements are scoped (no scope creep)

PHASE 4 — PLAN
[ ] F13. Plan written BEFORE files were touched
[ ] F14. Files to create/modify listed with rationale
[ ] F15. Dependencies between changes noted
[ ] F16. Risk assessment present
[ ] F17. Rollback path identified for irreversible operations

PHASE 5 — CHECKLIST
[ ] F18. Pre-execution checklist derived from requirements
[ ] F19. Each item is binary (done/not done)
[ ] F20. Each item linked to a requirement or acceptance criterion

PHASE 6 — ACTIONS
[ ] F21. Actions listed in execution order
[ ] F22. Actions match the plan
[ ] F23. Deviations from plan documented

PHASE 7 — EXECUTION
[ ] F24. Actions executed in documented order
[ ] F25. No silent deviations from plan
[ ] F26. Blockers documented if encountered

PHASE 8 — VERIFICATION
[ ] F27. Every requirement verified (test, review, or manual check)
[ ] F28. Verification table or equivalent produced
[ ] F29. Acceptance criteria checked one by one

PHASE 9 — QUALITY GATE
[ ] F30. All checklist items completed
[ ] F31. All tests pass (zero red, no unexplained skip)
[ ] F32. No regressions in existing tests
[ ] F33. No silent TODO left as "final" output
[ ] F34. No placeholder or stub left as delivered feature

PHASE 10 — SATISFACTION GATE
[ ] F35. Acceptance criteria of issue are met
[ ] F36. Strategic intent addressed (not just literal words)
[ ] F37. No cosmetic/wrapper drift
[ ] F38. No scope creep (unrequested changes absent)
[ ] F39. Reviewer/watchdog can independently verify from checklist

PHASE 11 — POST-TASK EVALUATION
[ ] F40. Brief evaluation produced (what worked, what didn't)
[ ] F41. Follow-up issues identified or explicitly noted as "none"
[ ] F42. Lessons documented for future similar tasks

PHASE 12 — NEXT-STEP PROPAGATION
[ ] F43. Follow-up items opened as issues (not left in comments)
[ ] F44. Sub-issues have their own intake section
[ ] F45. Parent/child links set on GitHub

SAFETY INVARIANTS (always required regardless of mode)
[ ] F46. Mission Brain Advisory NOT enabled as gate or auto-execution
[ ] F47. Live agent loop behavior NOT changed
[ ] F48. No #942 recovery proposals implemented or anticipated
[ ] F49. Global defaults NOT changed
[ ] F50. No mandatory gate introduced
```

---

## C. Reviewer / Watchdog Checklist

Use this to review any PR before approval.

```
REVIEWER / WATCHDOG CHECKLIST
==============================

INTENT VERIFICATION
[ ] R1.  PR description includes clear intent statement
[ ] R2.  Intent matches the referenced issue (read the issue, not just PR)
[ ] R3.  The PR is not cosmetic-only (wrapper, rename without value, docs only for docs)

REQUIREMENTS VERIFICATION
[ ] R4.  Requirements are listed and verifiable
[ ] R5.  Requirements are not vague
[ ] R6.  Requirements do not expand scope beyond the issue

CHECKLIST VERIFICATION
[ ] R7.  A pre-execution checklist was produced
[ ] R8.  Checklist is fully completed (no items left as TODO)
[ ] R9.  Checklist items map to acceptance criteria

TEST VERIFICATION
[ ] R10. Tests exist for the delivered functionality
[ ] R11. Tests are not trivially wrong (e.g. always-pass assertions)
[ ] R12. Existing test suite passes (check CI)
[ ] R13. New tests cover at least the happy path AND one failure path

QUALITY GATE VERIFICATION
[ ] R14. Quality gate was evaluated and passed
[ ] R15. No placeholder left as deliverable
[ ] R16. No unexplained test skip

SATISFACTION GATE VERIFICATION
[ ] R17. Satisfaction gate was evaluated (not just asserted "PASS")
[ ] R18. All acceptance criteria from the issue are addressed
[ ] R19. Technical success AND strategic success confirmed

SAFETY VERIFICATION
[ ] R20. "No runtime loop behavior changed" statement present and credible
[ ] R21. "Mission Brain Advisory remains advisory-only" statement present and credible
[ ] R22. "#942 recovery proposals were not implemented" statement present and credible
[ ] R23. No new global default introduced
[ ] R24. No new mandatory gate introduced

POST-TASK EVALUATION
[ ] R25. Post-task evaluation present (full mode) or explicitly waived (compact mode)
[ ] R26. Follow-up issues opened if noted

REJECT CONDITIONS (automatic rejection):
[ ] R27. PR is cosmetic-only with no functional change
[ ] R28. PR lacks intent/requirements section entirely
[ ] R29. Acceptance criteria are not covered
[ ] R30. Tests are missing for non-trivial changes
[ ] R31. Advisory system was modified to become a gate
[ ] R32. Loop decision behavior was changed
[ ] R33. Auto-execution was introduced
```

---

## D. PR Review Checklist (Author Self-Check Before Submitting)

```
PR SELF-CHECK BEFORE SUBMITTING
================================

[ ] PR1.  PR title follows convention: type(#issue): description
[ ] PR2.  PR body includes MBOP sections (compact or full)
[ ] PR3.  All acceptance criteria referenced in the issue are addressed
[ ] PR4.  CI is green (or failures are documented and justified)
[ ] PR5.  No stray debug code, TODO stubs, or commented-out code in delivered files
[ ] PR6.  Files changed list matches what was planned
[ ] PR7.  "No runtime loop behavior changed" explicitly stated
[ ] PR8.  "Mission Brain Advisory remains advisory-only" explicitly stated
[ ] PR9.  "#942 recovery proposals were not implemented" explicitly stated
[ ] PR10. Post-task evaluation section present (full mode)
[ ] PR11. Next-step issues opened if noted
[ ] PR12. Satisfaction gate passed (not just quality gate)
```

---

## E. Stop Conditions

The following conditions MUST cause IGRIS to stop and not proceed:

| # | Condition | When Triggered |
|---|-----------|----------------|
| S1 | Unknowns > 3 critical and unresolved | Phase 1 |
| S2 | Requirements are contradictory | Phase 3 |
| S3 | Plan has no rollback path for irreversible operations | Phase 4 |
| S4 | Quality gate fails | Phase 9 |
| S5 | Satisfaction gate fails | Phase 10 |
| S6 | Proceeding would violate a constraint from Phase 1 | Any phase |
| S7 | Advisory system would be made into a gate | Any phase |
| S8 | Loop decision behavior would be changed | Any phase |

Stopping is the correct action. It is not failure. It prevents larger failures.

---

## F. Failure Patterns Reference

These are recognized anti-patterns that automatically fail the satisfaction gate:

### F-WRAP: Wrapper/Cosmetic Work
**Definition**: Creating new files or functions that merely rename or wrap existing things
without adding real functionality, correctness, or understandability.  
**Example**: Renaming a function and calling it a "refactor" without changing behavior.  
**Detection**: The PR adds files but no new behavior, test coverage, or documented decision.

### F-INTENT: Missing Intent
**Definition**: Executing without documenting what was asked and why.  
**Example**: Jumping to code changes without reading the issue.  
**Detection**: PR has no intent statement; reviewer cannot tell what problem was solved.

### F-REQ: Missing Requirements
**Definition**: Delivering without verifiable criteria.  
**Example**: "I improved the system" — impossible to verify.  
**Detection**: No requirement list in PR or planning docs.

### F-CHECKLIST: Missing Checklist
**Definition**: Executing without a pre-verified list of deliverables.  
**Example**: "I just wrote the code and checked it worked."  
**Detection**: No checklist in PR body; items may be done but not traceable.

### F-TEST: Missing Tests
**Definition**: Closing issues that require verification with no automated check.  
**Example**: New module with no tests; "I manually tested it."  
**Detection**: No new test file for non-trivial functionality.

### F-QG: Missing Quality Gate
**Definition**: Advancing without verifying correctness.  
**Example**: "All done!" with no mention of whether tests pass.  
**Detection**: No quality gate section in PR.

### F-SG: Missing Satisfaction Gate
**Definition**: Advancing without verifying intent was met.  
**Example**: Tests pass but acceptance criteria from issue are not checked.  
**Detection**: PR has quality gate but no satisfaction gate; or satisfaction gate asserted without evidence.

### F-NSP: Missing Next-Step Propagation
**Definition**: Leaving follow-up work as implicit comments or TODO.  
**Example**: "We should also add X" in a comment, no issue opened.  
**Detection**: PR comments with "should/could/eventually" without opened issues.

### F-MEGA: Mega-PR Anti-Pattern
**Definition**: Bundling unrelated changes in one PR to avoid review.  
**Example**: Fixing 5 different issues in one PR.  
**Detection**: PR files changed > 20, multiple distinct intents, no shared acceptance criterion.

### F-AC: Acceptance Criteria Not Covered
**Definition**: Closing an issue when some acceptance criteria are partially unmet.  
**Example**: Issue has 5 acceptance criteria, PR covers 3.  
**Detection**: Checklist item for each acceptance criterion is missing or unchecked.

### F-CONFUSE: MBOP/Advisory Confusion
**Definition**: Treating MBOP (operating protocol) as if it were Advisory, or vice versa.  
**Example**: "Advisory now enforces MBOP gates" — WRONG. Advisory is advisory-only.  
**Detection**: PR description conflates MBOP with Advisory; or Advisory is made mandatory.
