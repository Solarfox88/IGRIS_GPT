# Teacher/Governor Anti-Loop — Epic #46

Definitive anti-loop enforcement with hard governor powers.

## Hard Powers

1. **Block incoherent fallbacks** — block entire families
2. **Reject duplicate tasks** — semantic + fingerprint deduplication
3. **Produce escalation reports** — full governance state dump
4. **Materialize alternative tasks** — auto-shift to unsaturated family
5. **Explain differentiator** — require concrete justification for repeating

## Family Saturation

After 3 repetitions of the same family (configurable threshold), the family is
saturated. The governor forces strategy shift to an unsaturated alternative.

### Supported Families

`observation`, `synthesis`, `repo_diff_discovery`, `patch_strategy`,
`branch_pr_plan`, `review_gate`, `candidate_materialization`,
`mastery_cycle`, `mastery_gate`, `school_report`, `grading_diagnosis`,
`stabilization_audit`, `devops_deploy`, `server_diagnosis`,
`test_repair`, `code_patch`, `documentation`, `security_audit`, `other`

## Semantic Deduplication

TaskFingerprint considers: family, intent, file target, expected effect,
block cause, success criteria. SHA-256 hash used for comparison.

## Forced Strategy Shift

When a family is saturated and no valid differentiator is provided:
1. Look up predefined shift targets (e.g., `code_patch` → `test_repair`)
2. Select first unsaturated, unblocked alternative
3. If all alternatives exhausted → escalate to human

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/governor/evaluate` | Evaluate proposed task |
| `GET` | `/api/governor/summary` | Governor state summary |
| `GET` | `/api/governor/saturated` | Saturated families + counts |
| `POST` | `/api/governor/block-family` | Block a family |
| `POST` | `/api/governor/materialize-alternative` | Auto-shift to alternative |
| `GET` | `/api/governor/escalation-report` | Full escalation report |
| `POST` | `/api/governor/record-task` | Record task execution |

## Persistence

Governor state saved to `.igris/governor/state.json`:
- History (descriptions + family tags)
- Blocked families
- Forced shift count
- Escalation log

## File Layout

```
igris/core/teacher_governor.py         — Governor logic
tests/test_teacher_governor.py         — 37 tests
docs/TEACHER_GOVERNOR_ANTI_LOOP.md     — This file
```
