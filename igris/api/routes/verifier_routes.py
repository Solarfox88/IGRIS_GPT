"""Verifier API routes (#1246)."""
from __future__ import annotations
import json
import logging
logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, Request
    from pydantic import BaseModel, Field
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


class MissionStepPayload(BaseModel if _FASTAPI_AVAILABLE else object):  # type: ignore[misc]
    """Request schema for a single mission step (#1297)."""
    step_id: str = ""
    title: str = ""
    action_type: str = "analysis"
    risk: str = "low"
    requires_approval: bool = False
    dry_run_only: bool = True


class MissionPayload(BaseModel if _FASTAPI_AVAILABLE else object):  # type: ignore[misc]
    """Request schema for the 'mission' field (#1297)."""
    mission_id: str = "api_mission"
    title: str = ""
    route: str = ""
    risk: str = "low"
    status: str = "planned"
    execution_mode: str = "plan_only"
    interlocutor_id: str = "unknown"
    trust_level: str = "untrusted"
    requires_approval: bool = False
    blocked: bool = False
    steps: list = Field(default_factory=list)


class VerifyMissionRequest(BaseModel if _FASTAPI_AVAILABLE else object):  # type: ignore[misc]
    """Explicit request schema for POST /api/verifier/mission (#1297)."""
    mission: MissionPayload | None = None
    bundle: dict | None = None
    mission_plan: dict | None = None
    evidence_bundle: dict | None = None


def _make_router():
    if not _FASTAPI_AVAILABLE:
        return None

    router = APIRouter(prefix="/api/verifier", tags=["verifier"])

    @router.post("/mission")
    async def verify_mission(request: Request) -> dict:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError, TypeError):
            body = {}

        # Check for common wrong field names and provide helpful error (#1297)
        wrong_fields = []
        for wrong in ("bundle", "mission_plan", "evidence_bundle"):
            if wrong in body and "mission" not in body:
                wrong_fields.append(wrong)

        mission_data = body.get("mission") or {}
        if not mission_data:
            if wrong_fields:
                return {
                    "ok": False,
                    "error": (
                        f"Missing 'mission' field (found '{wrong_fields[0]}'). "
                        "Expected: {{'mission': {{mission_id, title, route, steps}}}}"
                    ),
                }
            return {
                "ok": False,
                "error": (
                    "Missing 'mission' field. "
                    "Expected: {'mission': {mission_id, title, route, steps}}"
                ),
            }

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
        except Exception as e:  # noqa: BLE001  # API endpoint boundary — return error response
            logger.warning("Verifier API error: %s", e)
            return {"ok": False, "error": str(e), "bundle": None}

    @router.get("/health")
    async def verifier_health() -> dict:
        try:
            from igris.core.verifier_registry import VerifierRegistry
            from igris.models.config import CONFIG
            registry = VerifierRegistry(project_root=str(CONFIG.project_root))
            return registry.healthcheck()
        except Exception as e:  # noqa: BLE001  # API endpoint boundary — return error response
            return {"ok": False, "error": str(e)}

    return router


router = _make_router()
