"""Verifier Registry / Evidence Bundle (#1246).

Provides mission verification and evidence collection.
Verifiers CHECK missions — they do NOT execute operations.
"""
from __future__ import annotations

import logging
import re
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

class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"


class EvidenceKind(str, Enum):
    TEXT = "text"
    LOG = "log"
    TEST_RESULT = "test_result"
    FILE_CHECK = "file_check"
    GIT_STATE = "git_state"
    API_RESPONSE = "api_response"
    MISSION_PLAN = "mission_plan"
    SECURITY_DECISION = "security_decision"
    CONTEXT_BRIEF = "context_brief"
    VERIFIER_OUTPUT = "verifier_output"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class EvidenceItem:
    evidence_id: str
    kind: str
    title: str
    content: str = ""
    source: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    safe_for_prompt: bool = True
    redacted: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _redact_any({
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "timestamp": self.timestamp,
            "safe_for_prompt": self.safe_for_prompt,
            "redacted": self.redacted,
            "metadata": self.metadata,
            "warnings": self.warnings,
        })


@dataclass
class VerificationResult:
    verifier_id: str
    name: str
    status: str
    passed: bool = False
    summary: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _redact_any({
            "verifier_id": self.verifier_id,
            "name": self.name,
            "status": self.status,
            "passed": self.passed,
            "summary": self.summary,
            "evidence_ids": self.evidence_ids,
            "warnings": self.warnings,
            "errors": self.errors,
        })


@dataclass
class EvidenceBundle:
    bundle_id: str
    mission_id: str
    route: str = ""
    risk: str = ""
    status: str = "inconclusive"
    ok: bool = False
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    results: list[VerificationResult] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _redact_any({
            "bundle_id": self.bundle_id,
            "mission_id": self.mission_id,
            "route": self.route,
            "risk": self.risk,
            "status": self.status,
            "ok": self.ok,
            "generated_at": self.generated_at,
            "results": [r.to_dict() for r in self.results],
            "evidence": [e.to_dict() for e in self.evidence],
            "warnings": self.warnings,
        })

    def summary_text(self, max_chars: int = 4000) -> str:
        lines = [
            "[EVIDENCE BUNDLE]",
            f"Mission: {self.mission_id[:8]} | Route: {self.route} | Status: {self.status}",
            f"Generated: {self.generated_at}",
            "",
        ]
        for r in self.results:
            icon = "OK" if r.passed else ("WARN" if r.status == "warning" else "FAIL")
            lines.append(f"[{icon}] {r.name}: {r.summary[:120]}")
        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in self.warnings[:5]:
                lines.append(f"  - {w}")
        text = _redact("\n".join(lines))
        return text[:max_chars] + ("\n[TRUNCATED]" if len(text) > max_chars else "")


# ── Base Verifier ─────────────────────────────────────────────────────────────

class BaseVerifier:
    verifier_id: str = "base"
    name: str = "Base Verifier"
    supported_routes: set[str] = set()
    supports_blocked: bool = False

    def can_verify(self, mission_plan: Any) -> bool:
        route = str(getattr(mission_plan, "route", ""))
        if not self.supported_routes:
            return True  # universal verifier
        if route in self.supported_routes:
            return True
        if self.supports_blocked and getattr(mission_plan, "blocked", False):
            return True
        return False

    def _make_evidence(self, title: str, content: str, kind: str = "verifier_output",
                       source: str = "") -> EvidenceItem:
        return EvidenceItem(
            evidence_id=str(uuid.uuid4()),
            kind=kind,
            title=title,
            content=_redact(content),
            source=source or self.verifier_id,
            redacted=True,
        )

    def verify(self, mission_plan: Any, *, context: Any = None) -> tuple[VerificationResult, list[EvidenceItem]]:
        return VerificationResult(
            verifier_id=self.verifier_id,
            name=self.name,
            status=VerificationStatus.SKIPPED,
            passed=True,
            summary="Base verifier — skipped",
        ), []


# ── Concrete Verifiers ────────────────────────────────────────────────────────

