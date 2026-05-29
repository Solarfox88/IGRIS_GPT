"""Tests for igris/core/tts_router.py (issue #530)."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from igris.core.tts_router import TTSRouter


class TestTTSRouter:
    def test_disabled_via_env_returns_false(self):
        with patch.dict("os.environ", {"IGRIS_TTS_ENABLED": "false"}):
            router = TTSRouter()
            decision = router.should_vocalize("chat_response", "Hello")
        assert decision.should_speak is False
        assert decision.reason == "tts_disabled"

    def test_disabled_explicit_returns_false(self):
        router = TTSRouter(enabled=False)
        decision = router.should_vocalize("mission_complete", "Done")
        assert decision.should_speak is False

    def test_empty_text_returns_false(self):
        router = TTSRouter(enabled=True)
        decision = router.should_vocalize("chat_response", "")
        assert decision.should_speak is False
        assert decision.reason == "empty_text"

    def test_always_speak_trigger_speaks(self):
        router = TTSRouter(enabled=True)
        decision = router.should_vocalize("mission_complete", "All done!")
        assert decision.should_speak is True

    def test_conditional_trigger_speaks(self):
        router = TTSRouter(enabled=True)
        decision = router.should_vocalize("chat_response", "Here is my response.")
        assert decision.should_speak is True

    def test_unknown_trigger_does_not_speak(self):
        router = TTSRouter(enabled=True)
        decision = router.should_vocalize("random_event", "Some text")
        assert decision.should_speak is False
        assert decision.reason == "trigger_not_vocalized"

    def test_rate_limit_blocks_conditional_trigger(self):
        router = TTSRouter(enabled=True, max_per_minute=2)
        router.should_vocalize("chat_response", "msg1")
        router.should_vocalize("chat_response", "msg2")
        decision = router.should_vocalize("chat_response", "msg3")
        assert decision.should_speak is False
        assert decision.reason == "rate_limited"

    def test_always_speak_bypasses_rate_limit(self):
        router = TTSRouter(enabled=True, max_per_minute=1)
        router.should_vocalize("chat_response", "fill the limit")
        # Now rate limited — but mission_complete should bypass
        decision = router.should_vocalize("mission_complete", "Done!")
        assert decision.should_speak is True
        assert "bypass" in decision.reason

    def test_current_rate_increments(self):
        router = TTSRouter(enabled=True)
        assert router.current_rate() == 0
        router.should_vocalize("chat_response", "msg")
        assert router.current_rate() == 1

    def test_rate_window_resets_after_60s(self):
        router = TTSRouter(enabled=True, max_per_minute=2)
        # Add two old timestamps (more than 60s ago)
        old_time = time.time() - 65
        router._timestamps.append(old_time)
        router._timestamps.append(old_time)
        # After pruning, rate should be 0, so next call should succeed
        decision = router.should_vocalize("chat_response", "fresh msg")
        assert decision.should_speak is True

    def test_alert_trigger_always_speaks(self):
        router = TTSRouter(enabled=True)
        decision = router.should_vocalize("alert", "CRITICAL: server down!")
        assert decision.should_speak is True

    def test_supervisor_blocked_always_speaks(self):
        router = TTSRouter(enabled=True)
        decision = router.should_vocalize("supervisor_blocked", "Blocked.")
        assert decision.should_speak is True

    def test_max_per_minute_from_env(self):
        with patch.dict("os.environ", {"IGRIS_TTS_MAX_PER_MINUTE": "3"}):
            router = TTSRouter(enabled=True)
        assert router.max_per_minute == 3
