"""Tests for video timestamp seeking, media control playback, and vision model fallback."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from automation import (
    AutomationContext,
    parse_automation_command,
    parse_timestamp_to_seconds,
    jump_to_video_time,
    trigger_media_key,
    analyze_screen_content,
)


class TestJumpAndVision(unittest.TestCase):
    def test_parse_timestamp_to_seconds(self):
        """Verify various timestamp representations convert accurately to total seconds."""
        self.assertEqual(parse_timestamp_to_seconds("2:00"), 120)
        self.assertEqual(parse_timestamp_to_seconds("02:00"), 120)
        self.assertEqual(parse_timestamp_to_seconds("0:45"), 45)
        self.assertEqual(parse_timestamp_to_seconds("1:15:30"), 4530)
        self.assertEqual(parse_timestamp_to_seconds("2 minute"), 120)
        self.assertEqual(parse_timestamp_to_seconds("2 min 30 sec"), 150)
        self.assertEqual(parse_timestamp_to_seconds("5m20s"), 320)
        self.assertEqual(parse_timestamp_to_seconds("45s"), 45)
        self.assertEqual(parse_timestamp_to_seconds("dedh minute"), 90)
        self.assertEqual(parse_timestamp_to_seconds("dhai minute"), 150)
        self.assertEqual(parse_timestamp_to_seconds("aadha minute"), 30)
        self.assertEqual(parse_timestamp_to_seconds("120"), 120)
        self.assertIsNone(parse_timestamp_to_seconds("invalid"))
        self.assertIsNone(parse_timestamp_to_seconds(""))

    def test_jump_to_video_time_presets(self):
        """Verify standard video seek presets like start, middle, and percentage."""
        with patch("pyautogui.press") as mock_press, patch("automation._focus_browser_window") as mock_focus:
            mock_focus.return_value = True

            res = jump_to_video_time("start")
            self.assertTrue(res.success)
            mock_press.assert_called_with("0")

            res = jump_to_video_time("middle")
            self.assertTrue(res.success)
            mock_press.assert_called_with("5")

            res = jump_to_video_time("50%")
            self.assertTrue(res.success)
            mock_press.assert_called_with("5")

            res = jump_to_video_time("30%")
            self.assertTrue(res.success)
            mock_press.assert_called_with("3")

    def test_jump_to_video_time_relative(self):
        """Verify relative seek (forward/backward) presses l/j key the appropriate number of times."""
        with patch("pyautogui.press") as mock_press, patch("automation._focus_browser_window") as mock_focus:
            mock_focus.return_value = True

            res = jump_to_video_time("10s forward")
            self.assertTrue(res.success)
            self.assertEqual(res.data.get("target"), "+10s")

            res = jump_to_video_time("30 seconds aage")
            self.assertTrue(res.success)
            self.assertEqual(res.data.get("target"), "+30s")

            res = jump_to_video_time("20 seconds peeche")
            self.assertTrue(res.success)
            self.assertEqual(res.data.get("target"), "-20s")

    def test_jump_to_video_time_url_navigation(self):
        """Verify jumping to exact timestamp modifies active YouTube URL &t parameter."""
        with patch("pyautogui.hotkey") as mock_hotkey, \
             patch("pyautogui.press") as mock_press, \
             patch("pyperclip.paste") as mock_paste, \
             patch("pyperclip.copy") as mock_copy, \
             patch("automation._focus_browser_window") as mock_focus:

            mock_focus.return_value = True
            mock_paste.return_value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

            res = jump_to_video_time("2:00")
            self.assertTrue(res.success)
            self.assertEqual(res.data.get("seconds"), 120)
            self.assertEqual(res.data.get("formatted"), "2:00")
            mock_copy.assert_any_call("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120s")

    def test_parse_automation_command_jump_and_media(self):
        """Verify natural language patterns route to jump_to_video_time and trigger_media_key."""
        cmd = parse_automation_command("gaane ko 2 minute par le jao")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "jump_to_video_time")
        self.assertIn("2 minute", cmd.arguments.get("timestamp", ""))

        cmd = parse_automation_command("video ko 1:30 par jump karo")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "jump_to_video_time")
        self.assertEqual(cmd.arguments.get("timestamp"), "1:30")

        cmd = parse_automation_command("10 second aage karo")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "jump_to_video_time")

        cmd = parse_automation_command("स्टॉप")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "trigger_media_key")
        self.assertEqual(cmd.arguments.get("key"), "stop")

        cmd = parse_automation_command("stop")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "trigger_media_key")
        self.assertEqual(cmd.arguments.get("key"), "stop")

        cmd = parse_automation_command("chalu karo")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "trigger_media_key")
        self.assertEqual(cmd.arguments.get("key"), "play_pause")

        cmd = parse_automation_command("fir se play karo")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "trigger_media_key")
        self.assertEqual(cmd.arguments.get("key"), "play_pause")

    def test_trigger_media_key(self):
        """Verify trigger_media_key executes for allowed playback keys."""
        with patch("ctypes.windll.user32.keybd_event") as mock_keybd:
            res = trigger_media_key("play_pause")
            self.assertTrue(res.success)
            self.assertGreaterEqual(mock_keybd.call_count, 2)

            res = trigger_media_key("resume")
            self.assertTrue(res.success)

            res = trigger_media_key("invalid_key_xyz")
            self.assertFalse(res.success)

    def test_analyze_screen_fallback(self):
        """Verify analyze_screen_content gracefully falls back through model candidates."""
        from PIL import Image

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Screen par YouTube video chal raha hai."

        # First candidate fails with 429, second candidate succeeds
        mock_client.models.generate_content.side_effect = [
            Exception("429 RESOURCE_EXHAUSTED"),
            mock_resp,
        ]

        with patch("automation._capture_desktop_screenshot", return_value=Image.new("RGB", (100, 100), "white")), \
             patch("automation._get_cached_genai_client", return_value=mock_client), \
             patch("config.load_settings") as mock_settings:

            s = MagicMock()
            s.api_key = "dummy_key"
            s.casual_model = "gemini-3.5-flash-lite"
            s.model = "gemini-3.8-flash"
            mock_settings.return_value = s

            res = analyze_screen_content(prompt="Check video")
            self.assertTrue(res.success)
            self.assertIn("YouTube video", res.message)
            self.assertEqual(mock_client.models.generate_content.call_count, 2)


if __name__ == "__main__":
    unittest.main()
