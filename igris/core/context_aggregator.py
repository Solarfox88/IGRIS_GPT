"""Context Aggregator — collects, normalizes and synthesizes operational context (#1244).

Produces a PersonalOSBrief: a safe, structured summary of IGRIS operational state
usable by chat, router, missions, reasoning loop, dashboard, and future modules.

The aggregator COLLECTS context only — it does NOT execute operations.
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    if not text:
        return text
    return _SECRET_RE.sub(r'\1=<REDACTED>', str(text))


def _redact_dict(d: dict) -> dict:
    """Recursively redact dict values."""
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = _redact(v)
        elif isinstance(v, dict):
            out[k] = _redact_dict(v)
        elif isinstance(v, list):
            out[k] = [_redact(i) if isinstance(i, str) else i for i in v]
        else:
            out[k] = v
    return out


# ── Trust helpers ─────────────────────────────────────────────────────────────

_TRUSTED_LEVELS = {"admin", "owner", "trusted"}


def _allows_sensitive(trust_level: str) -> bool:
    return (trust_level or "").lower() in _TRUSTED_LEVELS


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ContextSection:
    name: str
    title: str
    status: str = "ok"          # ok | empty | degraded | unavailable
    priority: int = 50
    summary: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = ""
    safe_for_prompt: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "summary": _redact(self.summary),
            "items": [_redact_dict(i) if isinstance(i, dict) else {"text": _redact(str(i))} for i in self.items],
            "warnings": self.warnings,
            "source": self.source,
            "safe_for_prompt": self.safe_for_prompt,
        }


@dataclass
class PersonalOSBrief:
    ok: bool
    generated_at: str
    interlocutor_id: str = "unknown"
    trust_level: str = "untrusted"
    route: str = ""
    query: str = ""
    sections: list[ContextSection] = field(default_factory=list)
    brief_text: str = ""
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "generated_at": self.generated_at,
            "interlocutor_id": self.interlocutor_id,
            "trust_level": self.trust_level,
            "route": self.route,
            "query": _redact(self.query),
            "sections": [s.to_dict() for s in self.sections],
            "brief_text": _redact(self.brief_text),
            "warnings": self.warnings,
            "degraded": self.degraded,
        }

    def get_section(self, name: str) -> ContextSection | None:
        return next((s for s in self.sections if s.name == name), None)


# ── ContextAggregator ─────────────────────────────────────────────────────────

class ContextAggregator:
    """Collects and normalizes context from all IGRIS subsystems.

    Produces a PersonalOSBrief suitable for injection into chat, mission
    reasoning, or dashboard display.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        unified_memory=None,
        task_engine=None,
        mission_controller=None,
    ):
        if project_root is None:
            try:
                from igris.models.config import CONFIG
                project_root = CONFIG.project_root
            except Exception:
                project_root = Path.home()
        self.project_root = Path(project_root)
        self._memory = unified_memory
        self._task_engine = task_engine
        self._mission_controller = mission_controller

    def _get_memory(self):
        if self._memory is None:
            try:
                from igris.core.unified_memory import UnifiedMemory
                self._memory = UnifiedMemory(project_root=self.project_root)
            except Exception as e:
                logger.debug("ContextAggregator: UnifiedMemory unavailable: %s", e)
        return self._memory

    # ── Section builders ──────────────────────────────────────────────────────

    def _section_route(self, route_decision) -> ContextSection:
        sec = ContextSection(name="route", title="Route Decision", priority=10, source="jarvis_router")
        if route_decision is None:
            sec.status = "empty"
            sec.summary = "No route decision provided."
            return sec

        try:
            rd = route_decision.to_dict() if hasattr(route_decision, "to_dict") else dict(route_decision)
            sec.summary = f"Route: {rd.get('route', '?')} | Risk: {rd.get('risk', '?')}"
            if rd.get("blocked"):
                sec.summary += " | BLOCKED"
            if rd.get("requires_approval"):
                sec.summary += " | REQUIRES APPROVAL"
            if rd.get("requires_clarification"):
                sec.summary += " | NEEDS CLARIFICATION"
            sec.items = [_redact_dict({k: v for k, v in rd.items()
                          if k in ("route", "risk", "blocked", "requires_approval",
                                   "requires_clarification", "memory_mode",
                                   "mission_required", "reason")})]
            sec.status = "ok"
        except Exception as e:
            sec.status = "degraded"
            sec.warnings.append(f"route section error: {e}")
            logger.warning("ContextAggregator: route section failed: %s", e)

        return sec

    def _section_memory(self, query: str, interlocutor_id: str, trust_level: str,
                        route_str: str, max_items: int) -> ContextSection:
        sec = ContextSection(name="memory", title="Memory Context", priority=20, source="unified_memory")

        if not _allows_sensitive(trust_level):
            sec.status = "empty"
            sec.summary = "Memory context not available for untrusted interlocutor."
            sec.safe_for_prompt = False
            return sec

        mem = self._get_memory()
        if mem is None:
            sec.status = "unavailable"
            sec.warnings.append("unified_memory unavailable")
            return sec

        try:
            mission_routes = {"read_only_inspection", "project_reasoning", "code_change",
                              "server_operation", "github_operation", "deploy_operation"}
            if route_str in mission_routes:
                result = mem.retrieve_for_mission(goal=query, interlocutor_id=interlocutor_id,
                                                   trust_level=trust_level, limit=max_items)
            else:
                result = mem.retrieve_for_chat(query=query, interlocutor_id=interlocutor_id,
                                                trust_level=trust_level, limit=max_items)

            sec.summary = _redact(result.context[:500]) if result.context else "No relevant memory found."
            sec.items = [i.to_dict() if hasattr(i, "to_dict") else (i if isinstance(i, dict) else {"text": str(i)})
                         for i in result.items[:max_items]]
            sec.warnings = list(result.warnings)
            sec.status = "degraded" if result.degraded else ("empty" if not result.items else "ok")
            sec.safe_for_prompt = True
            if result.influence_report:
                sec.items.append({"influence_report": _redact(result.influence_report)})
        except Exception as e:
            sec.status = "degraded"
            sec.warnings.append(f"memory section error: {e}")
            logger.warning("ContextAggregator: memory section failed: %s", e)

        return sec

    def _section_tasks(self, max_items: int) -> ContextSection:
        sec = ContextSection(name="tasks_timeline", title="Tasks & Timeline", priority=30, source="task_engine")

        te = self._task_engine
        if te is None:
            sec.status = "unavailable"
            sec.warnings.append("task_engine not provided")
            return sec

        try:
            timeline = None
            # TaskEngine uses recent_timeline_events(limit)
            fn = getattr(te, "recent_timeline_events", None)
            if fn and callable(fn):
                timeline = fn(limit=max_items)
            else:
                for method in ("get_timeline_events", "get_recent_events"):
                    fn2 = getattr(te, method, None)
                    if fn2 and callable(fn2):
                        timeline = fn2()
                        break
                if timeline is None and hasattr(te, "timeline_events"):
                    timeline = te.timeline_events

            if timeline:
                recent = list(timeline)[-max_items:]
                sec.items = [_redact_dict(e) if isinstance(e, dict) else {"event": _redact(str(e))} for e in recent]
                sec.summary = f"{len(list(timeline))} events, showing last {len(sec.items)}"
                sec.status = "ok"
            else:
                sec.status = "empty"
                sec.summary = "No timeline events."
        except Exception as e:
            sec.status = "degraded"
            sec.warnings.append(f"tasks section error: {e}")
            logger.warning("ContextAggregator: tasks section failed: %s", e)

        return sec

    def _section_missions(self, max_items: int) -> ContextSection:
        sec = ContextSection(name="missions", title="Active Missions", priority=25, source="mission_controller")

        mc = self._mission_controller
        if mc is None:
            sec.status = "unavailable"
            sec.warnings.append("mission_controller not provided")
            return sec

        try:
            missions = None
            # Try module-level list_controlled_missions function first
            for method in ("list_controlled_missions", "get_active_missions", "list_active", "list_missions"):
                fn = getattr(mc, method, None)
                if fn and callable(fn):
                    missions = fn()
                    break

            if missions:
                items = list(missions)[:max_items]
                sec.items = [
                    _redact_dict(m.__dict__) if hasattr(m, "__dict__") and not isinstance(m, dict)
                    else (_redact_dict(m) if isinstance(m, dict) else {"mission": _redact(str(m))})
                    for m in items
                ]
                sec.summary = f"{len(list(missions))} active mission(s)"
                sec.status = "ok"
            else:
                sec.status = "empty"
                sec.summary = "No active missions."
        except Exception as e:
            sec.status = "degraded"
            sec.warnings.append(f"missions section error: {e}")
            logger.warning("ContextAggregator: missions section failed: %s", e)

        return sec

    def _section_project_state(self) -> ContextSection:
        sec = ContextSection(name="project_state", title="Project State", priority=40, source="config")
        try:
            from igris.models.config import CONFIG
            info: dict[str, Any] = {
                "project_root": str(self.project_root),
                "app": getattr(CONFIG, "app_name", "IGRIS_GPT"),
            }
            try:
                safe = CONFIG.safe_dict()
                info.update({k: v for k, v in safe.items()
                              if k in ("app_name", "version", "environment", "log_level")})
            except Exception:
                pass
            sec.items = [_redact_dict(info)]
            sec.summary = f"Project: {info.get('app', 'IGRIS_GPT')} at {info.get('project_root', '?')}"
            sec.status = "ok"
        except Exception as e:
            sec.status = "degraded"
            sec.warnings.append(f"project_state error: {e}")
            logger.warning("ContextAggregator: project_state section failed: %s", e)
        return sec

    def _section_git_state(self) -> ContextSection:
        sec = ContextSection(name="git_state", title="Git State", priority=45, source="git")
        try:
            def _run(cmd: list[str]) -> str:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                                   cwd=str(self.project_root))
                return r.stdout.strip() if r.returncode == 0 else ""

            branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
            sha = _run(["git", "rev-parse", "--short", "HEAD"])
            dirty = _run(["git", "status", "--porcelain"])
            changed_count = len([ln for ln in dirty.split("\n") if ln.strip()]) if dirty else 0

            sec.items = [_redact_dict({
                "branch": branch or "unknown",
                "sha": sha or "unknown",
                "dirty": dirty != "",
                "changed_files": changed_count,
            })]
            sec.summary = f"Branch: {branch} | SHA: {sha} | {'dirty' if dirty else 'clean'} ({changed_count} changes)"
            sec.status = "ok" if branch else "degraded"
        except Exception as e:
            sec.status = "degraded"
            sec.warnings.append(f"git_state error: {e}")
            logger.debug("ContextAggregator: git_state section failed: %s", e)
        return sec

    def _section_rank(self) -> ContextSection:
        sec = ContextSection(name="rank_status", title="Rank & Gauntlet", priority=50, source="rank_gauntlet")
        try:
            from igris.core.rank_gauntlet import RankGauntlet
            result = RankGauntlet().run(project_root=self.project_root)
            sec.items = [_redact_dict({
                "rank": result.rank,
                "score": round(result.score, 3),
                "passed": result.passed,
                "checks_total": len(result.checks),
                "checks_passed": sum(1 for c in result.checks if c.passed),
            })]
            sec.summary = f"Rank: {result.rank} | Score: {result.score:.0%} | {'PASSED' if result.passed else 'FAILED'}"
            sec.status = "ok"
        except Exception as e:
            sec.status = "unavailable"
            sec.warnings.append(f"rank_gauntlet unavailable: {e}")
            logger.debug("ContextAggregator: rank section failed: %s", e)
        return sec

    # ── Main methods ──────────────────────────────────────────────────────────

    def build_context(
        self,
        query: str = "",
        *,
        interlocutor_id: str = "unknown",
        trust_level: str = "untrusted",
        route_decision=None,
        include_memory: bool = True,
        include_tasks: bool = True,
        include_missions: bool = True,
        include_project_state: bool = True,
        include_git_state: bool = True,
        include_rank: bool = True,
        max_items_per_section: int = 8,
        max_chars: int = 12000,
    ) -> PersonalOSBrief:
        """Build a complete PersonalOSBrief from all available context sources."""
        now = datetime.now(timezone.utc).isoformat()
        route_str = ""
        if route_decision is not None:
            route_str = getattr(route_decision, "route", "") or ""
            if hasattr(route_str, "value"):
                route_str = route_str.value

        is_blocked = getattr(route_decision, "blocked", False) if route_decision else False
        requires_approval = getattr(route_decision, "requires_approval", False) if route_decision else False

        sections: list[ContextSection] = []
        all_warnings: list[str] = []
        any_degraded = False

        # Route section (always)
        sec_route = self._section_route(route_decision)
        sections.append(sec_route)
        if sec_route.status == "degraded":
            any_degraded = True
            all_warnings.extend(sec_route.warnings)

        # Memory section
        if include_memory and not is_blocked:
            sec_mem = self._section_memory(
                query=query,
                interlocutor_id=interlocutor_id,
                trust_level=trust_level,
                route_str=route_str,
                max_items=max_items_per_section,
            )
            if requires_approval:
                sec_mem.safe_for_prompt = False
                sec_mem.summary = "Memory context suppressed — operation requires approval."
                sec_mem.items = []
            sections.append(sec_mem)
            if sec_mem.status in ("degraded", "unavailable"):
                any_degraded = True
                all_warnings.extend(sec_mem.warnings)

        # Tasks
        if include_tasks:
            sec_tasks = self._section_tasks(max_items_per_section)
            sections.append(sec_tasks)
            if sec_tasks.status in ("degraded", "unavailable"):
                any_degraded = True
                all_warnings.extend(sec_tasks.warnings)

        # Missions
        if include_missions:
            sec_missions = self._section_missions(max_items_per_section)
            sections.append(sec_missions)
            if sec_missions.status in ("degraded", "unavailable"):
                any_degraded = True
                all_warnings.extend(sec_missions.warnings)

        # Project state
        if include_project_state:
            sec_proj = self._section_project_state()
            sections.append(sec_proj)
            if sec_proj.status == "degraded":
                any_degraded = True
                all_warnings.extend(sec_proj.warnings)

        # Git state
        if include_git_state:
            sec_git = self._section_git_state()
            sections.append(sec_git)
            if sec_git.status == "degraded":
                any_degraded = True
                all_warnings.extend(sec_git.warnings)

        # Rank
        if include_rank:
            sec_rank = self._section_rank()
            sections.append(sec_rank)
            if sec_rank.status in ("degraded", "unavailable"):
                any_degraded = True
                all_warnings.extend(sec_rank.warnings)

        sections.sort(key=lambda s: s.priority)

        brief = PersonalOSBrief(
            ok=True,
            generated_at=now,
            interlocutor_id=interlocutor_id,
            trust_level=trust_level,
            route=route_str,
            query=query,
            sections=sections,
            warnings=all_warnings,
            degraded=any_degraded,
        )
        brief.brief_text = self.build_brief_text(brief, max_chars=max_chars)
        return brief

    def build_brief_text(self, brief: PersonalOSBrief, max_chars: int = 12000) -> str:
        """Build human-readable brief text from PersonalOSBrief."""
        lines = [
            "[PERSONAL OS BRIEF]",
            f"Generated: {brief.generated_at}",
            f"Interlocutor: {brief.interlocutor_id} ({brief.trust_level})",
        ]
        if brief.route:
            lines.append(f"Route: {brief.route}")
        if brief.query:
            lines.append(f"Query: {_redact(brief.query[:100])}")
        lines.append("")

        for sec in sorted(brief.sections, key=lambda s: s.priority):
            if not sec.safe_for_prompt:
                continue
            if sec.status in ("empty", "unavailable") and not sec.warnings:
                continue
            lines.append(f"## {sec.title} [{sec.status.upper()}]")
            if sec.summary:
                lines.append(_redact(sec.summary))
            for item in sec.items[:3]:
                if isinstance(item, dict):
                    for k, v in list(item.items())[:4]:
                        if k not in ("influence_report",):
                            lines.append(f"  - {k}: {_redact(str(v))}")
                else:
                    lines.append(f"  - {_redact(str(item))}")
            if sec.warnings:
                lines.append(f"  [warnings: {'; '.join(sec.warnings[:2])}]")
            lines.append("")

        if brief.warnings:
            lines.append("## Warnings")
            for w in brief.warnings[:5]:
                lines.append(f"  - {w}")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[TRUNCATED]"
        return text

    def build_prompt_context(
        self,
        query: str = "",
        *,
        interlocutor_id: str = "unknown",
        trust_level: str = "untrusted",
        route_decision=None,
        max_chars: int = 4000,
    ) -> str:
        """Build compact, prompt-safe context string for injection into LLM system prompt."""
        brief = self.build_context(
            query=query,
            interlocutor_id=interlocutor_id,
            trust_level=trust_level,
            route_decision=route_decision,
            include_rank=False,
            max_chars=max_chars,
        )
        return brief.brief_text

    def healthcheck(self) -> dict:
        """Return health status of all data sources."""
        status: dict[str, str] = {}

        mem = self._get_memory()
        if mem:
            try:
                h = mem.healthcheck()
                status["unified_memory"] = "ok" if h.get("ok") else "degraded"
            except Exception:
                status["unified_memory"] = "degraded"
        else:
            status["unified_memory"] = "unavailable"

        status["task_engine"] = "ok" if self._task_engine else "unavailable"
        status["mission_controller"] = "ok" if self._mission_controller else "unavailable"

        try:
            r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, timeout=3,
                               cwd=str(self.project_root))
            status["git"] = "ok" if r.returncode == 0 else "degraded"
        except Exception:
            status["git"] = "unavailable"

        try:
            from igris.core.rank_gauntlet import RankGauntlet  # noqa: F401
            status["rank_gauntlet"] = "ok"
        except Exception:
            status["rank_gauntlet"] = "unavailable"

        ok = all(v in ("ok", "unavailable") for v in status.values())
        return {
            "ok": ok,
            "backends": status,
            "warnings": [f"{k}: {v}" for k, v in status.items() if v == "degraded"],
        }
