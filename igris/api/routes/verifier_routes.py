"""Verifier API routes (#1246)."""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, Request
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


def _make_router():
    if not _FASTAPI_AVAILABLE:
        return None

    router = APIRouter(prefix="/api/verifier", tags=["verifier"])

    @router.post("/mission")
    async def verify_mission(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            body = {}

        mission_data = body.get("mission") or {}
        if not mission_data:
            return {"ok": False, "error": "mission payload required"}

        try:
            from igris.core.mission_first import MissionPlan, MissionStep
            from igris.core.verifier_registry import VerifierRegistry
            from igris.models.config import CONFIG

            # Reconstruct MissionPlan (simplified — just verify structure)
            steps = []
            for s in mission_data.get("steps", []):
                step = MissionStep(
                    step_id=s.get("step_id", ""),
                    title=s.get("title", ""),
                    action_type=s.get("action_type", "analysis"),
                    risk=s.get("risk", "low"),
                    requires_approval=s.get("requires_approval", False),
                    dry_run_only=s.get("dry_run_only", True),
                )
                steps.append(step)

            plan = MissionPlan(
                mission_id=mission_data.get("mission_id", "api_mission"),
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

            registry = VerifierRegistry(project_root=str(CONFIG.project_root))
            bundle = registry.verify_mission(plan, persist=True)

            return {
                "ok": bundle.ok,
                "bundle": bundle.to_dict(),
                "summary": bundle.summary_text(max_chars=1000),
            }
        except Exception as e:
            logger.warning("Verifier API error: %s", e)
            return {"ok": False, "error": str(e), "bundle": None}

    @router.get("/health")
    async def verifier_health() -> dict:
        try:
            from igris.core.verifier_registry import VerifierRegistry
            from igris.models.config import CONFIG
            registry = VerifierRegistry(project_root=str(CONFIG.project_root))
            return registry.healthcheck()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return router


router = _make_router()
