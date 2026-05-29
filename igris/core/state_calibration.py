"""
State Calibration — Layer 6 of the Interlocutor-Aware system (issue #526).

Detects emotional/cognitive state of the interlocutor from message signals.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


_URGENCY_WORDS = frozenset([
    "adesso", "subito", "urgente", "urgent", "asap", "now", "immediately",
    "ora", "quick", "fast", "hurry", "emergency", "critical",
])
_FRUSTRATION_WORDS = frozenset([
    "ancora", "di nuovo", "sempre", "solito", "again", "still",
    "non funziona", "non va", "broke", "broken", "doesn't work", "failed again",
    "perche", "why", "impossible",
])
_CONFUSION_WORDS = frozenset([
    "non capisco", "confused", "what", "cosa", "come", "how", "which",
    "don't understand", "help", "explain", "unclear",
])
_MULTI_PUNCT = re.compile(r"[!?]{2,}")
_CAPS_RATIO = 0.4


@dataclass
class StateSignal:
    state: str        # "routine" | "urgency" | "frustration" | "confusion"
    confidence: float
    signals: list

    @property
    def is_routine(self) -> bool:
        return self.state == "routine"

    @property
    def is_urgent(self) -> bool:
        return self.state == "urgency"

    @property
    def is_frustrated(self) -> bool:
        return self.state == "frustration"

    @property
    def is_confused(self) -> bool:
        return self.state == "confusion"


@dataclass
class ResponseMode:
    verbosity: str        # "minimal" | "normal" | "detailed"
    tone: str             # "empathetic" | "direct" | "formal" | "casual"
    lead_with_action: bool = False
    use_bullet_points: bool = False
    simplify_language: bool = False


class StateCalibration:
    """Layer 6: detect state and select response mode."""

    def detect(self, message: str) -> StateSignal:
        signals: List[str] = []
        lower = message.lower()
        words = lower.split()

        urgency_hits = [w for w in words if w.strip(".,!?:;") in _URGENCY_WORDS]
        multi_punct = bool(_MULTI_PUNCT.search(message))
        upper_words = [w for w in message.split() if w.isupper() and len(w) > 2]
        caps_heavy = len(upper_words) / max(len(message.split()), 1) >= _CAPS_RATIO
        short_message = len(message.strip()) < 30

        if urgency_hits:
            signals.extend([f"urgency_word:{w}" for w in urgency_hits])
        if multi_punct:
            signals.append("multi_punct")
        if caps_heavy:
            signals.append("caps_heavy")

        urgency_score = (
            len(urgency_hits) * 0.4
            + (0.3 if multi_punct else 0)
            + (0.2 if caps_heavy else 0)
            + (0.1 if short_message else 0)
        )

        frustration_hits = []
        for phrase in _FRUSTRATION_WORDS:
            if phrase in lower:
                frustration_hits.append(phrase)
        if frustration_hits:
            signals.extend([f"frustration_phrase:{p}" for p in frustration_hits])

        frustration_score = min(len(frustration_hits) * 0.5, 1.0)

        confusion_hits = [w for w in words if w.strip(".,!?:;") in _CONFUSION_WORDS]
        question_marks = message.count("?")
        if confusion_hits:
            signals.extend([f"confusion_word:{w}" for w in confusion_hits])

        confusion_score = (
            len(confusion_hits) * 0.35
            + min(question_marks * 0.15, 0.45)
        )

        scores = {
            "urgency": urgency_score,
            "frustration": frustration_score,
            "confusion": confusion_score,
            "routine": 0.1,
        }
        dominant = max(scores, key=scores.__getitem__)
        confidence = min(scores[dominant], 1.0)

        if confidence < 0.2:
            dominant = "routine"
            confidence = 1.0

        return StateSignal(state=dominant, confidence=confidence, signals=signals)

    def select_response_mode(
        self,
        signal: StateSignal,
        communication_style: str = "technical",
        expertise_level: str = "intermediate",
    ) -> ResponseMode:
        if signal.is_urgent:
            return ResponseMode(
                verbosity="minimal",
                tone="direct",
                lead_with_action=True,
                use_bullet_points=True,
                simplify_language=False,
            )
        if signal.is_frustrated:
            return ResponseMode(
                verbosity="normal",
                tone="empathetic",
                lead_with_action=False,
                use_bullet_points=True,
                simplify_language=(expertise_level in ("novice", "intermediate")),
            )
        if signal.is_confused:
            return ResponseMode(
                verbosity="detailed",
                tone="empathetic",
                lead_with_action=False,
                use_bullet_points=True,
                simplify_language=True,
            )

        verbosity = "normal"
        if expertise_level in ("expert", "owner"):
            verbosity = "minimal"
        elif expertise_level == "novice":
            verbosity = "detailed"

        tone_map = {
            "formal": "formal",
            "casual": "casual",
            "technical": "direct",
        }
        tone = tone_map.get(communication_style, "direct")

        return ResponseMode(
            verbosity=verbosity,
            tone=tone,
            lead_with_action=False,
            use_bullet_points=(expertise_level in ("novice",)),
            simplify_language=(expertise_level == "novice"),
        )
