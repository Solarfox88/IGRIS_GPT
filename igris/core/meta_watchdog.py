from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict

from igris.core.smw_actions import execute_action
from igris.core.smw_diagnosis import diagnose, diagnose_with_llm
from igris.core.smw_patterns import detect_patterns
from igris.core.smw_sensors import take_snapshot
from igris.core.smw_teach import Incident, record_incident, teach_back
from igris.core.smw_pr_review import PRReviewRequest, load_review_results, review_pr, save_review_result
from igris.core.smw_weak_signals import run_all_detectors
# Issue #521 — CodeHealthMonitor (lazy import to avoid startup overhead)
_code_health_monitor_cls = None
def _get_code_health_monitor():
    global _code_health_monitor_cls
    if _code_health_monitor_cls is None:
        from igris.core.code_health_monitor import CodeHealthMonitor
        _code_health_monitor_cls = CodeHealthMonitor
    return _code_health_monitor_cls

# Issue #522 — OutcomeQualityTracker (24h background job)
_last_quality_run: float = 0.0
_QUALITY_RUN_INTERVAL = 86400  # 24h

_SMW_POLL_SECONDS = 120
_SMW_COOLDOWN_PATTERNS: Dict[str, float] = {}

# Issue #732 — configurable auto-merge confidence threshold (default 0.8, NOT 0.5)
import os as _os
_SMW_MERGE_CONFIDENCE: float = float(_os.getenv("IGRIS_SMW_MERGE_CONFIDENCE", "0.8"))


