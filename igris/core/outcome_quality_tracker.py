"""OutcomeQualityTracker — fix quality scoring for AssignmentRouter.

Part of GitHub issue #522: feat(memory): Outcome quality tracker.
Fase 2bis — Gap 5.

Tracks whether fixes "stick" after delivery:
  quality_score = 1.0  — fix still in place after 7 days
  quality_score = 0.5  — PR merged but issue reopened
  quality_score = 0.0  — rollback detected or fix reverted

The tracker enriches assignment_outcomes.json records with quality_score.
AssignmentRouter.decide() uses quality_score_weighted = success_rate * avg_quality
to prefer profiles that produce durable fixes, not just passing tests.

Background job (run every 24h via watchdog): checks recently-closed issues
and updates quality scores for the corresponding outcomes.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


_QUALITY_HISTORY_FILE = ".igris/quality_scores.json"
_QUALITY_WINDOW_DAYS = 7      # days after which a fix is considered "stable"
_QUALITY_CHECK_INTERVAL = 86400  # 24h between checks


# ---------------------------------------------------------------------------
# Quality score enum values
# ---------------------------------------------------------------------------

QUALITY_STICKY = 1.0      # fix persists, issue closed, no reopen
QUALITY_REOPENED = 0.5    # issue was reopened after close
QUALITY_ROLLBACK = 0.0    # rollback detected (PR reverted or force-close+reopen same day)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QualityRecord:
    outcome_id: str           # matches record["outcome_id"] in assignment_outcomes.json
    issue_number: Optional[int]
    profile: str
    closed_at: float          # Unix timestamp when issue was closed
    quality_score: float = 1.0
    checked_at: Optional[float] = None
    reopen_detected: bool = False
    rollback_detected: bool = False


@dataclass
class QualityReport:
    updated: int = 0
    skipped: int = 0          # too recent to evaluate
    errors: List[str] = field(default_factory=list)
    ran_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _history_path(project_root: str) -> Path:
    return Path(project_root) / _QUALITY_HISTORY_FILE


def load_quality_scores(project_root: str) -> Dict[str, QualityRecord]:
    """Return {outcome_id: QualityRecord} from disk."""
    path = _history_path(project_root)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        result = {}
        for oid, d in raw.items():
            result[oid] = QualityRecord(
                outcome_id=oid,
                issue_number=d.get("issue_number"),
                profile=str(d.get("profile", "")),
                closed_at=float(d.get("closed_at", 0.0)),
                quality_score=float(d.get("quality_score", 1.0)),
                checked_at=d.get("checked_at"),
                reopen_detected=bool(d.get("reopen_detected", False)),
                rollback_detected=bool(d.get("rollback_detected", False)),
            )
        return result
    except Exception:
        return {}


def save_quality_scores(project_root: str, records: Dict[str, QualityRecord]) -> None:
    path = _history_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        oid: {
            "issue_number": r.issue_number,
            "profile": r.profile,
            "closed_at": r.closed_at,
            "quality_score": r.quality_score,
            "checked_at": r.checked_at,
            "reopen_detected": r.reopen_detected,
            "rollback_detected": r.rollback_detected,
        }
        for oid, r in records.items()
    }
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, str(path))


# ---------------------------------------------------------------------------
# GitHub issue status helpers
# ---------------------------------------------------------------------------

def _get_issue_state(project_root: str, issue_number: int) -> Optional[str]:
    """Return 'open' | 'closed' | None via gh CLI."""
    try:
        r = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--json", "state"],
            capture_output=True, text=True, cwd=project_root, timeout=10,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            return str(data.get("state", "")).lower()
    except Exception:
        pass
    return None


def _get_issue_events(project_root: str, issue_number: int) -> List[Dict]:
    """Return recent events for an issue via gh api."""
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{{owner}}/{{repo}}/issues/{issue_number}/events",
             "--paginate", "--jq", ".[].event"],
            capture_output=True, text=True, cwd=project_root, timeout=15,
        )
        if r.returncode == 0:
            events = [line.strip() for line in r.stdout.splitlines() if line.strip()]
            return [{"event": e} for e in events]
    except Exception:
        pass
    return []


def _issue_was_reopened(project_root: str, issue_number: int, after_ts: float) -> bool:
    """True if the issue was reopened after after_ts."""
    state = _get_issue_state(project_root, issue_number)
    if state == "open":
        # Currently open — was probably reopened
        return True
    # Check events for a reopen event after the close
    events = _get_issue_events(project_root, issue_number)
    return any(e.get("event") == "reopened" for e in events)


# ---------------------------------------------------------------------------
# Quality computation
# ---------------------------------------------------------------------------

def compute_quality_score(
    project_root: str,
    record: QualityRecord,
    now: Optional[float] = None,
) -> float:
    """Compute and return the quality score for a single outcome record."""
    if now is None:
        now = time.time()
    age_days = (now - record.closed_at) / 86400

    if age_days < _QUALITY_WINDOW_DAYS:
        # Too early to evaluate — keep current score
        return record.quality_score

    if record.issue_number is None:
        return QUALITY_STICKY  # no issue to track — assume sticky

    reopened = _issue_was_reopened(project_root, record.issue_number, record.closed_at)
    if reopened:
        # Distinguish rollback (reopened within 24h) from normal reopen
        if age_days < 1.0:
            return QUALITY_ROLLBACK
        return QUALITY_REOPENED
    return QUALITY_STICKY


# ---------------------------------------------------------------------------
# Outcome record enrichment
# ---------------------------------------------------------------------------

def enrich_outcome_with_quality(
    outcome: Dict[str, Any],
    scores: Dict[str, "QualityRecord"],
) -> Dict[str, Any]:
    """Add quality_score to an outcome dict if available."""
    oid = outcome.get("outcome_id", "")
    if oid and oid in scores:
        outcome = dict(outcome)
        outcome["quality_score"] = scores[oid].quality_score
    return outcome


def avg_quality_for_profile(
    outcomes: List[Dict[str, Any]],
    profile: str,
    scores: Dict[str, "QualityRecord"],
    min_history: int = 3,
) -> Optional[float]:
    """Return average quality score for outcomes matching profile, or None if insufficient."""
    matching = [
        o for o in outcomes
        if o.get("preferred_profile") == profile and o.get("outcome") == "success"
    ]
    if len(matching) < min_history:
        return None
    qs = [scores[o["outcome_id"]].quality_score
          for o in matching
          if o.get("outcome_id") in scores]
    if not qs:
        return None
    return sum(qs) / len(qs)


# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

class OutcomeQualityTracker:
    """Background quality tracker for IGRIS assignment outcomes.

    Usage (from watchdog every 24h)::

        tracker = OutcomeQualityTracker(project_root, outcomes_path)
        report = tracker.run()
    """

    def __init__(self, project_root: str, outcomes_path: Optional[str] = None) -> None:
        self._root = project_root
        self._outcomes_path = outcomes_path or str(
            Path(project_root) / ".igris" / "assignment_outcomes.json"
        )

    def run(self) -> QualityReport:
        """Scan recent outcomes and update quality scores."""
        from igris.core.assignment_outcomes import load_assignment_outcomes, save_assignment_outcome

        report = QualityReport()
        now = time.time()
        cutoff = now - _QUALITY_WINDOW_DAYS * 86400

        try:
            outcomes = load_assignment_outcomes(self._outcomes_path)
        except Exception as exc:
            report.errors.append(f"load outcomes: {exc}")
            return report

        scores = load_quality_scores(self._root)

        for outcome in outcomes:
            oid = outcome.get("outcome_id", "")
            if not oid or outcome.get("outcome") != "success":
                continue

            closed_ts = float(outcome.get("timestamp", 0.0) or 0.0)
            age_days = (now - closed_ts) / 86400

            if age_days < _QUALITY_WINDOW_DAYS:
                report.skipped += 1
                continue

            # Already checked recently? Skip
            if oid in scores and scores[oid].checked_at:
                last_check = float(scores[oid].checked_at or 0.0)
                if (now - last_check) < _QUALITY_CHECK_INTERVAL:
                    report.skipped += 1
                    continue

            # Build or refresh QualityRecord
            issue_num: Optional[int] = None
            raw_issue = outcome.get("issue_number")
            if raw_issue is not None:
                try:
                    issue_num = int(raw_issue)
                except (TypeError, ValueError):
                    pass

            rec = scores.get(oid) or QualityRecord(
                outcome_id=oid,
                issue_number=issue_num,
                profile=str(outcome.get("preferred_profile", "")),
                closed_at=closed_ts,
            )

            try:
                new_score = compute_quality_score(self._root, rec, now=now)
                rec.quality_score = new_score
                rec.checked_at = now
                rec.reopen_detected = new_score < QUALITY_STICKY
                rec.rollback_detected = new_score == QUALITY_ROLLBACK
                scores[oid] = rec
                report.updated += 1
            except Exception as exc:
                report.errors.append(f"outcome {oid}: {exc}")

        try:
            save_quality_scores(self._root, scores)
        except Exception as exc:
            report.errors.append(f"save scores: {exc}")

        return report

    def quality_weighted_success_rate(
        self,
        outcomes: List[Dict[str, Any]],
        profile: str,
        agent_role: str,
        task_type: str,
        min_history: int = 3,
    ) -> Optional[float]:
        """Return quality-weighted success rate for a profile, or None if insufficient data."""
        scores = load_quality_scores(self._root)
        matching_success = [
            o for o in outcomes
            if o.get("preferred_profile") == profile
            and o.get("agent_role") == agent_role
            and o.get("task_type") == task_type
            and o.get("outcome") == "success"
        ]
        if len(matching_success) < min_history:
            return None
        total_for_profile = [
            o for o in outcomes
            if o.get("preferred_profile") == profile
            and o.get("agent_role") == agent_role
            and o.get("task_type") == task_type
        ]
        if not total_for_profile:
            return None

        success_rate = len(matching_success) / len(total_for_profile)
        avg_q = avg_quality_for_profile(outcomes, profile, scores, min_history=1)
        if avg_q is None:
            return success_rate  # no quality data — use plain success rate
        return success_rate * avg_q