class MissionStructureVerifier(BaseVerifier):
    verifier_id = "mission_structure"
    name = "Mission Structure Verifier"
    supports_blocked = True

    def verify(self, plan: Any, *, context: Any = None):
        errors = []
        warnings = []
        evidence_items = []

        # Check required fields
        if not getattr(plan, "mission_id", ""):
            errors.append("mission_id is missing")
        if not getattr(plan, "route", ""):
            errors.append("route is missing")
        if not getattr(plan, "status", ""):
            errors.append("status is missing")
        if not getattr(plan, "execution_mode", ""):
            errors.append("execution_mode is missing")

        # Check steps for operational routes
        _op_routes = {"read_only_inspection", "project_reasoning", "code_change",
                       "server_operation", "github_operation", "deploy_operation", "high_risk_operation"}
        route = str(getattr(plan, "route", ""))
        steps = getattr(plan, "steps", [])
        if route in _op_routes and not steps and not getattr(plan, "blocked", False):
            warnings.append(f"No steps defined for operational route: {route}")

        # Check blocked/approval consistency
        if getattr(plan, "blocked", False):
            execution_mode = str(getattr(plan, "execution_mode", ""))
            if execution_mode != "blocked":
                warnings.append(f"Blocked plan has execution_mode={execution_mode!r} (expected 'blocked')")

        if getattr(plan, "requires_approval", False):
            execution_mode = str(getattr(plan, "execution_mode", ""))
            if execution_mode not in ("approval_required", "blocked"):
                warnings.append(f"requires_approval=True but execution_mode={execution_mode!r}")

        # Check no raw secret in plan
        try:
            plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else {}
            import json
            plan_str = json.dumps(plan_dict)
            if _SECRET_RE.search(plan_str):
                errors.append("Raw secret detected in mission plan — redaction failed")
        except Exception as e:
            warnings.append(f"Could not serialize plan for secret check: {e}")

        # Create evidence snapshot
        try:
            plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else {}
            ev = self._make_evidence(
                "Mission plan snapshot",
                str({k: v for k, v in plan_dict.items() if k not in ("steps",)}),
                kind=EvidenceKind.MISSION_PLAN,
            )
            evidence_items.append(ev)
        except Exception as e:
            warnings.append(f"Evidence creation failed: {e}")
            logger.warning("MissionStructureVerifier: evidence creation failed: %s", e)

        passed = not errors
        status = VerificationStatus.PASSED if passed else VerificationStatus.FAILED
        if passed and warnings:
            status = VerificationStatus.WARNING

        return VerificationResult(
            verifier_id=self.verifier_id,
            name=self.name,
            status=status.value,
            passed=passed,
            summary=("Mission structure valid" if passed else f"Structure errors: {'; '.join(errors)}"),
            evidence_ids=[ev.evidence_id for ev in evidence_items],
            warnings=warnings,
            errors=errors,
        ), evidence_items


class ApprovalPolicyVerifier(BaseVerifier):
    verifier_id = "approval_policy"
    name = "Approval Policy Verifier"
    supported_routes = {"deploy_operation", "github_operation", "server_operation",
                         "code_change", "high_risk_operation", "read_only_inspection"}
    supports_blocked = True

    _APPROVAL_REQUIRED_ROUTES = {"deploy_operation", "github_operation", "code_change",
                                   "server_operation", "high_risk_operation"}

    def verify(self, plan: Any, *, context: Any = None):
        errors = []
        warnings = []
        route = str(getattr(plan, "route", ""))
        requires_approval = getattr(plan, "requires_approval", False)
        blocked = getattr(plan, "blocked", False)
        execution_mode = str(getattr(plan, "execution_mode", ""))
        trust_level = str(getattr(plan, "trust_level", "untrusted"))

        if route in self._APPROVAL_REQUIRED_ROUTES:
            if not requires_approval and not blocked:
                errors.append(
                    f"Route {route!r} must require approval or be blocked, "
                    f"got requires_approval={requires_approval} blocked={blocked}"
                )

        if route == "read_only_inspection" and requires_approval and trust_level not in ("untrusted", "unknown"):
            warnings.append("read_only_inspection requiring approval for trusted user — verify if intended")

        passed = not errors
        status = VerificationStatus.PASSED if passed else VerificationStatus.FAILED
        if passed and warnings:
            status = VerificationStatus.WARNING

        return VerificationResult(
            verifier_id=self.verifier_id,
            name=self.name,
            status=status.value,
            passed=passed,
            summary=("Approval policy satisfied" if passed else f"Policy violations: {'; '.join(errors)}"),
            warnings=warnings,
            errors=errors,
        ), []


