"""Tests for DarkShadow Deep Male Voice Persona and Settings."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Settings, load_settings


class TestDeepMaleVoice(unittest.TestCase):

    def test_settings_deep_male_defaults(self):
        """Verify default voice persona settings resolve to deep male baritone."""
        s = load_settings()
        self.assertEqual(s.tts_voice, "hi-IN-MadhurNeural")
        self.assertEqual(s.tts_english_voice, "en-IN-PrabhatNeural")
        self.assertIn("-5Hz", s.tts_pitch)
        self.assertEqual(s.tts_gemini_voice, "Charon")
        self.assertIn(s.live_voice, {"Charon", "Puck", "Fenrir", "Orus", "ash"})

    def test_empty_env_fallback_to_deep_male(self):
        """Even with empty environment dictionary, fallbacks should be deep male."""
        with patch.dict("os.environ", {}, clear=True):
            s = Settings(api_key="test_key")
            self.assertEqual(s.tts_voice, "hi-IN-MadhurNeural")
            self.assertEqual(s.tts_english_voice, "en-IN-PrabhatNeural")
            self.assertEqual(s.tts_pitch, "-5Hz")
            self.assertEqual(s.live_voice, "Charon")
