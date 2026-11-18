"""Tests for OpenAI Realtime Live Voice configuration and session logic."""

import unittest
from unittest.mock import MagicMock, patch

from config import Settings
from openai_realtime import (
    OpenAIRealtimeSession,
    OPENAI_VALID_VOICES,
    OPENAI_MIC_SAMPLE_RATE,
)


class TestOpenAIRealtime(unittest.TestCase):
    def test_config_openai_settings(self):
        settings = Settings(
            api_key="test_key",
            openai_api_key="sk-test-openai-12345",
            live_provider="openai",
            live_model="gpt-realtime-2.1",
            live_voice="ash",
        )
        self.assertTrue(settings.openai_configured)
        self.assertEqual(settings.live_provider, "openai")
        self.assertEqual(settings.live_model, "gpt-realtime-2.1")
        self.assertEqual(settings.live_voice, "ash")

    def test_session_init_and_tool_schema(self):
        settings = Settings(
            api_key="test_key",
            openai_api_key="sk-test-openai-12345",
            live_provider="openai",
            live_model="gpt-realtime-2.1",
            live_voice="ballad",
        )
        fake_pa = MagicMock()
        session = OpenAIRealtimeSession(settings, pyaudio_module=fake_pa)

        self.assertEqual(OPENAI_MIC_SAMPLE_RATE, 24000)
        tools = session._build_tools_schema()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 5)

        # Check tool format conforms to OpenAI standard
        for t in tools:
            self.assertEqual(t["type"], "function")
            self.assertIn("name", t)
            self.assertIn("parameters", t)

        session.close()

    def test_live_voice_delegation_to_openai(self):
        from live_voice import LiveVoiceSession

        settings = Settings(
            api_key="test_key",
            openai_api_key="sk-test-openai-12345",
            live_provider="openai",
            live_model="gpt-realtime-2.1",
            live_voice="ash",
        )
        fake_pa = MagicMock()
        live_session = LiveVoiceSession(settings, pyaudio_module=fake_pa)

        self.assertIsNotNone(live_session._openai_session)
        self.assertIsInstance(live_session._openai_session, OpenAIRealtimeSession)
        live_session.close()


if __name__ == "__main__":
    unittest.main()
