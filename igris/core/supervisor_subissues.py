"""Supervisor sub-issue auto-creation utilities.

Standalone function for creating one GitHub issue per sub_mission from a
decomposition, including deduplication, dependency-wave scheduling, file-scope
conflict detection, title hygiene, acceptance-criteria generation, and parent
issue summary posting. Extracted from self_repair_supervisor.py for modularity
(Issue #1371).
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING, Any, Dict, List

from igris.core.supervisor_models import _safe_redact
import logging


_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from igris.core.supervisor_models import RankSupervisorConfig, SupervisorRun


def auto_create_subissues(
    supervisor,
    run: "SupervisorRun",
    config: "RankSupervisorConfig",
    decomposition: Dict[str, Any],
    triggering_signal: str,
) -> List[str]:
    """Create one GitHub issue per sub_mission and return list of created URLs.

    Each issue body includes parent run context, generated_by, risk, scopes.
    After creating all issues, posts a summary comment on the parent issue (if
    a parent URL can be inferred from config.goal or run.report).
    """
    sub_missions = decomposition.get("sub_missions") or []
    generated_by = decomposition.get("generated_by", "unknown")
    why_too_large = _safe_redact(str(decomposition.get("why_too_large", "")))
    first_sub = decomposition.get("first_sub_mission", "")

    # Collect parent issue labels to propagate to sub-issues (roadmap, P*, phase-*).
    # This ensures the watchdog can discover sub-issues the same way it finds parent
    # roadmap issues.  Best-effort: if we can't read the parent labels, we proceed
    # without them rather than blocking sub-issue creation.
    _parent_inherit_labels: List[str] = []
    try:
        import re as _re, subprocess as _subp2
        _parent_num_m = _re.search(r"#(\d+)", config.goal or "")
        if _parent_num_m:
            _parent_num = int(_parent_num_m.group(1))
            _pl = _subp2.run(
                ["gh", "issue", "view", str(_parent_num), "--json", "labels"],
                capture_output=True, text=True, cwd=supervisor.project_root, timeout=15,
            )
            if _pl.returncode == 0:
                import json as _json2
                _raw_labels = _json2.loads(_pl.stdout or "{}").get("labels", [])
                for _lbl in _raw_labels:
                    _n = (_lbl.get("name") or "").lower()
                    if _n in ("roadmap", "created-by:igris") or _n.startswith("p") and len(_n) == 2 and _n[1].isdigit() or _n.startswith("phase-"):
                        _parent_inherit_labels.append(_lbl.get("name", _n))
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        _log.debug("supervisor_subissues: narrowed catch failed: %s", exc, exc_info=True)

    # Epic #1075 — Dependency-order scheduling: build execution waves and log
    # the wave structure so the autochain can respect creation order.
    try:
        from igris.core.parallel_task_runner import ParallelTask, build_dependency_order
        _dep_tasks = [
            ParallelTask(
                task_id=str(sub.get("title", f"sub_{j}")),
                goal=str(sub.get("goal", "")),
                depends_on=list(sub.get("dependencies") or []),
                initial_context={"file_scopes": sub.get("allowed_file_scopes") or []},
            )
            for j, sub in enumerate(sub_missions)
        ]
        _waves = build_dependency_order(_dep_tasks)
        _wave_summary = [
            {"wave": w, "tasks": [t.task_id for t in wave]}
            for w, wave in enumerate(_waves)
        ]
        run.add(
            "subissue_dependency_order",
            "computed",
            f"Dependency waves: {len(_waves)} wave(s) for {len(sub_missions)} sub-mission(s)",
            wave_count=len(_waves),
            waves=_wave_summary,
        )
    except (ImportError, TypeError, ValueError, KeyError, AttributeError) as _dep_exc:
        run.add(
            "subissue_dependency_order",
            "skipped",
            f"build_dependency_order unavailable: {_dep_exc}",
        )

    created_urls: List[str] = []
    run.add(
        "subissue_creation",
        "running",
        f"Creating {len(sub_missions)} sub-issue(s) from decomposition.",
        count=len(sub_missions),
        generated_by=generated_by,
    )

    # Build a set of existing open issue titles to deduplicate sub-missions.
    # Fixes #613: IGRIS was creating identical sub-missions on every decomposition.
    existing_open_titles: set = set()
    try:
        import subprocess as _subp
        _existing = _subp.run(
            ["gh", "issue", "list", "--state", "open", "--limit", "50",
             "--json", "number,title"],
            capture_output=True, text=True, cwd=supervisor.project_root, timeout=20,
        )
        if _existing.returncode == 0:
            import json as _json
            for _issue in _json.loads(_existing.stdout or "[]"):
                existing_open_titles.add((_issue.get("title") or "").lower().strip())
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        _log.debug("supervisor_subissues: narrowed catch failed: %s", exc, exc_info=True)

    # Epic #1078 — Enforce max sub-issue count to prevent noisy decompositions.
    _MAX_SUBISSUES = int(os.getenv("IGRIS_MAX_SUBISSUES_PER_DECOMPOSITION", "12"))
    if len(sub_missions) > _MAX_SUBISSUES:
        run.add(
            "subissue_creation",
            "capped",
            f"Decomposition produced {len(sub_missions)} sub-missions; capping at {_MAX_SUBISSUES}.",
            original_count=len(sub_missions),
            cap=_MAX_SUBISSUES,
        )
        sub_missions = sub_missions[:_MAX_SUBISSUES]

    # Epic #1078 — File scope overlap detection.
    # Build ParallelTask-like dicts from sub_missions so we can detect which
    # files would be touched by multiple concurrent sub-issues, and log
    # conflicts so the operator can add explicit serialisation (depends_on).
    try:
        from igris.core.parallel_task_runner import ParallelTask, detect_file_conflicts
        _ptasks = [
            ParallelTask(
                task_id=str(sub.get("title", f"sub_{j}")),
                goal=str(sub.get("goal", "")),
                initial_context={"file_scopes": sub.get("allowed_file_scopes") or []},
                depends_on=list(sub.get("dependencies") or []),
            )
            for j, sub in enumerate(sub_missions)
        ]
        _scope_conflicts = detect_file_conflicts(_ptasks)
        if _scope_conflicts:
            run.add(
                "subissue_scope_conflict",
                "warning",
                f"File scope overlap detected across {len(_scope_conflicts)} file(s): "
                + "; ".join(
                    f"{f} → {ids}" for f, ids in list(_scope_conflicts.items())[:5]
                ),
                conflicts=_scope_conflicts,
            )
    except (ImportError, TypeError, ValueError, KeyError, AttributeError) as _sc_exc:
        run.add(
            "subissue_scope_conflict",
            "skipped",
            f"Scope conflict detection unavailable: {_sc_exc}",
        )

    for i, sub in enumerate(sub_missions):
        title = _safe_redact(str(sub.get("title", f"Sub-task {i+1}")))
        goal_text = _safe_redact(str(sub.get("goal", "")))
        risk = str(sub.get("risk_level", "medium"))
        scopes = sub.get("allowed_file_scopes") or []
        tests = sub.get("tests") or []
        criteria = sub.get("acceptance_criteria") or []
        deps = sub.get("dependencies") or []

        # Epic #1078 — Title hygiene: reject vague or auto-generated titles.
        # Normalized format: <Area>: <concrete action> for <scope>
        _title_lower = title.lower().strip()
        _title_is_vague = (
            not _title_lower
            or len(_title_lower) < 5
            or _title_lower.startswith("implement github issue #")
            or "igris/**" in _title_lower
            or _title_lower.startswith("sub-task ")
            or _title_lower.startswith("sub_task ")
            or _title_lower == f"sub-task {i+1}"
        )
        if _title_is_vague:
            # Build a meaningful title from goal text rather than a generic placeholder
            _goal_short = goal_text.strip()[:60].rstrip(".").rstrip(",")
            _area = (scopes[0].split("/")[0] if scopes else config.rank_id).strip("/")
            _clean_title = f"{_area}: {_goal_short}" if _goal_short else f"{config.rank_id}: sub-task {i+1}"
            run.add(
                "subissue_title_hygiene",
                "normalized",
                f"Vague title normalized: {title!r} → {_clean_title!r}",
                index=i + 1,
                original_title=title,
                normalized_title=_clean_title,
            )
            title = _clean_title

        # Epic #1078 — AC validation: generate minimal ACs when missing or vague.
        _VAGUE_AC_MARKERS = {"_not specified_", "not specified", "tbd", "todo", "n/a", ""}
        _valid_criteria = [
            c for c in criteria
            if str(c).strip().lower() not in _VAGUE_AC_MARKERS and len(str(c).strip()) > 10
        ]
        if len(_valid_criteria) < 3:
            # Generate deterministic acceptance criteria from goal and tests
            _generated_acs = []
            if goal_text:
                _generated_acs.append(f"Implementation matches goal: {goal_text[:120]}")
            if tests:
                _generated_acs.append(f"All test targets pass: {', '.join(str(t) for t in tests[:3])}")
            else:
                _generated_acs.append("pytest passes with no regressions on the full test suite")
            _generated_acs.append("No new lint errors introduced; changed files are importable")
            _generated_acs.append("PR diff is minimal and scoped to the stated file targets")
            _generated_acs += list(_valid_criteria)  # keep any valid ones the model produced
            criteria = _generated_acs
            run.add(
                "subissue_ac_generated",
                "auto_generated",
                f"Sub-mission {i+1}: generated {len(_generated_acs)} ACs (had {len(_valid_criteria)} valid).",
                index=i + 1,
                title=title,
                ac_count=len(_generated_acs),
            )

        # Epic #1078 — Goal-hash dedup: also check normalized goal text, not just title.
        import hashlib as _hashlib
        _goal_hash = _hashlib.md5(goal_text.lower().strip().encode()).hexdigest()[:8]
        _goal_hash_key = f"__goal_hash:{_goal_hash}"
        if _goal_hash_key in existing_open_titles:
            run.add(
                "subissue_dedup",
                "skipped",
                f"Sub-mission {i+1} has duplicate goal hash ({_goal_hash}): {title}",
                index=i + 1,
                title=title,
                reason="dedup:goal_hash_match",
            )
            continue
        existing_open_titles.add(_goal_hash_key)

        # Dedup: skip sub-mission if an open issue with same title already exists
        if title.lower().strip() in existing_open_titles:
            # Find existing URL to include in created_urls so autochain works
            try:
                _found = _subp.run(
                    ["gh", "issue", "list", "--state", "open", "--search", title,
                     "--json", "number,title", "--limit", "5"],
                    capture_output=True, text=True, cwd=supervisor.project_root, timeout=20,
                )
                if _found.returncode == 0:
                    for _fi in _json.loads(_found.stdout or "[]"):
                        if (_fi.get("title") or "").lower().strip() == title.lower().strip():
                            _repo_url = "https://github.com/Solarfox88/IGRIS_GPT"
                            _existing_url = f"{_repo_url}/issues/{_fi['number']}"
                            created_urls.append(_existing_url)
                            run.add(
                                "subissue_dedup",
                                "skipped",
                                f"Sub-mission {i+1} already exists: {title}",
                                index=i + 1,
                                title=title,
                                url=_existing_url,
                                reason="dedup:title_match",
                            )
                            break
            except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                _log.debug("supervisor_subissues: narrowed catch failed: %s", exc, exc_info=True)
            continue
        out_of_scope = sub.get("out_of_scope") or []
        success_signal = str(sub.get("success_signal", "")).strip()
        failure_fallback = str(sub.get("failure_fallback", "")).strip()

        scopes_md = "\n".join(f"- `{s}`" for s in scopes) if scopes else "_not specified_"
        tests_md = "\n".join(f"- `{t}`" for t in tests) if tests else "_not specified_"
        criteria_md = "\n".join(f"- {c}" for c in criteria) if criteria else "_not specified_"
        deps_md = ", ".join(deps) if deps else "none"
        oos_md = "\n".join(f"- {o}" for o in out_of_scope) if out_of_scope else "_not specified_"
        success_md = success_signal or "All acceptance criteria verified by the supervisor"
        fallback_md = failure_fallback or "Escalate to human review; reopen parent issue"

        body = (
            f"## Sub-mission {i+1} of {len(sub_missions)}\n\n"
            f"**Goal:** {goal_text}\n\n"
            f"**Risk level:** {risk}\n"
            f"**Dependencies:** {deps_md}\n\n"
            f"### Acceptance criteria\n{criteria_md}\n\n"
            f"### File scopes\n{scopes_md}\n\n"
            f"### Test targets\n{tests_md}\n\n"
            f"### Out of scope\n{oos_md}\n\n"
            f"### Success signal\n{success_md}\n\n"
            f"### Failure fallback\n{fallback_md}\n\n"
            f"---\n"
            f"**Parent run:** `{run.run_id}` (rank `{run.rank_id}`)\n"
            f"**Decomposition source:** `{generated_by}`\n"
            f"**Trigger signal:** `{triggering_signal}`\n"
            f"**Why original mission was too large:** {why_too_large}\n"
            f"**Original goal:** {_safe_redact(config.goal)}\n"
        )

        result = supervisor.backend.create_issue(title, body)
        if result.success:
            url = result.output.strip()
            created_urls.append(url)
            run.add(
                "subissue_created",
                "success",
                f"Created sub-issue: {title}",
                index=i + 1,
                title=title,
                url=url,
                risk=risk,
            )
            # Propagate parent roadmap/priority/phase labels so the watchdog
            # can discover and schedule sub-issues automatically.
            # Always add "no-decompose" so the watchdog knows this is a leaf
            # sub-issue that must be implemented directly, not decomposed again.
            _sub_labels = list(_parent_inherit_labels)
            if "no-decompose" not in _sub_labels:
                _sub_labels.append("no-decompose")
            # Also add depends-on-NNN labels for dependencies between sub-issues
            for _dep in deps:
                # deps may be issue URLs or "Sub-task N" style references
                import re as _re2
                _dep_num = _re2.search(r"#?(\d+)", str(_dep))
                if _dep_num:
                    _sub_labels.append(f"depends-on-{_dep_num.group(1)}")
            try:
                import subprocess as _subp3
                _subp3.run(
                    ["gh", "issue", "edit", url, "--add-label",
                     ",".join(_sub_labels)],
                    capture_output=True, text=True,
                    cwd=supervisor.project_root, timeout=20,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                _log.debug("supervisor_subissues: narrowed catch failed: %s", exc, exc_info=True)
        else:
            run.add(
                "subissue_created",
                "failure",
                f"Failed to create sub-issue: {title}",
                index=i + 1,
                title=title,
                error=_safe_redact(result.error),
            )

    # Post summary comment on parent issue if we can infer the URL.
    parent_url = supervisor._infer_parent_issue_url(config.goal)
    if parent_url and created_urls:
        sub_list = "\n".join(
            f"- {url} — {sub.get('title','?')}"
            for url, sub in zip(created_urls, sub_missions)
        )
        comment = (
            f"## Decomposition sub-issues created\n\n"
            f"Run `{run.run_id}` produced {len(created_urls)} sub-issue(s) "
            f"via `{generated_by}`:\n\n{sub_list}\n\n"
            f"First sub-mission to run: **{_safe_redact(first_sub)}**"
        )
        comment_result = supervisor.backend.update_issue(parent_url, comment)
        run.add(
            "parent_issue_updated",
            "success" if comment_result.success else "failure",
            "Posted sub-issue summary to parent issue.",
            parent_url=parent_url,
            sub_count=len(created_urls),
        )

    run.add(
        "subissue_creation",
        "success" if created_urls else "failure",
        f"Sub-issue creation complete. Created {len(created_urls)}/{len(sub_missions)}.",
        created_count=len(created_urls),
        total=len(sub_missions),
        urls=created_urls,
    )
    return created_urls
