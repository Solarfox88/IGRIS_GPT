"""Shadow ML API routes (#1248) — shadow/evaluation only, no operational changes."""
# NOTE: do NOT use `from __future__ import annotations` here —
# FastAPI uses runtime annotation inspection.
import json
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
        router = APIRouter(prefix="/api/shadow", tags=["shadow"])
    except ImportError:
        return None

    @router.post("/evaluate")
    async def shadow_evaluate(request: Request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            body = {}

        message = _redact(str(body.get("message", "") or "")[:500])
        if not message:
            return {"ok": False, "error": "message required", "shadow_only": True,
                    "changed_decision": False}

        try:
            from igris.core.shadow_ml import ShadowMLCoordinator
            from igris.models.config import CONFIG
            from types import SimpleNamespace

            # Route decision proxy
            route_data = body.get("route_decision") or {}
            route_decision_proxy = None
            if route_data:
                rd = SimpleNamespace(
                    route=route_data.get("route", ""),
                    risk=route_data.get("risk", "low"),
                )
                route_decision_proxy = rd

            # Mission plan proxy
            mission_data = body.get("mission") or {}
            mission_proxy = None
            if mission_data:
                mp = SimpleNamespace(
                    route=mission_data.get("route", ""),
                    risk=mission_data.get("risk", "low"),
                    blocked=mission_data.get("blocked", False),
                    requires_approval=mission_data.get("requires_approval", False),
                    status=mission_data.get("status", "planned"),
                )
                mission_proxy = mp

            # Bundle proxy
            bundle_data = body.get("bundle") or {}
            bundle_proxy = None
            if bundle_data:
                bp = SimpleNamespace(
                    status=bundle_data.get("status", "inconclusive"),
                    ok=bundle_data.get("ok", False),
                    results=[],
                )
                bundle_proxy = bp

            memory_items = body.get("memory_items") or []
            trust_level = str(body.get("trust_level", "untrusted"))

            coordinator = ShadowMLCoordinator(project_root=str(CONFIG.project_root))
            report = coordinator.evaluate_request(
                message,
                route_decision=route_decision_proxy,
                memory_items=memory_items or None,
                mission_plan=mission_proxy,
                evidence_bundle=bundle_proxy,
                trust_level=trust_level,
            )

            return {
                "ok": report.ok,
                "shadow_only": True,
                "changed_decision": False,
                "report": report.to_dict(),
                "summary": report.summary_text(max_chars=500),
            }

        except Exception as e:
            logger.warning("Shadow evaluate API error: %s", e)
            return {"ok": False, "error": _redact(str(e)), "shadow_only": True,
                    "changed_decision": False}

    @router.get("/health")
    async def shadow_health():
        try:
            from igris.core.shadow_ml import ShadowMLCoordinator
            from igris.models.config import CONFIG
            c = ShadowMLCoordinator(project_root=str(CONFIG.project_root))
            return c.healthcheck()
        except Exception as e:
            return {"ok": False, "error": _redact(str(e))}

    return router


router = _make_router()
