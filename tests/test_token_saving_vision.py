"""Unit tests for Token-Saving Vision Architecture (Jugaad 1, 2, and 3).

Verifies:
1. ScreenDeltaDetector correctly identifies identical vs changed frames.
2. Frame skipping when screen delta is below threshold (0 tokens).
3. Force flag bypasses threshold for explicit analyze_screen tool requests.
4. Statistics tracking (tokens saved, frames skipped).
5. Accessibility tree UIA context generation (structured text control representation).
6. LiveVoiceSession.send_screen_frame delta shield and transmission behavior.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image

from config import load_settings
from desktop_engine import DesktopControl, ScreenDeltaDetector, WindowsUIAutomationEngine


class TestScreenDeltaDetector(unittest.TestCase):
    """Test CPU-based pixel delta differencing and token-saving metrics."""

    def setUp(self) -> None:
        self.detector = ScreenDeltaDetector(threshold=0.08, thumbnail_size=(64, 64))

    def test_identical_images_produce_zero_delta_and_skip(self) -> None:
        # Create solid red image
        img1 = Image.new("RGB", (200, 200), color=(255, 0, 0))
        img2 = Image.new("RGB", (200, 200), color=(255, 0, 0))

        # First frame should always send
        send1, delta1 = self.detector.should_send_frame(img1)
        self.assertTrue(send1)
        self.assertEqual(delta1, 1.0)

        # Second frame (identical) should be skipped (0 tokens)
        send2, delta2 = self.detector.should_send_frame(img2)
        self.assertFalse(send2)
        self.assertEqual(delta2, 0.0)

    def test_different_images_exceed_threshold_and_send(self) -> None:
        # White image then Black image (100% pixel change)
        img_white = Image.new("RGB", (100, 100), color=(255, 255, 255))
        img_black = Image.new("RGB", (100, 100), color=(0, 0, 0))

        send1, _ = self.detector.should_send_frame(img_white)
        self.assertTrue(send1)

        send2, delta2 = self.detector.should_send_frame(img_black)
        self.assertTrue(send2)
        self.assertGreater(delta2, 0.08)

    def test_force_flag_bypasses_delta_check(self) -> None:
        img = Image.new("RGB", (100, 100), color=(128, 128, 128))

        send1, _ = self.detector.should_send_frame(img)
        self.assertTrue(send1)

        # Identical image with force=True must still send
        send2, delta2 = self.detector.should_send_frame(img, force=True)
        self.assertTrue(send2)
        self.assertEqual(delta2, 1.0)

    def test_statistics_and_token_savings(self) -> None:
        img1 = Image.new("RGB", (100, 100), color=(50, 50, 50))
        img2 = Image.new("RGB", (100, 100), color=(50, 50, 50))

        # Check 1 initial frame + 3 identical frames
        self.detector.should_send_frame(img1)
        self.detector.should_send_frame(img2)
        self.detector.should_send_frame(img2)
        self.detector.should_send_frame(img2)

        stats = self.detector.stats
        self.assertEqual(stats["frames_checked"], 4)
        self.assertEqual(stats["frames_sent"], 1)
        self.assertEqual(stats["frames_skipped"], 3)
        # 3 skipped frames * 258 tokens = 774 tokens saved
        self.assertEqual(stats["tokens_saved_approx"], 3 * 258)
        self.assertEqual(stats["saving_percentage"], 75.0)

    def test_reset_clears_history(self) -> None:
        img = Image.new("RGB", (100, 100), color=(100, 100, 100))
        self.detector.should_send_frame(img)
        self.detector.reset()
        self.assertIsNone(self.detector._last_thumbnail_bytes)
        # Next frame is treated as first frame
        send, delta = self.detector.should_send_frame(img)
        self.assertTrue(send)
        self.assertEqual(delta, 1.0)


class TestAccessibilityTreeContext(unittest.TestCase):
    """Test Jugaad 3: structured text UI representation over heavy vision."""

    def test_get_active_window_context_formatting(self) -> None:
        engine = WindowsUIAutomationEngine()

        sample_controls = [
            DesktopControl(name="File", control_type="Button"),
            DesktopControl(name="Edit", control_type="Button"),
            DesktopControl(name="Editor Content", control_type="Edit"),
        ]

        with patch.object(engine, "get_active_window_title", return_value="Untitled - Notepad"), \
             patch.object(engine, "list_window_controls", return_value=sample_controls):
            context = engine.get_active_window_context()
            self.assertIn('Active Window: "Untitled - Notepad"', context)
            self.assertIn('[Button] "File"', context)
            self.assertIn('[Edit] "Editor Content"', context)

    def test_inspect_active_window_includes_context_summary(self) -> None:
        engine = WindowsUIAutomationEngine()

        sample_controls = [
            DesktopControl(name="Search", control_type="Button"),
        ]

        with patch.object(engine, "get_active_window_title", return_value="Settings"), \
             patch.object(engine, "list_window_controls", return_value=sample_controls):
            info = engine.inspect_active_window()
            self.assertIn("context_summary", info)
            self.assertIn("Settings", info["context_summary"])
            self.assertIn('[Button] "Search"', info["context_summary"])


class TestLiveVoiceVisionIntegration(unittest.IsolatedAsyncioTestCase):
    """Test LiveVoiceSession send_screen_frame delta shield and tool fallbacks."""

    async def test_send_screen_frame_skips_identical_screen(self) -> None:
        from live_voice import LiveVoiceSession

        settings = load_settings()
        mock_output = MagicMock()
        session_obj = LiveVoiceSession(settings, output_fn=mock_output)

        mock_gemini_session = AsyncMock()
        mock_gemini_session.send_realtime_input = AsyncMock()

        test_img = Image.new("RGB", (400, 300), color=(30, 60, 90))

        with patch("automation._capture_desktop_screenshot", return_value=test_img):
            # 1st call: Should send frame (image blob + optional UIA text context)
            res1 = await session_obj.send_screen_frame(mock_gemini_session, force=False)
            self.assertTrue(res1)
            first_call_count = mock_gemini_session.send_realtime_input.call_count
            self.assertGreaterEqual(first_call_count, 1)  # At least 1 (image), maybe 2 (image + UIA text)

            # 2nd call (same image): Screen delta shield should skip sending!
            res2 = await session_obj.send_screen_frame(mock_gemini_session, force=False)
            self.assertTrue(res2)
            # Call count should NOT increase (second transmission was skipped, 0 tokens!)
            self.assertEqual(mock_gemini_session.send_realtime_input.call_count, first_call_count)

            # 3rd call with force=True: Must send frame even if identical
            res3 = await session_obj.send_screen_frame(mock_gemini_session, force=True)
            self.assertTrue(res3)
            # Call count should increase beyond first_call_count
            self.assertGreater(mock_gemini_session.send_realtime_input.call_count, first_call_count)

    def test_execute_tool_call_desktop_context(self) -> None:
        from live_voice import _execute_tool_call

        with patch("automation.inspect_desktop_window") as mock_inspect:
            from automation import AutomationResult
            mock_inspect.return_value = AutomationResult(
                True,
                "desktop_control_action",
                "Captain, active window inspect ho gayi.",
                {"context_summary": 'Active Window: "VS Code"'},
            )

            res = _execute_tool_call("get_active_window_context", {})
            self.assertEqual(res["status"], "ok")
            self.assertIn("data", res)


if __name__ == "__main__":
    unittest.main()
