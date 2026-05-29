"""
TTS Router — decides when IGRIS speaks and applies rate limiting (issue #530).

Not every response is vocalized. Trigger conditions are:
- chat response (if configured)
- mission completion
- SMW alert / supervisor event
- heartbeat notification

Rate limiting: max N syntheses/minute. Configurable via IGRIS_TTS_MAX_PER_MINUTE.
"""
from __future__ import annotations

import collections
import os
import time
from dataclasses import dataclass
from typing import Deque, Optional

_DEFAULT_MAX_PER_MINUTE = 10

# Trigger types that always result in TTS output
_ALWAYS_SPEAK_TRIGGERS = frozenset([
    "mission_complete",
    "alert",
    "critical_failure",
    "supervisor_blocked",
])

# Trigger types that speak if TTS is enabled and not rate-limited
_CONDITIONAL_TRIGGERS = frozenset([
    "chat_response",
    "heartbeat",
    "status_update",
    "advisory",
])


@dataclass
class TTSDecision:
    """Result of the TTS router decision."""
    should_speak: bool
    reason: str


class TTSRouter:
    """Decides whether to vocalize a given event.

    Usage:
        router = TTSRouter()
        decision = router.should_vocalize("mission_complete", text="All done.")
        if decision.should_speak:
            audio = engine.synthesize(text)
    """

    def __init__(
        self,
        max_per_minute: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        if enabled is None:
            env_val = os.getenv("IGRIS_TTS_ENABLED", "true").lower()
            enabled = env_val not in ("false", "0", "no")
        self.enabled = enabled

        if max_per_minute is None:
            try:
                max_per_minute = int(os.getenv("IGRIS_TTS_MAX_PER_MINUTE", str(_DEFAULT_MAX_PER_MINUTE)))
            except (ValueError, TypeError):
                max_per_minute = _DEFAULT_MAX_PER_MINUTE
        self.max_per_minute = max_per_minute

        # Sliding window of synthesis timestamps (last 60 seconds)
        self._timestamps: Deque[float] = collections.deque()

    def _prune_window(self) -> None:
        """Remove timestamps older than 60 seconds from the window."""
        cutoff = time.time() - 60.0
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def _is_rate_limited(self) -> bool:
        self._prune_window()
        return len(self._timestamps) >= self.max_per_minute

    def _record(self) -> None:
        self._timestamps.append(time.time())

    def should_vocalize(self, trigger: str, text: str = "") -> TTSDecision:
        """Decide whether to speak given this trigger.

        Args:
            trigger: Event type string (e.g. "mission_complete", "chat_response").
            text: The text to be spoken (used for length check).

        Returns:
            TTSDecision with should_speak and reason.
        """
        if not self.enabled:
            return TTSDecision(should_speak=False, reason="tts_disabled")

        if not text.strip():
            return TTSDecision(should_speak=False, reason="empty_text")

        is_always = trigger in _ALWAYS_SPEAK_TRIGGERS
        is_conditional = trigger in _CONDITIONAL_TRIGGERS

        if not is_always and not is_conditional:
            return TTSDecision(should_speak=False, reason="trigger_not_vocalized")

        if self._is_rate_limited():
            if is_always:
                # Always-speak triggers bypass rate limit
                self._record()
                return TTSDecision(should_speak=True, reason="always_speak_bypass_rate_limit")
            return TTSDecision(should_speak=False, reason="rate_limited")

        self._record()
        return TTSDecision(should_speak=True, reason=f"trigger:{trigger}")

    def current_rate(self) -> int:
        """Return number of syntheses in the last 60 seconds."""
        self._prune_window()
        return len(self._timestamps)