async def _smw_loop(project_root: str) -> None:
    logger = logging.getLogger("igris.smw")
    cycle_count = 0
    while True:
        try:
            snapshot = await take_snapshot(project_root)
            patterns = detect_patterns(snapshot)
            for detected in patterns:
                name = detected.pattern.name
                last = _SMW_COOLDOWN_PATTERNS.get(name, 0)
                if (detected.detected_at - last) < detected.pattern.cooldown_seconds:
                    continue
                _SMW_COOLDOWN_PATTERNS[name] = detected.detected_at
                d = diagnose(detected, project_root)
                if d.requires_llm:
                    try:
                        d = await diagnose_with_llm(detected, snapshot, project_root)
                    except Exception as _llm_exc:
                        logger.warning("SMW LLM diagnosis failed: %s", _llm_exc)
                actions_applied = []
                for action_name in d.recommended_actions:
                    result = await execute_action(action_name, tier=d.recommended_tier, dry_run=(d.confidence < 0.6), project_root=project_root, pattern_name=name, evidence=detected.evidence, actions_tried=actions_applied)
                    actions_applied.append(action_name)
                    logger.info("SMW: action %s => %s", action_name, result.success)
                await asyncio.sleep(1)
                still_active = any(p.pattern.name == name for p in detect_patterns(await take_snapshot(project_root)))
                outcome = "failed" if still_active else "resolved"
                incident = Incident(uuid.uuid4().hex, name, detected.detected_at, None if still_active else asyncio.get_running_loop().time(), d.root_cause, actions_applied, outcome, detected.evidence)
                record_incident(incident, project_root)
                if outcome == "resolved":
                    await teach_back(incident, project_root, outcome_label="positive")
                else:
                    # Issue #724 — teach_back on failed outcomes too (negative label)
                    await teach_back(incident, project_root, outcome_label="negative")
                    await execute_action("open_diagnostic_issue", tier=2, dry_run=False, project_root=project_root, pattern_name=name, evidence=detected.evidence, actions_tried=actions_applied)
            cycle_count += 1
            if cycle_count % 10 == 0:
                signals = run_all_detectors(project_root)
                for signal in signals:
                    logger.warning("SMW weak signal: %s - %s | action=%s", signal.name, signal.description, signal.recommended_action)
                    if signal.severity == "ACTION_REQUIRED":
                        await execute_action("open_diagnostic_issue", tier=2, dry_run=False, project_root=project_root, pattern_name=signal.name, evidence=signal.description, actions_tried=[])
                # Issue #521 — CodeHealthMonitor: proactive code quality scan
                try:
                    _chm = _get_code_health_monitor()(project_root, dry_run=False)
                    _health_report = await asyncio.to_thread(_chm.run, False)
                    if _health_report.findings or _health_report.errors:
                        logger.info(
                            "SMW code health: %d finding(s), %d issue(s) opened, %d skipped (anti-spam), %d error(s)",
                            len(_health_report.findings),
                            len(_health_report.issues_opened),
                            _health_report.issues_skipped,
                            len(_health_report.errors),
                        )
                    # Update API cache so GET /api/code-health/summary returns latest result
                    try:
                        from igris.api.routes.code_health import update_code_health_cache
                        update_code_health_cache(_health_report)
                    except Exception as _cache_exc:
                        logger.debug("code health cache update skipped: %s", _cache_exc)
                except Exception as _chm_exc:
                    logger.warning("SMW code health monitor error (non-fatal): %s", _chm_exc)

                # Issue #522 — OutcomeQualityTracker: update fix quality scores (24h interval)
                global _last_quality_run
                import time as _time_mod
                if (_time_mod.time() - _last_quality_run) >= _QUALITY_RUN_INTERVAL:
                    try:
                        from igris.core.outcome_quality_tracker import OutcomeQualityTracker
                        _oqt = OutcomeQualityTracker(project_root)
                        _qr = await asyncio.to_thread(_oqt.run)
                        logger.info(
                            "SMW quality tracker: %d updated, %d skipped, %d error(s)",
                            _qr.updated, _qr.skipped, len(_qr.errors),
                        )
                        _last_quality_run = _time_mod.time()
                    except Exception as _oqt_exc:
                        logger.warning("SMW quality tracker error (non-fatal): %s", _oqt_exc)

            try:
                reviewed = {r.pr_number for r in load_review_results(project_root)}
                out = await asyncio.to_thread(__import__("subprocess").run, ["gh", "pr", "list", "--json", "number,title,headRefName,files,statusCheckRollup"], capture_output=True, text=True, cwd=project_root)
                if out.returncode == 0:
                    prs = __import__("json").loads(out.stdout or "[]")
                    for pr in prs:
                        number = int(pr.get("number", 0))
                        if number in reviewed:
                            continue
                        rollup = pr.get("statusCheckRollup") or []
                        ci_green = bool(rollup) and all((c.get("conclusion") in {"SUCCESS", "NEUTRAL", "SKIPPED"}) for c in rollup if isinstance(c, dict))
                        if not ci_green:
                            continue
                        _diff_proc = await asyncio.to_thread(__import__("subprocess").run, ["gh", "pr", "diff", str(number)], capture_output=True, text=True, cwd=project_root)
                        _pr_diff = _diff_proc.stdout[:8000] if _diff_proc.returncode == 0 else ""
                        req = PRReviewRequest(
                            pr_number=number,
                            pr_title=pr.get("title", ""),
                            pr_diff=_pr_diff,
                            issue_description="",
                            changed_files=[f.get("path", "") for f in (pr.get("files") or []) if isinstance(f, dict)],
                            ci_passed=True,
                            run_id="smw",
                            last_failure_class="",
                            repair_cycles_used=0,
                            max_repair_cycles=1,
                            capability_signals={},
                        )
                        rr = await review_pr(req, project_root)
                        save_review_result(rr, project_root)
                        if rr.approved and rr.confidence >= _SMW_MERGE_CONFIDENCE:
                            # Issue #732 — only auto-merge above configurable threshold
                            logger.info("SMW auto-merging PR #%s (confidence=%.2f >= threshold=%.2f)", number, rr.confidence, _SMW_MERGE_CONFIDENCE)
                            await asyncio.to_thread(__import__("subprocess").run, ["gh", "pr", "merge", str(number), "--squash", "--delete-branch"], capture_output=True, text=True, cwd=project_root)
                        elif rr.approved and rr.confidence >= 0.5:
                            # Needs human review — open PR but do NOT auto-merge
                            logger.warning("SMW skipping auto-merge PR #%s: confidence %.2f below threshold %.2f — human review required", number, rr.confidence, _SMW_MERGE_CONFIDENCE)
                            await asyncio.to_thread(__import__("subprocess").run, ["gh", "pr", "comment", str(number), "--body", f"⚠️ SMW: auto-merge skipped (confidence={rr.confidence:.2f} < threshold={_SMW_MERGE_CONFIDENCE:.2f}). Human review required.\n\nSuggestion: {rr.suggestion}"], capture_output=True, text=True, cwd=project_root)
                        elif (not rr.approved) and rr.confidence > 0.7:
                            await asyncio.to_thread(__import__("subprocess").run, ["gh", "pr", "comment", str(number), "--body", f"SMW blocked merge: {rr.suggestion}\nConcerns: {rr.concerns}"], capture_output=True, text=True, cwd=project_root)
                            await execute_action("open_diagnostic_issue", tier=2, dry_run=False, project_root=project_root, pattern_name="pr_review_blocked", evidence=f"pr#{number}", actions_tried=[])
                        elif rr.tiebreaker_used and rr.confidence < 0.6:
                            await execute_action("open_diagnostic_issue", tier=2, dry_run=False, project_root=project_root, pattern_name="pr_review_discordance", evidence=f"pr#{number}", actions_tried=[])
            except Exception as exc:
                logger.warning("SMW PR review pass failed: %s", exc)
        except Exception as exc:
            logger.warning("SMW error: %s", exc)
        await asyncio.sleep(_SMW_POLL_SECONDS)


def start_smw(project_root: str) -> asyncio.Task:
    return asyncio.create_task(_smw_loop(project_root))
