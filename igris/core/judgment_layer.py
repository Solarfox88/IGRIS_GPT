"""
Judgment Layer — Layer 5 of the Interlocutor-Aware system (issue #526).

Advisory engine: even when authorized, IGRIS reasons about action opportuneness.
Never blocks (advisory only). Admin=non-blocking, trusted=confirmation required.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Advisory:
    """Advisory produced by the JudgmentLayer."""
    action_type: str
    target_resource: str
    should_proceed: bool
    confidence: float
    reason: str
    message: str
    requires_confirmation: bool = False
    blocking: bool = False  # always False


@dataclass
class OperationalContext:
    """Snapshot of the current operational state."""
    active_backups: List[Dict[str, Any]] = field(default_factory=list)
    ci_running: bool = False
    open_prs: List[str] = field(default_factory=list)
    hour_of_day: Optional[int] = None
    run_in_progress: bool = False
    custom_facts: Dict[str, Any] = field(default_factory=dict)


class JudgmentLayer:
    """Layer 5: advisory engine for context-aware action judgment."""

    _SENSITIVE_ACTIONS = frozenset([
        "restart_server", "restart", "shutdown", "deploy", "merge",
        "delete_branch", "force_push", "drop_database", "wipe_storage",
        "reset_hard", "terminate_process", "remove_file",
    ])

    def advise(
        self,
        action_type: str,
        target_resource: str,
        context: OperationalContext,
        trust_level: str = "trusted",
    ) -> Advisory:
        if action_type not in self._SENSITIVE_ACTIONS:
            return Advisory(
                action_type=action_type,
                target_resource=target_resource,
                should_proceed=True,
                confidence=0.95,
                reason="non_sensitive",
                message="Action is non-sensitive. No advisory needed.",
                requires_confirmation=False,
            )

        warnings: List[str] = []
        requires_confirm = trust_level in ("trusted", "limited")

        for bk in context.active_backups:
            name = bk.get("name", "backup")
            pct = int(bk.get("pct", 0))
            eta_sec = int(bk.get("eta_sec", 0))
            eta_min = round(eta_sec / 60, 1) if eta_sec else "?"
            if pct < 100:
                warnings.append(
                    f"Backup '{name}' is active ({pct}%, ETA ~{eta_min} min). "
                    "Proceeding now may corrupt the backup."
                )

        if context.ci_running:
            warnings.append(
                f"CI is currently running. "
                f"Action on '{target_resource}' may affect CI results."
            )

        if context.open_prs and action_type in ("delete_branch", "merge", "force_push"):
            pr_list = ", ".join(context.open_prs[:3])
            warnings.append(f"Open PR(s) exist: {pr_list}. Verify before proceeding.")

        hour = context.hour_of_day
        if hour is None:
            hour = time.localtime().tm_hour
        if hour < 6 or hour >= 23:
            warnings.append(
                f"Current time is {hour:02d}:xx. Unusual hour for {action_type}. "
                "Are you sure you want to proceed now?"
            )

        if context.run_in_progress:
            warnings.append(
                f"A supervisor run is currently in progress. "
                f"Action on '{target_resource}' may interfere."
            )

        if not warnings:
            return Advisory(
                action_type=action_type,
                target_resource=target_resource,
                should_proceed=True,
                confidence=0.9,
                reason="no_concerns",
                message="No operational concerns detected. Proceeding.",
                requires_confirmation=False,
            )

        advisory_msg = f"Advisory for '{action_type}' on '{target_resource}':\n"
        for i, w in enumerate(warnings, 1):
            advisory_msg += f"  {i}. {w}\n"
        if requires_confirm:
            advisory_msg += "\nPlease confirm to proceed, or abort."
        else:
            advisory_msg += "\nProceeding (admin — advisory noted)."

        return Advisory(
            action_type=action_type,
            target_resource=target_resource,
            should_proceed=True,
            confidence=0.7,
            reason="advisory_issued",
            message=advisory_msg.strip(),
            requires_confirmation=requires_confirm,
            blocking=False,
        )

    def persist_advisory_outcome(
        self,
        advisory: Advisory,
        outcome: str,
        project_root: str,
    ) -> None:
        try:
            from igris.core.memory_graph import MemoryGraph
            mg = MemoryGraph(project_root)
            mg.add_node(
                "lesson",
                {
                    "source": "judgment_layer",
                    "action_type": advisory.action_type,
                    "target_resource": advisory.target_resource,
                    "advisory_reason": advisory.reason,
                    "advisory_message": advisory.message[:200],
                    "outcome": outcome,
                    "ts": time.time(),
                },
                confidence=0.65,
            )
        except Exception:
            pass
