"""Unit tests for Gemini Live Voice-to-Voice (V2V) integration in ui.py."""

import unittest
from unittest.mock import MagicMock, patch

from config import load_settings


class TestUIV2VIntegration(unittest.TestCase):
    """Test suite ensuring V2V operates cleanly with ui.py."""

    def setUp(self) -> None:
        self.settings = load_settings()

    def test_01_live_voice_thread_signals_and_init(self) -> None:
        """Verify LiveVoiceThread instantiates with all required Qt signals."""
        from ui import LiveVoiceThread

        thread = LiveVoiceThread(self.settings)
        self.assertFalse(thread.isRunning())
        self.assertFalse(thread._stop_requested)
        self.assertTrue(hasattr(thread, "state_changed"))
        self.assertTrue(hasattr(thread, "audio_level_changed"))
        self.assertTrue(hasattr(thread, "user_transcript_received"))
        self.assertTrue(hasattr(thread, "model_transcript_received"))
        self.assertTrue(hasattr(thread, "tool_executed"))
        self.assertTrue(hasattr(thread, "error_occurred"))

    def test_02_controller_toggles_live_voice(self) -> None:
        """Verify request_microphone toggles start and stop of LiveVoiceThread."""
        from ui import IntegratedAssistantController

        mock_window = MagicMock()
        mock_chatbot = MagicMock()

        controller = IntegratedAssistantController(
            mock_window,
            settings=self.settings,
            chatbot=mock_chatbot,
        )

        try:
            self.assertFalse(controller.is_live_voice_active)

            # Start Live Voice
            with patch("ui.LiveVoiceThread.start") as mock_start:
                controller.request_microphone()
                self.assertIsNotNone(controller._live_voice_thread)
                mock_start.assert_called_once()
                mock_window.set_state.assert_called_with("listening", "Connecting to Gemini Live…")

            # Mock thread running
            controller._live_voice_thread.isRunning = MagicMock(return_value=True)
            controller._live_voice_thread.stop = MagicMock()
            controller._live_voice_thread.wait = MagicMock()

            self.assertTrue(controller.is_live_voice_active)

            # Stop Live Voice
            controller.request_microphone()
            self.assertFalse(controller.is_live_voice_active)
            mock_window.set_state.assert_called_with("idle", "Ready")
        finally:
            controller.close()
            controller.thread.quit()
            controller.thread.wait(500)

    def test_03_submit_command_stops_active_live_voice(self) -> None:
        """Verify typing a text command automatically closes active live voice session."""
        from ui import IntegratedAssistantController

        mock_window = MagicMock()
        mock_chatbot = MagicMock()

        controller = IntegratedAssistantController(
            mock_window,
            settings=self.settings,
            chatbot=mock_chatbot,
        )

        try:
            # Simulate active live voice
            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = True
            controller._live_voice_thread = mock_thread

            self.assertTrue(controller.is_live_voice_active)

            # Submitting text command should stop live voice
            controller.submit_command("test text command")
            mock_thread.stop.assert_called_once()
            self.assertFalse(controller.is_live_voice_active)
        finally:
            controller.close()
            controller.thread.quit()
            controller.thread.wait(500)


if __name__ == "__main__":
    unittest.main()