class NoAutoExecutionVerifier(BaseVerifier):
    verifier_id = "no_auto_execution"
    name = "No Auto Execution Verifier"
    supported_routes = {"deploy_operation", "github_operation", "server_operation",
                         "code_change", "high_risk_operation"}
    supports_blocked = True

    _MUTATING_TYPES = {"deploy", "github", "server", "code_change"}

    def verify(self, plan: Any, *, context: Any = None):
        errors = []
        warnings = []
        steps = getattr(plan, "steps", [])
        blocked = getattr(plan, "blocked", False)

        if blocked:
            return VerificationResult(
                verifier_id=self.verifier_id,
                name=self.name,
                status=VerificationStatus.PASSED.value,
                passed=True,
                summary="Mission blocked — no execution possible",
            ), []

        for step in steps:
            action_type = str(getattr(step, "action_type", ""))
            status_val = str(getattr(step, "status", "planned"))
            dry_run_only = getattr(step, "dry_run_only", True)
            requires_step_approval = getattr(step, "requires_approval", False)

            if action_type in self._MUTATING_TYPES:
                if not dry_run_only and not requires_step_approval:
                    errors.append(
                        f"Step {getattr(step, 'title', '?')!r} ({action_type}) "
                        "is mutating without dry_run_only or requires_approval"
                    )
                if status_val == "completed":
                    errors.append(
                        f"Mutating step {getattr(step, 'title', '?')!r} has status=completed "
                        "without evidence of approval"
                    )

        passed = not errors
        return VerificationResult(
            verifier_id=self.verifier_id,
            name=self.name,
            status=VerificationStatus.PASSED.value if passed else VerificationStatus.FAILED.value,
            passed=passed,
            summary="No auto-execution detected" if passed else f"Auto-execution risks: {'; '.join(errors)}",
            warnings=warnings,
            errors=errors,
        ), []


class EvidencePresenceVerifier(BaseVerifier):
    verifier_id = "evidence_presence"
    name = "Evidence Presence Verifier"
    supports_blocked = True

    def verify(self, plan: Any, *, context: Any = None):
        evidence_items = []

        # Always create mission plan evidence
        try:
            plan_data = plan.to_dict() if hasattr(plan, "to_dict") else {"error": "no to_dict"}
            import json
            summary = {k: v for k, v in plan_data.items()
                       if k in ("mission_id", "route", "risk", "status", "execution_mode",
                                "requires_approval", "blocked", "interlocutor_id", "trust_level")}
            ev1 = self._make_evidence(
                "Mission metadata",
                json.dumps(summary, indent=2),
                kind=EvidenceKind.MISSION_PLAN,
                source="mission_first",
            )
            evidence_items.append(ev1)
        except Exception as e:
            logger.warning("EvidencePresenceVerifier: plan evidence failed: %s", e)

        # Add context summary if available
        context_summary = getattr(plan, "context_summary", "") or ""
        if context_summary:
            ev2 = self._make_evidence(
                "Context brief summary",
                context_summary[:500],
                kind=EvidenceKind.CONTEXT_BRIEF,
                source="context_aggregator",
            )
            evidence_items.append(ev2)

        # Add steps summary
        steps = getattr(plan, "steps", [])
        if steps:
            step_summaries = [f"{i+1}. {getattr(s, 'title', '?')} ({getattr(s, 'action_type', '?')})"
                               for i, s in enumerate(steps[:5])]
            ev3 = self._make_evidence(
                "Mission steps",
                "\n".join(step_summaries),
                kind=EvidenceKind.TEXT,
                source="mission_first",
            )
            evidence_items.append(ev3)

        return VerificationResult(
            verifier_id=self.verifier_id,
            name=self.name,
            status=VerificationStatus.PASSED.value,
            passed=True,
            summary=f"Evidence collected: {len(evidence_items)} item(s)",
            evidence_ids=[ev.evidence_id for ev in evidence_items],
        ), evidence_items


