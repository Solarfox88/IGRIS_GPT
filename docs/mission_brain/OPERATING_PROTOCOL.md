# Mission Brain Operating Protocol (MBOP)

**Version**: 1.0  
**Issue**: #936  
**Status**: DEFAULT WORKFLOW — effective immediately  
**Scope**: All IGRIS tasks, issues, missions, sub-tasks

---

## 1. What is MBOP?

The **Mission Brain Operating Protocol** (MBOP) is the standard methodology IGRIS must
apply to every task, issue, or mission. It replaces the previous ad-hoc workflow:

```
❌ Old workflow
read issue → modify files → run tests → close issue
```

```
✅ MBOP workflow
intake → intent decomposition → requirements → plan → checklist →
actions → execution → verification → quality gate → satisfaction gate →
post-task evaluation → next-step propagation
```

MBOP is a **reasoning discipline**, not a runtime component. It runs at the
planning/execution layer, not inside the live agent loop. No loop behavior is changed.

---

## 2. Why MBOP becomes the default

Without a structured protocol:
- Issues get closed without verifying real intent was addressed
- Work drifts toward cosmetic changes instead of strategic goals
- Reviewers have no shared language to verify correctness
- Sub-tasks propagate without context
- Quality gates are implicit and easily skipped

MBOP makes every task **traceable**, **verifiable**, and **intentional**.

---

## 3. MBOP vs. Mission Brain Advisory — Critical Distinction

