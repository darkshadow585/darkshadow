"""Unit tests for Ollama Moondream local vision integration."""

import io
import json
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

from automation import (
    analyze_screen_content,
    analyze_screen_with_ollama,
    is_ollama_available,
    parse_automation_command,
)


class TestOllamaVision(unittest.TestCase):
    """Test suite for Ollama Moondream local vision capabilities."""

    def test_is_ollama_available_true(self):
        """Verify is_ollama_available returns True on 200 response."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.assertTrue(is_ollama_available("http://127.0.0.1:11434"))

    def test_is_ollama_available_false_on_error(self):
        """Verify is_ollama_available returns False when connection fails."""
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            self.assertFalse(is_ollama_available("http://127.0.0.1:11434"))

    def test_analyze_screen_with_ollama_success(self):
        """Verify analyze_screen_with_ollama parses Ollama response successfully."""
        mock_resp = MagicMock()
        payload = json.dumps({"response": "VS Code editor is open with Python code."}).encode("utf-8")
        mock_resp.read.return_value = payload
        mock_resp.__enter__.return_value = mock_resp

        dummy_img = Image.new("RGB", (200, 200), "blue")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = analyze_screen_with_ollama(
                prompt="What is on screen?",
                model="moondream",
                img=dummy_img,
            )
            self.assertTrue(res.success)
            self.assertIn("moondream", res.message)
            self.assertIn("VS Code editor is open", res.message)
            self.assertEqual(res.data.get("provider"), "ollama")

    def test_analyze_screen_fallback_to_ollama_when_no_api_key(self):
        """Verify analyze_screen_content falls back to Ollama when Gemini API key is missing."""
        dummy_img = Image.new("RGB", (100, 100), "white")
        mock_ollama_res = MagicMock()
        mock_ollama_res.success = True
        mock_ollama_res.message = "Screen par terminal open hai."
        mock_ollama_res.data = {"analysis": "Terminal open hai"}

        with patch("automation._capture_desktop_screenshot", return_value=dummy_img), \
             patch("automation.is_ollama_available", return_value=True), \
             patch("automation.analyze_screen_with_ollama", return_value=mock_ollama_res), \
             patch("config.load_settings") as mock_settings:

            s = MagicMock()
            s.api_key = None
            s.ollama_enabled = True
            s.ollama_base_url = "http://127.0.0.1:11434"
            s.ollama_vision_model = "moondream"
            s.vision_provider = "auto"
            s.ollama_timeout_seconds = 40.0
            mock_settings.return_value = s

            res = analyze_screen_content(prompt="Check active window")
            self.assertTrue(res.success)
            self.assertEqual(res, mock_ollama_res)

    def test_analyze_screen_fallback_to_ollama_when_gemini_fails(self):
        """Verify analyze_screen_content falls back to Ollama if Gemini throws 429 quota error."""
        dummy_img = Image.new("RGB", (100, 100), "white")
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED")

        mock_ollama_res = MagicMock()
        mock_ollama_res.success = True
        mock_ollama_res.message = "Ollama detected desktop browser."

        with patch("automation._capture_desktop_screenshot", return_value=dummy_img), \
             patch("automation._get_cached_genai_client", return_value=mock_client), \
             patch("automation.is_ollama_available", return_value=True), \
             patch("automation.analyze_screen_with_ollama", return_value=mock_ollama_res), \
             patch("config.load_settings") as mock_settings:

            s = MagicMock()
            s.api_key = "dummy_key"
            s.casual_model = "gemini-3.5-flash-lite"
            s.model = "gemini-3.8-flash"
            s.ollama_enabled = True
            s.ollama_base_url = "http://127.0.0.1:11434"
            s.ollama_vision_model = "moondream"
            s.vision_provider = "auto"
            s.ollama_timeout_seconds = 40.0
            mock_settings.return_value = s

            res = analyze_screen_content(prompt="What is this")
            self.assertTrue(res.success)
            self.assertEqual(res, mock_ollama_res)

    def test_parse_ollama_screen_command(self):
        """Verify parse_automation_command detects explicit ollama/local screen intent."""
        cmd1 = parse_automation_command("ollama screen dekho")
        self.assertIsNotNone(cmd1)
        self.assertEqual(cmd1.intent, "analyze_screen")
        self.assertEqual(cmd1.arguments.get("provider"), "ollama")

        cmd2 = parse_automation_command("local vision se screen analyze karo")
        self.assertIsNotNone(cmd2)
        self.assertEqual(cmd2.intent, "analyze_screen")
        self.assertEqual(cmd2.arguments.get("provider"), "ollama")


if __name__ == "__main__":
    unittest.main()