class SecurityVerifier(BaseVerifier):
    verifier_id = "security"
    name = "Security Verifier"
    supports_blocked = True

    def verify(self, plan: Any, *, context: Any = None):
        errors = []
        warnings = []
        trust_level = str(getattr(plan, "trust_level", "untrusted"))
        interlocutor_id = str(getattr(plan, "interlocutor_id", "unknown"))
        route = str(getattr(plan, "route", ""))
        blocked = getattr(plan, "blocked", False)
        risk = str(getattr(plan, "risk", "low"))

        _UNTRUSTED = {"untrusted", "unknown", ""}
        _HIGH_RISK_ROUTES = {"deploy_operation", "high_risk_operation"}

        # untrusted + high-risk must be blocked
        if trust_level in _UNTRUSTED and route in _HIGH_RISK_ROUTES and not blocked:
            errors.append(
                f"Security violation: untrusted interlocutor {interlocutor_id!r} "
                f"attempting high-risk route {route!r} without being blocked"
            )

        # Check for secret leakage in plan
        try:
            plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else {}
            import json
            plan_str = json.dumps(plan_dict)
            if _SECRET_RE.search(plan_str):
                errors.append("Security: raw secret detected in mission plan output")
        except Exception as e:
            warnings.append(f"Secret check failed: {e}")
            logger.warning("SecurityVerifier: secret check failed: %s", e)

        passed = not errors
        return VerificationResult(
            verifier_id=self.verifier_id,
            name=self.name,
            status=VerificationStatus.PASSED.value if passed else VerificationStatus.FAILED.value,
            passed=passed,
            summary="Security checks passed" if passed else f"Security violations: {'; '.join(errors)}",
            warnings=warnings,
            errors=errors,
        ), []


class ReadOnlyVerifier(BaseVerifier):
    verifier_id = "read_only"
    name = "Read-Only Verifier"
    supported_routes = {"read_only_inspection"}

    def verify(self, plan: Any, *, context: Any = None):
        errors = []
        execution_mode = str(getattr(plan, "execution_mode", ""))
        steps = getattr(plan, "steps", [])

        if execution_mode not in ("read_only", "blocked", "dry_run"):
            errors.append(f"read_only_inspection should have execution_mode=read_only, got {execution_mode!r}")

        for step in steps:
            action_type = str(getattr(step, "action_type", ""))
            if action_type in ("deploy", "github", "server", "code_change"):
                errors.append(f"Read-only mission has mutating step: {action_type}")

        passed = not errors
        return VerificationResult(
            verifier_id=self.verifier_id,
            name=self.name,
            status=VerificationStatus.PASSED.value if passed else VerificationStatus.FAILED.value,
            passed=passed,
            summary="Read-only constraints satisfied" if passed else f"Violations: {'; '.join(errors)}",
            errors=errors,
        ), []


class PlanOnlyVerifier(BaseVerifier):
    verifier_id = "plan_only"
    name = "Plan-Only Verifier"
    supported_routes = {"project_reasoning"}

    def verify(self, plan: Any, *, context: Any = None):
        errors = []
        steps = getattr(plan, "steps", [])
        for step in steps:
            action_type = str(getattr(step, "action_type", ""))
            if action_type not in ("analysis", "read_only", ""):
                errors.append(f"project_reasoning step has non-analysis action: {action_type!r}")

        passed = not errors
        return VerificationResult(
            verifier_id=self.verifier_id,
            name=self.name,
            status=VerificationStatus.PASSED.value if passed else VerificationStatus.FAILED.value,
            passed=passed,
            summary="Plan-only constraints satisfied" if passed else f"Violations: {'; '.join(errors)}",
            errors=errors,
        ), []


# ── VerifierRegistry ──────────────────────────────────────────────────────────