| Dimension | MBOP (this doc, #936) | Mission Brain Advisory (#942) |
|---|---|---|
| What it is | Reasoning/execution methodology | Reporting and advisory system |
| Role | How IGRIS works on any task | Generates advisory reports on runs |
| Scope | Every issue, task, mission | Selected failed/blocked runs only |
| Output | Structured execution trace | Advisory text / future proposals |
| Automation | None — human-controlled process | Advisory only, no auto-execution |
| Gate? | No | No — advisory-only, never a gate |
| Default? | Yes — default workflow | No — selected reports only |
| Loop change? | No | No |

**Principle**: Advisory proposes. MBOP evaluates. IGRIS executes only after process approval.

---

## 4. #936 vs. #942 — Scope Boundary

**#936 (this issue)** = Define and adopt MBOP as IGRIS's default work methodology.

**#942** = Evolve Mission Brain Advisory from textual recommendations toward structured
recovery proposals. This is a future epic, separate from #936.

What **#936 does NOT do**:
- Does not implement Advisory recovery proposals
- Does not change Mission Brain Advisory behavior
- Does not enable Advisory as a gate or trigger
- Does not anticipate #942 features

What this document says about #942 recovery proposals:
> Any future Advisory Recovery Proposal (from #942) MUST be treated as MBOP intake.
> The proposal enters the MBOP pipeline at the `intake` phase. It does not bypass
> planning, checklist, or quality gate. It is input to MBOP, not a command.

---

## 5. Operating Modes

### 5a. Compact Mode (simple tasks)

Use when: single-file change, < 2h effort, clear acceptance criteria, no architectural impact.

Required phases: **intake → requirements → checklist → execution → verification → satisfaction gate**

Minimum documentation: one comment or PR section covering:
- [ ] Intent (1 sentence)
- [ ] Requirements (bullets)
- [ ] Checklist (done/todo)
- [ ] Tests run
- [ ] Satisfaction gate passed?

### 5b. Full Mode (complex tasks)

Use when: new module, multi-file change, architectural decision, > 2h effort, or any epic.

Required phases: all 12 (see section 6).

Required documentation: PR body with all MBOP sections (see PR template).

**When in doubt, use Full Mode.**

---

## 6. The Twelve Phases

### Phase 1: Intake

Understand what the task is asking before touching any file.

Produce:
- **What** the issue asks
- **Where** it acts (files, modules, APIs)
- **Why** it is needed (strategic context)
- **Constraints** (hard rules that must not be violated)
- **Output expected** (deliverables, acceptance criteria)
- **Unknowns** (open questions requiring investigation before planning)

**Stop condition**: if unknowns > 3 and critical, pause and resolve before continuing.

### Phase 2: Intent Decomposition

Break the task into concrete, addressable sub-intents.

Each sub-intent must:
- Have a clear action verb (create, modify, delete, verify, document)
- Be independently testable
- Map to at least one acceptance criterion

**Anti-pattern**: a sub-intent that says "improve things" without specifying what "improved" looks like.

### Phase 3: Requirements

Transform intent into verifiable requirements using this format:

```
REQ-N: [system] MUST/SHOULD [behavior] WHEN [condition] SO THAT [goal]
```

Requirements must be:
- Specific (no vague language like "better", "more robust")
- Verifiable (test or review can confirm pass/fail)
- Scoped (does not expand beyond issue boundaries)

### Phase 4: Plan

Write the implementation plan **before touching files**.

Plan must include:
- Files to create/modify (with rationale)
- Dependencies between changes (ordering)
- Risk assessment (what can go wrong)
- Rollback path (how to undo if needed)
- Estimated effort tier (compact vs. full)

**Anti-pattern**: "I'll figure it out as I go" — plan first, execute second.

### Phase 5: Checklist

Derive a specific checklist from requirements and plan.

Each item must be:
- Binary (done / not done)
- Linked to a requirement or acceptance criterion
- Actionable (describes a concrete deliverable or test)

The checklist is produced BEFORE execution and verified AFTER.

### Phase 6: Actions

List every concrete action to take, in order:
- `CREATE file X with content Y`
- `MODIFY function Z in file W`
- `ADD test for requirement REQ-N`
- `RUN script S and verify output`

Actions must match the plan. Any deviation must be documented.

### Phase 7: Execution

Execute actions in the listed order. For each action:
- Note what was done
- Note any deviation from plan and why
- If blocked: document the blocker and stop (do not work around without re-planning)

**No silent deviations from plan.** If the plan was wrong, update the plan, then execute.

### Phase 8: Verification

For every requirement, verify it is met:
- Run tests (unit, integration, acceptance)
- Review output against acceptance criteria
- Check for regressions

Produce a verification table:

| REQ | Test/Check | Result |
|-----|-----------|--------|
| REQ-1 | test_mbop_docs.py | PASS |
| REQ-2 | review protocol sections | PASS |

### Phase 9: Quality Gate

The quality gate answers: **Did we build it right?**

Must pass all:
- [ ] All checklist items completed
- [ ] All tests pass (no red, no skip without documented reason)
- [ ] No regressions in existing tests
- [ ] Code/docs follow project conventions
- [ ] No silent TODO left in delivered code
- [ ] No placeholder or stub left as "final" output

**If quality gate fails**: do not advance. Fix and re-verify.

### Phase 10: Satisfaction Gate

The satisfaction gate answers: **Did we build the right thing?**

Must confirm:
- [ ] The acceptance criteria of the issue are met
- [ ] The strategic intent (not just literal words) is addressed
- [ ] The task did not drift to a cosmetic/wrapper solution
- [ ] No scope creep (no unrequested changes)
- [ ] Reviewer/watchdog can independently verify from checklist alone

**Technical success ≠ strategic success.**  
A passing test suite does not automatically mean the issue intent was satisfied.

### Phase 11: Post-Task Evaluation

After the task is complete, produce a brief evaluation:
- What worked well in the process?
- What caused delays or errors?
- Were requirements accurate? If not, why?
- Are there follow-up issues to open?
- Lessons for future similar tasks

This is NOT optional for full-mode tasks. It feeds IGRIS's learning loop.

### Phase 12: Next-Step Propagation

If the task produces follow-up work:
- Open sub-issues with complete intake section
- Link them to the parent issue
- Each sub-issue must independently go through MBOP
- Do not leave implicit next steps in comments

**Anti-pattern**: "we should also do X" in a PR comment with no issue opened.

---

## 7. Stop Conditions

IGRIS must stop and not proceed when:
- Unknowns > 3 critical and unresolved (Phase 1)
- Requirements are contradictory (Phase 3)
- Plan has no rollback path for irreversible operations (Phase 4)
- Quality gate fails (Phase 9)
- Satisfaction gate fails (Phase 10)
- A constraint from intake would be violated by proceeding

Stopping is not failure. Stopping when the plan is wrong prevents larger failures.

---

## 8. What Is Explicitly Forbidden

MBOP does not permit:
- **Cosmetic/wrapper work**: creating files that just rename or wrap existing things without adding value
- **Skipping intake**: executing without understanding what was asked
- **Missing requirements**: delivering without verifiable criteria
- **Missing checklist**: executing without a pre-verified list of deliverables
- **Missing tests**: closing issues that require verification with no automated check
- **Missing quality gate**: advancing without verifying correctness
- **Missing satisfaction gate**: advancing without verifying intent was met
- **Missing next-step propagation**: leaving follow-up work as implicit comments
- **Mega-PR anti-pattern**: bundling unrelated changes in one PR to avoid review
- **Acceptance criteria not covered**: closing an issue when acceptance criteria are partially unmet
- **Scope creep**: changing things not requested by the issue
- **Silent plan deviation**: executing differently from the plan without documenting why

---

## 9. Technical Success vs. Strategic Success

**Technical success** = tests pass, files created, CI green.

**Strategic success** = the issue's real intent is addressed, the system is better, the next developer understands what was done and why.

MBOP requires both. The satisfaction gate (Phase 10) enforces strategic success.

Example:
- Technical success only: "I created a new file and all tests pass."
- Strategic success: "The MBOP protocol is now documented, distinct from Advisory,
  usable by future agents, and has a working validation script that will catch
  violations before they merge."

---

## 10. Advisory Recovery Proposals and MBOP

When (in future) Mission Brain Advisory generates structured recovery proposals (#942):

1. The proposal is **intake input** to MBOP — it enters at Phase 1
2. It goes through all MBOP phases (intent decomposition, requirements, plan, etc.)
3. It is NOT automatically executed
4. It is NOT a gate that blocks the live loop
5. It requires human/reviewer approval before becoming work
6. The advisory system itself does not change; only how its proposals are processed changes

**This is the only connection between #936 and #942.**

---

## 11. MBOP Application to IGRIS Agents and Reviewers

### For IGRIS (agent executing a task):
- Apply MBOP before every task — compact or full mode
- Never close an issue without satisfying both quality gate and satisfaction gate
- Always propagate next steps as opened issues

### For Claude (pair programming):
- Before generating any code: produce intake + requirements
- Never suggest "quick fixes" that skip requirements
- Always include checklist in PRs

### For reviewers and watchdog:
- Use the PR checklist to verify MBOP was applied
- Reject PRs that are cosmetic-only or lack intent/requirements sections
- Verify satisfaction gate was actually evaluated, not just asserted

---

## 12. Relationship to Other IGRIS Systems

| System | Relationship to MBOP |
|--------|----------------------|
| Mission Brain Advisory | Advisory-only; Advisory proposes, MBOP evaluates |
| DependencyChecker (#614) | Pre-flight check before MBOP execution phase |
| WorkSession (#540) | Records MBOP execution trace in memory graph |
| ReflectionHook (#532) | Post-task evaluation feed — learns from MBOP runs |
| ToolTracker (#534) | Quality gate input — tool success rates |
| ContextSectionWeighter (#524) | Informs planning phase with historical context utility |

---

## 13. Version History

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-05-29 | Initial protocol — adopted as default workflow (#936) |
