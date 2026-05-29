---
name: Mission Task (MBOP)
about: Standard issue template following the Mission Brain Operating Protocol
title: 'feat/fix/refactor(#NNN): <short description>'
labels: mbop
assignees: ''
---

## MBOP Intake

### What
<!-- Describe exactly what this task requires. Be specific — no vague language. -->

### Where
<!-- Files, modules, APIs, or services affected. -->

### Why
<!-- Strategic context: why does this need to be done? What problem does it solve? -->

### Constraints
<!-- Hard rules that must not be violated. Examples:
- Must not change runtime loop behavior
- Mission Brain Advisory must remain advisory-only
- VastAI excluded from chains
- No #942 recovery proposals implemented
-->

### Output Expected
<!-- Concrete deliverables and acceptance criteria. Each criterion should be independently verifiable. -->

- [ ] AC-1: 
- [ ] AC-2: 
- [ ] AC-3: 

### Unknowns
<!-- Open questions that need to be resolved before or during planning. -->
<!-- If > 3 critical unknowns, STOP and resolve before starting. -->

---

## Operating Mode

- [ ] **Compact** — single-file, < 2h, clear scope, no architectural impact
- [ ] **Full** — new module, multi-file, architectural decision, > 2h, or epic

*When in doubt, use Full Mode.*

---

## Safety Invariants (required for every issue)

- [ ] No runtime loop behavior will be changed
- [ ] Mission Brain Advisory remains advisory-only (never a gate)
- [ ] No #942 recovery proposals will be implemented
- [ ] No global defaults will be changed
- [ ] No mandatory gate will be introduced

---

## Notes

<!-- Any additional context, links, related issues. -->
<!-- Parent issue: #NNN -->
<!-- Related: #NNN -->