class VerifierRegistry:
    """Central registry for mission verifiers."""

    def __init__(
        self,
        project_root: str | Path | None = None,
        unified_memory=None,
        context_aggregator=None,
    ):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self._memory = unified_memory
        self._context_aggregator = context_aggregator
        self._verifiers: list[BaseVerifier] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(MissionStructureVerifier())
        self.register(ApprovalPolicyVerifier())
        self.register(NoAutoExecutionVerifier())
        self.register(EvidencePresenceVerifier())
        self.register(SecurityVerifier())
        self.register(ReadOnlyVerifier())
        self.register(PlanOnlyVerifier())

    def register(self, verifier: BaseVerifier) -> None:
        self._verifiers.append(verifier)

    def list_verifiers(self) -> list[dict]:
        return [{"id": v.verifier_id, "name": v.name, "routes": list(v.supported_routes)}
                for v in self._verifiers]

    def select_verifiers(self, mission_plan: Any) -> list[BaseVerifier]:
        return [v for v in self._verifiers if v.can_verify(mission_plan)]

    def _get_memory(self):
        if self._memory is None:
            try:
                from igris.core.unified_memory import UnifiedMemory
                self._memory = UnifiedMemory(project_root=self.project_root)
            except Exception as e:
                logger.debug("VerifierRegistry: UnifiedMemory unavailable: %s", e)
        return self._memory

    def verify_mission(
        self,
        mission_plan: Any,
        *,
        context: Any = None,
        persist: bool = True,
    ) -> EvidenceBundle:
        """Run all applicable verifiers on the mission plan."""
        bundle = EvidenceBundle(
            bundle_id=str(uuid.uuid4()),
            mission_id=getattr(mission_plan, "mission_id", "unknown"),
            route=str(getattr(mission_plan, "route", "")),
            risk=str(getattr(mission_plan, "risk", "low")),
        )

        verifiers = self.select_verifiers(mission_plan)
        all_evidence: list[EvidenceItem] = []

        for verifier in verifiers:
            try:
                result, evidence_items = verifier.verify(mission_plan, context=context)
                bundle.results.append(result)
                all_evidence.extend(evidence_items)
            except Exception as e:
                logger.warning("VerifierRegistry: verifier %s raised: %s", verifier.verifier_id, e)
                bundle.warnings.append(f"{verifier.verifier_id} failed: {e}")
                bundle.results.append(VerificationResult(
                    verifier_id=verifier.verifier_id,
                    name=verifier.name,
                    status=VerificationStatus.INCONCLUSIVE.value,
                    passed=False,
                    summary=f"Verifier raised exception: {e}",
                    errors=[str(e)],
                ))

        bundle.evidence = all_evidence

        # Determine bundle status
        all_passed = all(r.passed for r in bundle.results)
        any_failed = any(r.status == VerificationStatus.FAILED.value for r in bundle.results)
        is_blocked = getattr(mission_plan, "blocked", False)

        if is_blocked:
            bundle.status = VerificationStatus.BLOCKED.value
            bundle.ok = True  # being blocked correctly is a valid state
        elif all_passed:
            bundle.status = VerificationStatus.PASSED.value
            bundle.ok = True
        elif any_failed:
            bundle.status = VerificationStatus.FAILED.value
            bundle.ok = False
        else:
            bundle.status = VerificationStatus.WARNING.value
            bundle.ok = True

        if persist:
            persist_result = self.persist_bundle(bundle)
            if not persist_result.get("ok"):
                bundle.warnings.append(f"persistence_degraded: {persist_result.get('reason','')}")

        return bundle

    def persist_bundle(self, bundle: EvidenceBundle) -> dict:
        """Persist evidence bundle via UnifiedMemory.store_run_event()."""
        mem = self._get_memory()
        if mem is None:
            return {"ok": False, "reason": "unified_memory_unavailable",
                    "persistence_degraded": True}
        try:
            result = mem.store_run_event(
                mission_id=bundle.mission_id,
                action=f"verification:{bundle.route}",
                status=bundle.status,
                outcome=f"bundle_id={bundle.bundle_id} results={len(bundle.results)}",
                project="jarvis_core",
            )
            if result.ok:
                return {"ok": True, "bundle_id": bundle.bundle_id}
            else:
                logger.warning("VerifierRegistry: persist_bundle store_run_event ok=False: %s", result.warnings)
                return {"ok": False, "reason": "store_run_event returned ok=False",
                        "persistence_degraded": True, "warnings": result.warnings}
        except Exception as e:
            logger.warning("VerifierRegistry: persist_bundle failed: %s", e)
            return {"ok": False, "reason": str(e), "persistence_degraded": True}

    def healthcheck(self) -> dict:
        mem = self._get_memory()
        status = {
            "unified_memory": "ok" if mem else "unavailable",
            "context_aggregator": "ok" if self._context_aggregator else "unavailable",
            "verifiers_registered": len(self._verifiers),
        }
        ok = status["unified_memory"] in ("ok", "unavailable")
        return {"ok": ok, "backends": status, "warnings": []}
