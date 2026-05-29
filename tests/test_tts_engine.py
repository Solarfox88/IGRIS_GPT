"""Tests for igris/core/tts_engine.py (issue #530)."""
from __future__ import annotations

import wave
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igris.core.tts_engine import (
    TTSEngine,
    TTSModelConfig,
    VoiceProfile,
    _generate_silent_wav,
    select_tts_model,
)


class TestGenerateSilentWav:
    def test_returns_valid_wav_bytes(self):
        wav_bytes = _generate_silent_wav()
        assert isinstance(wav_bytes, bytes)
        assert len(wav_bytes) > 0
        # Verify it's a valid WAV
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 22050

    def test_duration_affects_length(self):
        short = _generate_silent_wav(duration_sec=0.1)
        long = _generate_silent_wav(duration_sec=1.0)
        assert len(long) > len(short)


class TestTTSEngine:
    def test_synthesize_returns_bytes_when_model_unavailable(self, tmp_path):
        """When model can't load, synthesize returns silent WAV (best-effort)."""
        cfg = TTSModelConfig(model_id=None, disabled=True)
        engine = TTSEngine(str(tmp_path), config=cfg)
        result = engine.synthesize("Hello world")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_synthesize_returns_bytes_when_transformers_missing(self, tmp_path):
        cfg = TTSModelConfig(model_id="Qwen/Qwen3-TTS-1.7B", precision="float16")
        engine = TTSEngine(str(tmp_path), config=cfg)
        with patch.dict("sys.modules", {"transformers": None}):
            result = engine.synthesize("Hello world")
        assert isinstance(result, bytes)

    def test_is_available_false_when_disabled(self, tmp_path):
        cfg = TTSModelConfig(model_id=None, disabled=True)
        engine = TTSEngine(str(tmp_path), config=cfg)
        assert engine.is_available() is False

    def test_is_available_true_when_model_set(self, tmp_path):
        cfg = TTSModelConfig(model_id="Qwen/Qwen3-TTS-1.7B", precision="float16")
        engine = TTSEngine(str(tmp_path), config=cfg)
        assert engine.is_available() is True

    def test_get_status_returns_dict(self, tmp_path):
        cfg = TTSModelConfig(model_id="Qwen/Qwen3-TTS-1.7B", precision="float16")
        engine = TTSEngine(str(tmp_path), config=cfg)
        status = engine.get_status()
        assert isinstance(status, dict)
        assert "enabled" in status
        assert "model_id" in status
        assert "available_ram_gb" in status

    def test_get_status_disabled_when_no_model(self, tmp_path):
        cfg = TTSModelConfig(model_id=None, disabled=True)
        engine = TTSEngine(str(tmp_path), config=cfg)
        status = engine.get_status()
        assert status["enabled"] is False

    def test_clone_voice_creates_profile(self, tmp_path):
        # Create a fake audio file
        audio_file = tmp_path / "sample.wav"
        audio_bytes = _generate_silent_wav()
        audio_file.write_bytes(audio_bytes)

        cfg = TTSModelConfig(model_id=None, disabled=True)
        engine = TTSEngine(str(tmp_path), config=cfg)
        profile = engine.clone_voice(str(audio_file), name="christian", description="Owner voice")

        assert profile.name == "christian"
        assert profile.description == "Owner voice"
        # Profile manifest should be on disk
        manifest = Path(tmp_path) / ".igris/voice_profiles/christian/profile.json"
        assert manifest.exists()

    def test_save_and_load_voice_profile(self, tmp_path):
        cfg = TTSModelConfig(model_id=None, disabled=True)
        engine = TTSEngine(str(tmp_path), config=cfg)

        profile = VoiceProfile(name="test_voice", profile_path="/tmp/audio.wav", description="test")
        engine.save_voice_profile(profile)
        loaded = engine.load_voice_profile("test_voice")

        assert loaded is not None
        assert loaded.name == "test_voice"
        assert loaded.description == "test"

    def test_load_nonexistent_profile_returns_none(self, tmp_path):
        cfg = TTSModelConfig(model_id=None, disabled=True)
        engine = TTSEngine(str(tmp_path), config=cfg)
        result = engine.load_voice_profile("nonexistent")
        assert result is None

    def test_list_voice_profiles_empty(self, tmp_path):
        cfg = TTSModelConfig(model_id=None, disabled=True)
        engine = TTSEngine(str(tmp_path), config=cfg)
        result = engine.list_voice_profiles()
        assert result == []

    def test_list_voice_profiles_after_save(self, tmp_path):
        cfg = TTSModelConfig(model_id=None, disabled=True)
        engine = TTSEngine(str(tmp_path), config=cfg)
        p1 = VoiceProfile(name="christian", profile_path="/tmp/a.wav")
        p2 = VoiceProfile(name="default", profile_path="/tmp/b.wav")
        engine.save_voice_profile(p1)
        engine.save_voice_profile(p2)
        profiles = engine.list_voice_profiles()
        names = [p.name for p in profiles]
        assert "christian" in names
        assert "default" in names
