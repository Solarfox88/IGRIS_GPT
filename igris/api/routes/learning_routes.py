"""Learning / Reflection API routes (#1247)."""
# NOTE: do NOT use `from __future__ import annotations` here —
# FastAPI uses runtime annotation inspection and deferred strings break Request injection.
import logging
import re

logger = logging.getLogger(__name__)

_SECRET_RE = re.compile(
    r'(token|passphrase|password|secret|api[_\s]?key|bearer)\s*[=:]\s*\S+', re.IGNORECASE,
)
def _redact(text): return _SECRET_RE.sub(r'\1=<REDACTED>', str(text)) if text else text

def _make_router():
    try:
        from fastapi import APIRouter, Request
        router = APIRouter(prefix="/api/learning", tags=["learning"])
    except ImportError:
        return None

    @router.post("/reflection")
    async def run_reflection(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}

        mission_data = body.get("mission") or {}
        bundle_data = body.get("bundle") or {}
        user_feedback = _redact(str(body.get("user_feedback", "") or "")[:500])

        if not mission_data:
            return {"ok": False, "error": "mission payload required"}

        try:
            from igris.core.mission_first import MissionPlan, MissionStep
            from igris.core.after_action_review import AfterActionReviewer
            from igris.models.config import CONFIG

            steps = [MissionStep(
                step_id=s.get("step_id", ""),
                title=s.get("title", ""),
                action_type=s.get("action_type", "analysis"),
                risk=s.get("risk", "low"),
                requires_approval=s.get("requires_approval", False),
                dry_run_only=s.get("dry_run_only", True),
            ) for s in mission_data.get("steps", [])]

            plan = MissionPlan(
                mission_id=mission_data.get("mission_id", ""),
                title=mission_data.get("title", ""),
                route=mission_data.get("route", ""),
                risk=mission_data.get("risk", "low"),
                status=mission_data.get("status", "planned"),
                execution_mode=mission_data.get("execution_mode", "plan_only"),
                interlocutor_id=mission_data.get("interlocutor_id", "unknown"),
                trust_level=mission_data.get("trust_level", "untrusted"),
                requires_approval=mission_data.get("requires_approval", False),
                blocked=mission_data.get("blocked", False),
                steps=steps,
            )

            # Simple bundle proxy
            class SimpleBundleProxy:
                def __init__(self, d):
                    self.status = d.get("status", "inconclusive")
                    self.ok = d.get("ok", False)
                    self.results = []

            bundle_proxy = SimpleBundleProxy(bundle_data) if bundle_data else None

            reviewer = AfterActionReviewer(project_root=str(CONFIG.project_root))
            report = reviewer.review(plan, bundle_proxy, user_feedback=user_feedback)

            from igris.core.learning_feedback import LearningFeedbackApplier
            applier = LearningFeedbackApplier(project_root=str(CONFIG.project_root))
            apply_result = applier.apply_report(report)

            return {
                "ok": report.confidence > 0,
                "report": report.to_dict(),
                "summary": report.summary_text(max_chars=500),
                "apply_result": apply_result.to_dict(),
            }
        except Exception as e:
            logger.warning("Learning reflection API error: %s", e)
            return {"ok": False, "error": str(e)}

    @router.get("/health")
    async def learning_health():
        try:
            from igris.core.after_action_review import AfterActionReviewer
            from igris.models.config import CONFIG
            r = AfterActionReviewer(project_root=str(CONFIG.project_root))
            return r.healthcheck()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return router

router = _make_router()
