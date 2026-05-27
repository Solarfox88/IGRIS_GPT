from __future__ import annotations

from typing import Dict, List

from igris.agent.mission.mission_schema import Mission


_INTENT_KEYWORDS = {
    "architecture": ("architecture", "architettura", "design"),
    "diagnosis": ("diagnosis", "diagnost", "bug", "errore", "root cause"),
    "verification": ("verification", "verifica", "test", "validate", "checked"),
    "code_change": ("code_change", "modifica", "implement", "patch", "diff"),
    "planning": ("planning", "piano", "plan", "roadmap", "steps"),
    "mixed": ("mixed", "analisi", "execution", "azione"),
}


def _extract_intent_type(mission: Mission) -> str:
    decomp = mission.context_snapshot.get("intent_decomposition", {})
    if isinstance(decomp, dict):
        intent = str(decomp.get("intent_type") or "").strip()
        if intent:
            return intent
    summary = (mission.intent_summary or "").strip()
    if summary.startswith("[") and "]" in summary:
        head = summary[1:summary.index("]")]
        return head.split("|")[0].strip() or "mixed"
    return "mixed"


def _extract_decomposition(mission: Mission) -> Dict[str, object]:
    decomp = mission.context_snapshot.get("intent_decomposition", {})
    if isinstance(decomp, dict):
        return decomp
    return {}


def evaluate_satisfaction_gate(mission: Mission) -> Dict[str, object]:
    gaps: List[str] = []
    diagnostics: List[str] = []
    if not mission.intent_summary or mission.intent_summary == "unknown":
        gaps.append("Intent summary missing")
    if not mission.final_response.strip():
        gaps.append("Final response missing")
    response = mission.final_response.lower().strip()
    intent_type = _extract_intent_type(mission)
    decomp = _extract_decomposition(mission)
    keywords = _INTENT_KEYWORDS.get(intent_type, _INTENT_KEYWORDS["mixed"])
    if response and not any(k in response for k in keywords):
        gaps.append(f"Final response does not semantically reflect intent type '{intent_type}'")

    where_items = [str(item) for item in (decomp.get("where") or []) if isinstance(item, str)]
    known_where = [item for item in where_items if item and item != "unknown"]
    if known_where and response:
        if not any(item.lower().split("/")[-1] in response for item in known_where):
            diagnostics.append("Final response does not explicitly mention known target location(s)")

    why_value = str(decomp.get("why", "unknown") or "unknown").strip().lower()
    if why_value == "unknown":
        if response and not any(
            token in response
            for token in ("unknown", "uncertain", "limite", "assumption", "clarification")
        ):
            diagnostics.append("Intent why is unknown but final response does not acknowledge uncertainty")

    strategic_passed = len(gaps) == 0
    quality_prerequisite_met = bool(mission.quality_gate_passed)
    ready_for_completion = strategic_passed and quality_prerequisite_met

    mission.satisfaction_gate_passed = strategic_passed
    return {
        "passed": strategic_passed,
        "gaps": gaps,
        "diagnostics": diagnostics,
        "quality_prerequisite_met": quality_prerequisite_met,
        "ready_for_completion": ready_for_completion,
        "intent_type": intent_type,
    }
