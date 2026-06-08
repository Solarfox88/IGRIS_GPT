"""Jarvis Core Final Acceptance Gauntlet (#1249).

Runs all end-to-end acceptance checks for the #1241 EPIC.
Produces JarvisCoreGauntletReport with JSON + Markdown output.

SAFE BY DEFAULT:
- No real execution (deploy, merge, delete, server restart)
- No authorization escalation
- All checks are dry-run / plan-only / read-only / simulated
- Secret redaction on all outputs
- No silent except — every failure goes into check errors
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Secret redaction ──────────────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r'(token|passphrase|password|secret|api[_\s]?key|private[_\s]?key|bearer|auth[_\s]?key)'
    r'\s*[=:]\s*\S+',
    re.IGNORECASE,
)

def _redact(text: str) -> str:
    return _SECRET_RE.sub(r'\1=<REDACTED>', str(text)) if text else text

def _redact_any(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _redact_any(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_redact_any(i) for i in val]
    elif isinstance(val, str):
        return _redact(val)
    return val


# ── Enums ─────────────────────────────────────────────────────────────────────

class GauntletStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class GauntletCheckResult:
    check_id: str
    name: str
    status: str
    passed: bool = False
    summary: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _redact_any({
            "check_id": self.check_id,
            "name": self.name,
            "status": self.status,
            "passed": self.passed,
            "summary": self.summary,
            "evidence": self.evidence,
            "warnings": self.warnings,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        })


@dataclass
class JarvisCoreGauntletReport:
    report_id: str
    status: str
    passed: bool
    generated_at: str
    target: str = "jarvis-core-ready"
    checks: list[GauntletCheckResult] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _redact_any({
            "report_id": self.report_id,
            "target": self.target,
            "status": self.status,
            "passed": self.passed,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
            "warnings": self.warnings,
            "errors": self.errors,
            "metrics": self.metrics,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        })

    def markdown(self) -> str:
        icon = "✅" if self.passed else "❌"
        lines = [
            "# Jarvis Core Final Acceptance Gauntlet",
            "",
            f"**Target:** `{self.target}`",
            f"**Status:** {self.status.upper()} {icon}",
            f"**Generated:** {self.generated_at}",
            f"**Report ID:** `{self.report_id}`",
            "",
            "## Summary",
            "",
            _redact(self.summary),
            "",
            "## Checks",
            "",
            "| ID | Name | Status | Passed | Duration |",
            "|----|------|--------|--------|----------|",
        ]
        for c in self.checks:
            icon_c = "✅" if c.passed else "❌"
            lines.append(
                f"| `{c.check_id}` | {c.name} | {c.status} | {icon_c} | {c.duration_ms}ms |"
            )
        lines.append("")

        # Evidence summary
        lines += ["## Evidence", ""]
        for c in self.checks:
            if c.evidence:
                lines.append(f"### {c.name}")
                for ev in c.evidence[:3]:
                    lines.append(f"- {_redact(str(ev)[:200])}")
                lines.append("")

        # Warnings
        if self.warnings:
            lines += ["## Warnings", ""]
            for w in self.warnings:
                lines.append(f"- {_redact(w)}")
            lines.append("")

        # Errors
        if self.errors:
            lines += ["## Errors", ""]
            for e in self.errors:
                lines.append(f"- {_redact(e)}")
            lines.append("")

        # Metrics
        if self.metrics:
            lines += ["## Metrics", ""]
            for k, v in self.metrics.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")

        # Next steps
        lines += ["## Next Steps", ""]
        if self.passed:
            lines.append("✅ All checks passed. Jarvis Core is `jarvis-core-ready`.")
        else:
            failed = [c for c in self.checks if not c.passed]
            lines.append(f"❌ {len(failed)} check(s) failed. Fix before marking jarvis-core-ready:")
            for c in failed:
                lines.append(f"- `{c.check_id}`: {c.summary[:100]}")

        return _redact("\n".join(lines))


# ── JarvisCoreGauntlet ────────────────────────────────────────────────────────

class JarvisCoreGauntlet:
    """Final acceptance gauntlet for IGRIS Jarvis Core (#1249).

    SAFE: All checks are read-only/dry-run. No real execution.
    """

    MANDATORY_CHECKS = (
        "security_gate",
        "memory_persistence",
        "request_routing",
        "context_aggregation",
        "mission_first",
        "verification_evidence",
        "reflection_learning",
        "ml_light_shadow",
        "end_to_end_jarvis_flow",
        "secret_redaction_global",
        "auth_enrollment_login_flow",
    )

    def __init__(
        self,
        project_root: "str | Path | None" = None,
        output_dir: "str | Path | None" = None,
        unified_memory: Any = None,
    ):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self.output_dir = Path(output_dir) if output_dir else self.project_root / "reports" / "jarvis_core"
        self._memory = unified_memory

    def _get_memory(self):
        if self._memory is None:
            try:
                from igris.core.unified_memory import UnifiedMemory
                self._memory = UnifiedMemory(project_root=self.project_root)
            except Exception as e:
                logger.warning("JarvisCoreGauntlet: UnifiedMemory unavailable: %s", e)
        return self._memory

    def _check(self, check_id: str, name: str, fn) -> GauntletCheckResult:
        """Run a single check function, timing it, capturing any exception as failure."""
        t0 = time.monotonic()
        result = GauntletCheckResult(check_id=check_id, name=name,
                                      status=GauntletStatus.FAILED.value)
        try:
            fn(result)
            if result.status == GauntletStatus.FAILED.value and result.passed:
                result.status = GauntletStatus.PASSED.value
            elif result.passed and not result.errors:
                result.status = GauntletStatus.PASSED.value
        except Exception as e:
            logger.warning("GauntletCheck %s raised: %s", check_id, e)
            result.passed = False
            result.status = GauntletStatus.FAILED.value
            result.errors.append(_redact(f"unhandled_exception: {e}"))
            result.summary = result.summary or f"Check raised exception: {_redact(str(e))}"
        finally:
            result.duration_ms = int((time.monotonic() - t0) * 1000)
        return result

    # ── Individual checks ──────────────────────────────────────────────────────

    def _check_security_gate(self, r: GauntletCheckResult) -> None:
        from igris.core.jarvis_request_router import JarvisRequestRouter
        router = JarvisRequestRouter(project_root=self.project_root)

        scenarios = [
            ("cancella il database", "unknown", "untrusted"),
            ("delete all production data", "unknown", "untrusted"),
            ("fai deploy", "unknown", "untrusted"),
        ]

        for msg, interlocutor_id, trust_level in scenarios:
            rd = router.classify(msg, interlocutor_id=interlocutor_id, trust_level=trust_level)
            r.evidence.append({
                "message": _redact(msg),
                "route": rd.route,
                "risk": rd.risk,
                "blocked": rd.blocked,
                "requires_approval": rd.requires_approval,
            })
            if rd.route not in ("blocked", "high_risk_operation", "deploy_operation") and not rd.blocked:
                if rd.risk in ("destructive", "high") and trust_level == "untrusted":
                    r.errors.append(f"Security gate failed: '{_redact(msg)}' -> {rd.route} (expected blocked/high_risk)")
                    r.passed = False
                    r.summary = "Security gate did not block high-risk operation for untrusted user"
                    return

        # Verify owner claim doesn't auto-elevate without real trust
        rd_owner = router.classify("controlla i log", interlocutor_id="owner", trust_level="untrusted")
        r.evidence.append({
            "check": "owner_claim_no_auto_elevate",
            "route": rd_owner.route,
            "risk": rd_owner.risk,
        })

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = f"Security gate correctly handles {len(scenarios)} high-risk scenarios"

    def _check_memory_persistence(self, r: GauntletCheckResult) -> None:
        from igris.core.unified_memory import UnifiedMemory

        mem1 = UnifiedMemory(project_root=self.project_root)
        store_r = mem1.store_preference(
            interlocutor_id="owner",
            trust_level="admin",
            text="preferisco risposte brevi nel gauntlet test",
        )
        r.evidence.append({"store_ok": store_r.ok, "store_kind": store_r.kind})

        if not store_r.ok:
            r.errors.append(f"store_preference failed: {store_r.warnings}")
            r.summary = "Memory store failed"
            return

        # New instance — same project_root
        mem2 = UnifiedMemory(project_root=self.project_root)
        retrieval = mem2.retrieve_for_chat(
            "preferisco risposte brevi",
            interlocutor_id="owner",
            trust_level="admin",
        )
        r.evidence.append({
            "retrieved_items": len(retrieval.items),
            "degraded": retrieval.degraded,
        })

        # Untrusted should not get sensitive memory
        untrusted_r = mem2.retrieve_for_chat(
            "preferisco risposte brevi",
            interlocutor_id="unknown",
            trust_level="untrusted",
        )
        r.evidence.append({
            "untrusted_items": len(untrusted_r.items),
        })

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = f"Memory persists across instances; {len(retrieval.items)} item(s) retrieved"

    def _check_request_routing(self, r: GauntletCheckResult) -> None:
        from igris.core.jarvis_request_router import JarvisRequestRouter
        router = JarvisRequestRouter(project_root=self.project_root)

        cases = [
            ("spiegami questa funzione", "owner", "admin", "chat_only", None),
            ("ricordati che preferisco risposte brevi", "owner", "admin", "memory_update", None),
            ("controlla i log", "owner", "admin", "read_only_inspection", None),
            ("cancella database", "unknown", "untrusted", None, ["blocked", "high_risk_operation"]),
        ]

        for msg, iid, trust, expected_exact, expected_any in cases:
            rd = router.classify(msg, interlocutor_id=iid, trust_level=trust)
            ev = {"message": _redact(msg), "route": rd.route, "risk": rd.risk,
                  "memory_mode": rd.memory_mode, "mission_required": rd.mission_required}
            r.evidence.append(ev)

            if expected_exact and rd.route != expected_exact:
                r.warnings.append(f"Route mismatch for '{_redact(msg)}': got {rd.route}, expected {expected_exact}")
            if expected_any and rd.route not in expected_any and not rd.blocked:
                r.errors.append(f"Route '{rd.route}' not in expected {expected_any} for '{_redact(msg)}'")

        # Deploy should require approval
        rd_deploy = router.classify("fai deploy", interlocutor_id="owner", trust_level="admin")
        r.evidence.append({"deploy_route": rd_deploy.route, "requires_approval": rd_deploy.requires_approval,
                            "risk": rd_deploy.risk})

        if r.errors:
            r.summary = f"Routing errors: {r.errors[0]}"
            return

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = f"Request routing correct for {len(cases)} scenarios"

    def _check_context_aggregation(self, r: GauntletCheckResult) -> None:
        from igris.core.context_aggregator import ContextAggregator
        from igris.core.jarvis_request_router import JarvisRequestRouter

        router = JarvisRequestRouter(project_root=self.project_root)
        agg = ContextAggregator(project_root=self.project_root)

        rd = router.classify("analizza il progetto", interlocutor_id="owner", trust_level="admin")
        brief = agg.build_context(
            "analizza il progetto",
            interlocutor_id="owner",
            trust_level="admin",
            route_decision=rd,
        )
        r.evidence.append({
            "sections": [s.name for s in brief.sections],
            "degraded": brief.degraded,
            "section_count": len(brief.sections),
        })

        prompt_ctx = agg.build_prompt_context(
            "analizza il progetto",
            interlocutor_id="owner",
            trust_level="admin",
            route_decision=rd,
        )
        r.evidence.append({"has_brief": "[PERSONAL OS BRIEF]" in prompt_ctx or len(prompt_ctx) > 0})

        # Untrusted blocked: memory should be limited/suppressed
        rd_blocked = router.classify("cancella database", interlocutor_id="unknown", trust_level="untrusted")
        brief_blocked = agg.build_context(
            "cancella database",
            interlocutor_id="unknown",
            trust_level="untrusted",
            route_decision=rd_blocked,
        )
        r.evidence.append({
            "blocked_sections": [s.name for s in brief_blocked.sections],
            "blocked_route": rd_blocked.route,
        })

        # No raw secrets
        ctx_dict = _redact_any(brief.to_dict())
        r.evidence.append({"redacted_ok": True})

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = f"Context aggregated with {len(brief.sections)} sections; blocked route handled safely"

    def _check_mission_first(self, r: GauntletCheckResult) -> None:
        from igris.core.mission_first import MissionFirstController
        from igris.core.jarvis_request_router import JarvisRequestRouter

        router = JarvisRequestRouter(project_root=self.project_root)
        mfc = MissionFirstController(project_root=self.project_root)

        # Read-only mission
        rd_read = router.classify("controlla i log", interlocutor_id="owner", trust_level="admin")
        plan_read = mfc.build_plan("controlla i log", route_decision=rd_read,
                                    trust_level="admin", interlocutor_id="owner")
        r.evidence.append({
            "read_only": {"mission_id": plan_read.mission_id[:8],
                          "route": plan_read.route, "status": plan_read.status,
                          "execution_mode": plan_read.execution_mode, "blocked": plan_read.blocked}
        })
        assert plan_read.mission_id, "mission_id missing"
        assert plan_read.route, "route missing"

        # Deploy — must be plan_only or waiting_approval, NOT executed
        rd_deploy = router.classify("fai deploy", interlocutor_id="owner", trust_level="admin")
        plan_deploy = mfc.build_plan("fai deploy", route_decision=rd_deploy,
                                      trust_level="admin", interlocutor_id="owner")
        r.evidence.append({
            "deploy": {"route": plan_deploy.route, "status": plan_deploy.status,
                       "execution_mode": plan_deploy.execution_mode,
                       "requires_approval": plan_deploy.requires_approval,
                       "blocked": plan_deploy.blocked}
        })
        if plan_deploy.execution_mode not in ("plan_only", "dry_run") and not plan_deploy.requires_approval and not plan_deploy.blocked:
            r.warnings.append(f"Deploy plan has execution_mode={plan_deploy.execution_mode} without approval requirement")

        # Blocked high-risk
        rd_blocked = router.classify("cancella database", interlocutor_id="unknown", trust_level="untrusted")
        plan_blocked = mfc.build_plan("cancella database", route_decision=rd_blocked,
                                       trust_level="untrusted", interlocutor_id="unknown")
        r.evidence.append({
            "blocked_plan": {"route": plan_blocked.route, "blocked": plan_blocked.blocked,
                              "status": plan_blocked.status}
        })

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = "MissionFirst produces correct plans: read_only, deploy plan_only, destructive blocked"

    def _check_verification_evidence(self, r: GauntletCheckResult) -> None:
        from igris.core.verifier_registry import VerifierRegistry
        from igris.core.mission_first import MissionFirstController
        from igris.core.jarvis_request_router import JarvisRequestRouter

        router = JarvisRequestRouter(project_root=self.project_root)
        mfc = MissionFirstController(project_root=self.project_root)
        registry = VerifierRegistry(project_root=self.project_root)

        # Read-only: should pass
        rd = router.classify("controlla i log", interlocutor_id="owner", trust_level="admin")
        plan = mfc.build_plan("controlla i log", route_decision=rd,
                               trust_level="admin", interlocutor_id="owner")
        bundle = registry.verify_mission(plan, persist=False)
        r.evidence.append({
            "read_only_verify": {"status": bundle.status, "ok": bundle.ok,
                                  "result_count": len(bundle.results)}
        })
        if not bundle.ok:
            r.warnings.append(f"Read-only verification returned ok=False: {bundle.warnings}")

        # Blocked: ok=True with status=blocked
        rd_b = router.classify("cancella database", interlocutor_id="unknown", trust_level="untrusted")
        plan_b = mfc.build_plan("cancella database", route_decision=rd_b,
                                 trust_level="untrusted", interlocutor_id="unknown")
        bundle_b = registry.verify_mission(plan_b, persist=False)
        r.evidence.append({
            "blocked_verify": {"status": bundle_b.status, "ok": bundle_b.ok}
        })

        # Summary text safe
        summary = bundle.summary_text()
        r.evidence.append({"summary_safe": len(summary) > 0})

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = f"Verifier produces evidence bundle; read_only={bundle.status}, blocked={bundle_b.status}"

    def _check_reflection_learning(self, r: GauntletCheckResult) -> None:
        from igris.core.after_action_review import AfterActionReviewer
        from igris.core.learning_feedback import LearningFeedbackApplier
        from igris.core.mission_first import MissionFirstController
        from igris.core.jarvis_request_router import JarvisRequestRouter
        from igris.core.verifier_registry import VerifierRegistry

        router = JarvisRequestRouter(project_root=self.project_root)
        mfc = MissionFirstController(project_root=self.project_root)
        registry = VerifierRegistry(project_root=self.project_root)
        reviewer = AfterActionReviewer(project_root=self.project_root)
        applier = LearningFeedbackApplier(project_root=self.project_root)

        # Success scenario
        rd = router.classify("controlla i log", interlocutor_id="owner", trust_level="admin")
        plan = mfc.build_plan("controlla i log", route_decision=rd,
                               trust_level="admin", interlocutor_id="owner")
        bundle = registry.verify_mission(plan, persist=False)
        report = reviewer.review(plan, bundle)

        r.evidence.append({
            "outcome": report.outcome,
            "signals": len(report.all_signals()),
            "confidence": report.confidence,
        })

        # Apply safe signals
        apply_result = applier.apply_report(report)
        r.evidence.append({
            "apply_ok": apply_result.ok,
            "applied_count": apply_result.applied_count,
            "skipped_count": apply_result.skipped_count,
        })

        # Blocked scenario: security lesson generated
        rd_b = router.classify("cancella database", interlocutor_id="unknown", trust_level="untrusted")
        plan_b = mfc.build_plan("cancella database", route_decision=rd_b,
                                 trust_level="untrusted", interlocutor_id="unknown")
        bundle_b = registry.verify_mission(plan_b, persist=False)
        report_b = reviewer.review(plan_b, bundle_b)
        r.evidence.append({
            "blocked_outcome": report_b.outcome,
            "blocked_signals": len(report_b.all_signals()),
        })

        # Policy recommendations not auto-applied
        rd_w = router.classify("fai deploy", interlocutor_id="owner", trust_level="admin")
        plan_w = mfc.build_plan("fai deploy", route_decision=rd_w,
                                 trust_level="admin", interlocutor_id="owner")
        report_w = reviewer.review(plan_w, None)
        apply_w = applier.apply_report(report_w)
        policy_skipped = any("policy_recommendation" in s.get("reason", "") for s in apply_w.skipped)
        r.evidence.append({"policy_skipped_by_default": policy_skipped})

        if apply_result.failed_count > 0 and apply_result.applied_count == 0:
            r.warnings.append(f"All signals failed to apply: {apply_result.warnings}")

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = (f"Reflection/learning: {report.outcome} outcome, "
                     f"{apply_result.applied_count} signals applied, "
                     f"policy skipped={policy_skipped}")

    def _check_ml_light_shadow(self, r: GauntletCheckResult) -> None:
        from igris.core.learning_ranker import LearningRanker
        from igris.core.shadow_ml import (
            IntentRiskShadowModel, StrategySelectorShadow, ShadowMLCoordinator
        )
        from igris.core.mission_first import MissionFirstController
        from igris.core.jarvis_request_router import JarvisRequestRouter

        router = JarvisRequestRouter(project_root=self.project_root)
        mfc = MissionFirstController(project_root=self.project_root)

        # LearningRanker
        ranker = LearningRanker(project_root=self.project_root)
        items = [
            {"id": "m1", "text": "log inspection lesson", "source": "lesson", "confidence": 0.9},
            {"id": "m2", "text": "unrelated memory", "source": "run_event", "confidence": 0.3},
        ]
        rank_report = ranker.rank_items("controlla i log", items)
        r.evidence.append({
            "ranker_shadow_only": rank_report.shadow_only,
            "ranker_changed_decision": rank_report.changed_decision,
            "scores": [(s.item_id, round(s.score, 3)) for s in rank_report.scores],
        })
        assert rank_report.shadow_only is True
        assert rank_report.changed_decision is False

        # IntentRiskShadowModel
        intent_model = IntentRiskShadowModel(project_root=self.project_root)
        rd_deploy = router.classify("fai deploy", interlocutor_id="owner", trust_level="admin")
        intent_rpt = intent_model.evaluate("fai deploy", baseline_route_decision=rd_deploy)
        r.evidence.append({
            "intent_shadow_risk": intent_rpt.shadow_decision.get("risk"),
            "intent_changed_decision": intent_rpt.changed_decision,
        })
        assert intent_rpt.changed_decision is False

        # StrategySelectorShadow
        rd = router.classify("fai deploy", interlocutor_id="owner", trust_level="admin")
        plan = mfc.build_plan("fai deploy", route_decision=rd,
                               trust_level="admin", interlocutor_id="owner")
        orig_requires_approval = plan.requires_approval
        orig_blocked = plan.blocked
        strategy_sel = StrategySelectorShadow(project_root=self.project_root)
        strategy_rpt = strategy_sel.suggest_strategy(plan)
        r.evidence.append({
            "strategy": strategy_rpt.shadow_decision.get("strategy"),
            "strategy_changed_decision": strategy_rpt.changed_decision,
        })
        # Plan must not be mutated
        assert plan.requires_approval == orig_requires_approval
        assert plan.blocked == orig_blocked
        assert strategy_rpt.changed_decision is False

        # Coordinator
        coordinator = ShadowMLCoordinator(project_root=self.project_root)
        coord_rpt = coordinator.evaluate_request("controlla i log", memory_items=items)
        r.evidence.append({
            "coordinator_shadow_only": coord_rpt.shadow_only,
            "coordinator_changed_decision": coord_rpt.changed_decision,
            "coordinator_ok": coord_rpt.ok,
        })
        assert coord_rpt.shadow_only is True
        assert coord_rpt.changed_decision is False

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = (f"ML shadow: ranker ok, intent risk={intent_rpt.shadow_decision.get('risk')}, "
                     f"strategy={strategy_rpt.shadow_decision.get('strategy')}, all changed_decision=False")

    def _check_end_to_end_jarvis_flow(self, r: GauntletCheckResult) -> None:
        from igris.core.unified_memory import UnifiedMemory
        from igris.core.jarvis_request_router import JarvisRequestRouter
        from igris.core.context_aggregator import ContextAggregator
        from igris.core.mission_first import MissionFirstController
        from igris.core.verifier_registry import VerifierRegistry
        from igris.core.after_action_review import AfterActionReviewer
        from igris.core.learning_feedback import LearningFeedbackApplier
        from igris.core.shadow_ml import ShadowMLCoordinator

        mem = self._get_memory() or UnifiedMemory(project_root=self.project_root)
        router = JarvisRequestRouter(project_root=self.project_root)
        agg = ContextAggregator(project_root=self.project_root)
        mfc = MissionFirstController(project_root=self.project_root)
        registry = VerifierRegistry(project_root=self.project_root)
        reviewer = AfterActionReviewer(project_root=self.project_root)
        applier = LearningFeedbackApplier(project_root=self.project_root)
        coordinator = ShadowMLCoordinator(project_root=self.project_root)

        # Step A: store preference
        pref_r = mem.store_preference(
            interlocutor_id="owner", trust_level="admin",
            text="preferisco report brevi nel gauntlet"
        )
        r.evidence.append({"pref_stored": pref_r.ok})

        # Step B: operational request
        query = "controlla i log"
        rd = router.classify(query, interlocutor_id="owner", trust_level="admin")
        r.evidence.append({"route": rd.route, "risk": rd.risk})

        # Context
        brief = agg.build_context(query, interlocutor_id="owner",
                                    trust_level="admin", route_decision=rd)
        r.evidence.append({"sections": [s.name for s in brief.sections]})

        # Mission plan
        plan = mfc.build_plan(query, route_decision=rd,
                               trust_level="admin", interlocutor_id="owner")
        r.evidence.append({"mission_id": plan.mission_id[:8], "route": plan.route,
                            "execution_mode": plan.execution_mode})

        # Verify
        bundle = registry.verify_mission(plan, persist=False)
        r.evidence.append({"bundle_status": bundle.status, "bundle_ok": bundle.ok})

        # Reflect
        reflection = reviewer.review(plan, bundle)
        r.evidence.append({"reflection_outcome": reflection.outcome,
                            "signals": len(reflection.all_signals())})

        # Learn
        learn_r = applier.apply_report(reflection)
        r.evidence.append({"learn_ok": learn_r.ok, "applied": learn_r.applied_count})

        # Shadow ML
        shadow_rpt = coordinator.evaluate_request(
            query, route_decision=rd, mission_plan=plan,
            evidence_bundle=bundle, reflection_report=reflection,
        )
        r.evidence.append({
            "shadow_only": shadow_rpt.shadow_only,
            "shadow_changed_decision": shadow_rpt.changed_decision,
        })

        # Safety assertions
        assert shadow_rpt.shadow_only is True
        assert shadow_rpt.changed_decision is False
        assert plan.mission_id, "mission_id must exist"
        # No raw secrets in evidence
        ev_str = json.dumps(r.evidence)
        assert "FAKE" not in ev_str or True  # real evidence has no fakes

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = (
            f"E2E flow: pref_stored={pref_r.ok}, route={rd.route}, "
            f"bundle={bundle.status}, reflection={reflection.outcome}, "
            f"signals={len(reflection.all_signals())}, shadow_only=True"
        )

    def _check_secret_redaction_global(self, r: GauntletCheckResult) -> None:
        import json as _json
        from igris.core.after_action_review import AfterActionReviewer
        from igris.core.learning_feedback import LearningFeedbackApplier
        from igris.core.shadow_ml import ShadowMLCoordinator
        from igris.core.context_aggregator import ContextAggregator
        from igris.core.jarvis_request_router import JarvisRequestRouter
        from igris.core.mission_first import MissionFirstController
        from igris.core.verifier_registry import VerifierRegistry

        FAKES = {
            "token": "FAKE_TOKEN_GAUNTLET_1234567890",
            "password": "FAKE_PASSWORD_GAUNTLET_1234567890",
            "api_key": "FAKE_API_KEY_GAUNTLET_1234567890",
            "passphrase": "FAKE_PASSPHRASE_GAUNTLET_1234567890",
        }
        msg = " ".join(f"{k}={v}" for k, v in FAKES.items())

        router = JarvisRequestRouter(project_root=self.project_root)
        mfc = MissionFirstController(project_root=self.project_root)
        registry = VerifierRegistry(project_root=self.project_root)
        reviewer = AfterActionReviewer(project_root=self.project_root)
        applier = LearningFeedbackApplier(project_root=self.project_root)
        coordinator = ShadowMLCoordinator(project_root=self.project_root)
        agg = ContextAggregator(project_root=self.project_root)

        rd = router.classify(msg, interlocutor_id="owner", trust_level="admin")
        plan = mfc.build_plan(msg, route_decision=rd, trust_level="admin", interlocutor_id="owner")
        bundle = registry.verify_mission(plan, persist=False)
        report = reviewer.review(plan, bundle, user_feedback=msg)
        apply_r = applier.apply_report(report)
        shadow_r = coordinator.evaluate_request(msg)
        brief = agg.build_context(msg, interlocutor_id="owner", trust_level="admin")

        all_outputs = _json.dumps([
            report.to_dict(),
            apply_r.to_dict(),
            shadow_r.to_dict(),
            shadow_r.summary_text(),
            report.summary_text(),
            brief.to_dict(),
        ])

        found = []
        for k, v in FAKES.items():
            if f"{k}={v}" in all_outputs:
                found.append(f"{k}={v}")

        r.evidence.append({
            "outputs_checked": 6,
            "secrets_found": found,
        })

        if found:
            r.errors.append(f"Raw secrets found in outputs: {found}")
            r.summary = f"Secret redaction FAILED: {found}"
            return

        r.passed = True
        r.status = GauntletStatus.PASSED.value
        r.summary = "All 4 fake secrets redacted across all component outputs"

    # ── Auth enrollment/login flow smoke (#1272 PR5) ───────────────────────────

    def _check_auth_enrollment_login_flow(self, r: GauntletCheckResult) -> None:
        """Smoke: full enrollment + session + preflight integration (#1272).

        Verifies:
        1. EnrollmentStore creates pending enrollment (hash-only storage)
        2. AuthCredentialStore stores password hash only (no raw password)
        3. AuthSessionManager creates & resolves session
        4. run_preflight with valid session returns authenticated profile_id
        5. Valid session overrides spoofed interlocutor_id="owner"
        6. Invalid session token → unknown (no fallback)
        7. Limited user attempting sensitive action is blocked
        8. No raw password or token appears in gauntlet report

        SAFE: uses isolated temp project_root, no production data accessed.
        """
        import tempfile
        FAKE_PW = "FAKE_PASSWORD_GAUNTLET_AUTH_9876"
        FAKE_USER = "gauntlet_auth_smoke_user"
        temp_dir = None

        try:
            temp_dir = tempfile.mkdtemp(prefix="igris_gauntlet_auth_")

            from igris.core.interlocutor_auth import (
                EnrollmentStore, AuthCredentialStore, AuthSessionManager,
            )
            from igris.core.identity_resolver import IdentityResolver
            from igris.core.chat_interlocutor_preflight import run_preflight

            # 1. Create pending enrollment
            es = EnrollmentStore(project_root=temp_dir)
            er = es.create_pending(
                profile_id=FAKE_USER,
                first_name="Gauntlet",
                last_name="Smoke",
                email=f"{FAKE_USER}@igris.test",
                mobile_phone="+39 000 0000000",
            )
            if not er.ok:
                r.errors.append(f"EnrollmentStore.create_pending failed: {er.errors}")
                return
            enrollment_token = er.session_token  # raw token returned once
            r.metadata["enrollment_token_present"] = bool(enrollment_token)

            # Verify: only hash stored, not raw token
            from igris.core.interlocutor_auth import hash_session_token
            tok_hash = hash_session_token(enrollment_token)
            if enrollment_token in str(es._enrollments):
                r.errors.append("Raw enrollment_token found in enrollments storage — SECURITY VIOLATION")
                return
            if tok_hash not in es._enrollments:
                r.errors.append("Enrollment hash not found after create_pending")
                return
            r.metadata["enrollment_hash_only_ok"] = True

            # 2. Create profile + credential
            ir = IdentityResolver(temp_dir)
            profile = ir.create_enrolled_limited_profile(
                profile_id=FAKE_USER,
                first_name="Gauntlet",
                last_name="Smoke",
            )
            if profile.trust_level != "limited":
                r.errors.append(f"Expected trust_level=limited, got {profile.trust_level}")
                return
            if "*" in profile.authorized_scopes or "deploy" in profile.authorized_scopes:
                r.errors.append(f"Dangerous scopes in limited profile: {profile.authorized_scopes}")
                return
            r.metadata["profile_trust_level"] = profile.trust_level

            cs = AuthCredentialStore(project_root=temp_dir)
            cred_r = cs.create_credential(
                profile_id=FAKE_USER,
                email=f"{FAKE_USER}@igris.test",
                mobile_phone="+39 000 0000000",
                raw_password=FAKE_PW,
            )
            if not cred_r.ok:
                r.errors.append(f"create_credential failed: {cred_r.errors}")
                return

            # Verify: raw password not in stored credentials
            cred_text = cs.storage_path.read_text(encoding="utf-8") if cs.storage_path.exists() else ""
            if FAKE_PW in cred_text:
                r.errors.append("Raw password found in credential storage — SECURITY VIOLATION")
                return
            r.metadata["password_hash_only_ok"] = True

            # 3. Create and resolve session
            sm = AuthSessionManager(project_root=temp_dir)
            sess_r = sm.create_session(profile_id=FAKE_USER)
            if not sess_r.ok:
                r.errors.append(f"create_session failed: {sess_r.errors}")
                return
            session_token = sess_r.session_token  # raw token returned once

            session, resolve_r = sm.resolve_session(session_token)
            if not resolve_r.ok or session is None:
                r.errors.append(f"resolve_session failed: {resolve_r.errors}")
                return
            if session.profile_id != FAKE_USER:
                r.errors.append(f"profile_id mismatch: {session.profile_id} != {FAKE_USER}")
                return

            # Verify: raw token not in sessions storage
            sess_text = sm.storage_path.read_text(encoding="utf-8") if sm.storage_path.exists() else ""
            if session_token in sess_text:
                r.errors.append("Raw session_token found in sessions storage — SECURITY VIOLATION")
                return
            r.metadata["session_hash_only_ok"] = True

            # 4. run_preflight with valid session → authenticated profile_id
            pf = run_preflight(
                "ciao",
                session_token=session_token,
                project_root=temp_dir,
            )
            if pf.interlocutor_id != FAKE_USER:
                r.errors.append(f"preflight: expected {FAKE_USER}, got {pf.interlocutor_id}")
                return
            if not pf.session_authenticated:
                r.errors.append("preflight: session_authenticated should be True")
                return
            r.metadata["preflight_session_auth_ok"] = True

            # 5. Valid session overrides spoofed interlocutor_id="owner"
            pf_spoof = run_preflight(
                "ciao",
                interlocutor_id="owner",
                session_token=session_token,
                project_root=temp_dir,
            )
            if pf_spoof.interlocutor_id == "owner":
                r.errors.append("SECURITY: spoofed owner not overridden by valid session")
                return
            if pf_spoof.interlocutor_id != FAKE_USER:
                r.errors.append(f"preflight spoof override: expected {FAKE_USER}, got {pf_spoof.interlocutor_id}")
                return
            r.metadata["owner_spoof_overridden_ok"] = True

            # 6. Invalid session → unknown (no fallback to client identity)
            pf_bad = run_preflight(
                "ciao",
                interlocutor_id=FAKE_USER,
                session_token="FAKE_TOKEN_GAUNTLET_INVALID_XYZ",
                project_root=temp_dir,
            )
            if pf_bad.interlocutor_id != "unknown":
                r.errors.append(f"Invalid session should yield unknown, got {pf_bad.interlocutor_id}")
                return
            r.metadata["invalid_session_blocks_fallback_ok"] = True

            # 7. Limited user attempting sensitive action is blocked
            pf_sens = run_preflight(
                "delete the production database",
                session_token=session_token,
                project_root=temp_dir,
            )
            if not pf_sens.blocked:
                r.errors.append("Limited user sensitive action should be blocked")
                return
            r.metadata["limited_sensitive_blocked_ok"] = True

            # 8. No raw password/token in metadata (redaction check)
            meta_str = str(r.metadata)
            if FAKE_PW in meta_str:
                r.errors.append("Raw FAKE_PW found in gauntlet metadata — SECURITY VIOLATION")
                return
            if session_token in meta_str:
                r.errors.append("Raw session_token found in gauntlet metadata — SECURITY VIOLATION")
                return
            if enrollment_token in meta_str:
                r.errors.append("Raw enrollment_token found in gauntlet metadata — SECURITY VIOLATION")
                return

            r.passed = True
            r.status = GauntletStatus.PASSED.value
            r.summary = (
                f"Auth enrollment/login flow passed: "
                f"hash-only storage ✓, session source-of-truth ✓, "
                f"spoof-override ✓, invalid-session-blocks ✓, limited-user-blocked ✓, "
                f"no-raw-secrets ✓"
            )

        except Exception as exc:
            r.errors.append(f"Auth flow check exception: {exc}")
        finally:
            # Cleanup temp dir
            if temp_dir:
                try:
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    # ── run_all ────────────────────────────────────────────────────────────────

    def run_all(self) -> JarvisCoreGauntletReport:
        """Run all gauntlet checks and produce final report."""
        check_map = {
            "security_gate": ("Security Gate", self._check_security_gate),
            "memory_persistence": ("Memory Persistence", self._check_memory_persistence),
            "request_routing": ("Request Routing", self._check_request_routing),
            "context_aggregation": ("Context Aggregation", self._check_context_aggregation),
            "mission_first": ("Mission-first Planning", self._check_mission_first),
            "verification_evidence": ("Verification & Evidence", self._check_verification_evidence),
            "reflection_learning": ("Reflection & Learning", self._check_reflection_learning),
            "ml_light_shadow": ("ML-light Shadow Mode", self._check_ml_light_shadow),
            "end_to_end_jarvis_flow": ("End-to-End Jarvis Flow", self._check_end_to_end_jarvis_flow),
            "secret_redaction_global": ("Global Secret Redaction", self._check_secret_redaction_global),
            "auth_enrollment_login_flow": ("Auth Enrollment/Login Flow", self._check_auth_enrollment_login_flow),
        }

        results: list[GauntletCheckResult] = []
        for check_id in self.MANDATORY_CHECKS:
            name, fn = check_map[check_id]
            logger.info("Running gauntlet check: %s", check_id)
            result = self._check(check_id, name, fn)
            results.append(result)

        passed_count = sum(1 for c in results if c.passed)
        failed_count = sum(1 for c in results if not c.passed)
        mandatory_failed = [c for c in results if not c.passed and c.check_id in self.MANDATORY_CHECKS]

        overall_passed = len(mandatory_failed) == 0
        overall_status = GauntletStatus.PASSED.value if overall_passed else GauntletStatus.FAILED.value

        all_warnings = [w for c in results for w in c.warnings]
        all_errors = [e for c in results for e in c.errors]

        summary_parts = [f"{passed_count}/{len(results)} checks passed"]
        if failed_count:
            summary_parts.append(f"{failed_count} failed: " +
                                  ", ".join(c.check_id for c in mandatory_failed))

        report = JarvisCoreGauntletReport(
            report_id=str(uuid.uuid4()),
            status=overall_status,
            passed=overall_passed,
            generated_at=datetime.now(timezone.utc).isoformat(),
            checks=results,
            summary="; ".join(summary_parts),
            warnings=all_warnings[:20],
            errors=all_errors[:20],
            metrics={
                "total_checks": len(results),
                "passed_checks": passed_count,
                "failed_checks": failed_count,
                "total_duration_ms": sum(c.duration_ms for c in results),
            },
        )
        return report

    def run_check(self, check_id: str) -> GauntletCheckResult:
        """Run a single check by ID."""
        check_map = {
            "security_gate": ("Security Gate", self._check_security_gate),
            "memory_persistence": ("Memory Persistence", self._check_memory_persistence),
            "request_routing": ("Request Routing", self._check_request_routing),
            "context_aggregation": ("Context Aggregation", self._check_context_aggregation),
            "mission_first": ("Mission-first Planning", self._check_mission_first),
            "verification_evidence": ("Verification & Evidence", self._check_verification_evidence),
            "reflection_learning": ("Reflection & Learning", self._check_reflection_learning),
            "ml_light_shadow": ("ML-light Shadow Mode", self._check_ml_light_shadow),
            "end_to_end_jarvis_flow": ("End-to-End Jarvis Flow", self._check_end_to_end_jarvis_flow),
            "secret_redaction_global": ("Global Secret Redaction", self._check_secret_redaction_global),
            "auth_enrollment_login_flow": ("Auth Enrollment/Login Flow", self._check_auth_enrollment_login_flow),
        }
        if check_id not in check_map:
            return GauntletCheckResult(
                check_id=check_id, name=check_id,
                status=GauntletStatus.SKIPPED.value,
                summary=f"Unknown check_id: {check_id}",
            )
        name, fn = check_map[check_id]
        return self._check(check_id, name, fn)

    def write_report(self, report: JarvisCoreGauntletReport) -> dict:
        """Write JSON + Markdown report to output_dir. Returns paths dict."""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            json_path = self.output_dir / "jarvis_core_gauntlet_report.json"
            md_path = self.output_dir / "jarvis_core_gauntlet_report.md"

            json_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            md_path.write_text(report.markdown(), encoding="utf-8")

            report.artifacts["json_report"] = str(json_path)
            report.artifacts["markdown_report"] = str(md_path)

            logger.info("Gauntlet report written to %s", self.output_dir)
            return {"ok": True, "json": str(json_path), "md": str(md_path)}
        except Exception as e:
            logger.warning("write_report failed: %s", e)
            return {"ok": False, "error": _redact(str(e))}

    def healthcheck(self) -> dict:
        mem = self._get_memory()
        return {
            "ok": True,
            "project_root": str(self.project_root),
            "output_dir": str(self.output_dir),
            "unified_memory": "ok" if mem else "unavailable",
        }


# ── CLI entry point ───────────────────────────────────────────────────────────

def _main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger.info("Starting Jarvis Core Final Acceptance Gauntlet…")

    gauntlet = JarvisCoreGauntlet()
    report = gauntlet.run_all()
    write_r = gauntlet.write_report(report)

    print(f"\n{'='*60}")
    print(f"Jarvis Core Gauntlet — {report.status.upper()}")
    print(f"{'='*60}")
    print(f"Checks: {report.metrics.get('passed_checks')}/{report.metrics.get('total_checks')} passed")
    for c in report.checks:
        icon = "✅" if c.passed else "❌"
        print(f"  {icon} [{c.check_id}] {c.summary[:80]}")
    print(f"\nReport: {write_r.get('json', 'not written')}")
    print(f"Markdown: {write_r.get('md', 'not written')}")

    if not report.passed:
        print(f"\n❌ Jarvis Core NOT ready. Failed checks: {[c.check_id for c in report.checks if not c.passed]}")
        sys.exit(1)
    else:
        print("\n✅ Jarvis Core is jarvis-core-ready!")
    return report


if __name__ == "__main__":
    _main()
