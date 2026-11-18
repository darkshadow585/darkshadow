import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation import (
    parse_automation_command,
    parsed_command_from_tool_call,
    vision_browser_goal,
    AUTOMATION_FUNCTION_SCHEMAS,
    _AUTOMATION_FUNCTIONS,
)
from browser_engine import DarkShadowBrowserEngine, get_browser_engine
from config import Settings, load_settings


class TestLevel3BrowserAutomation(unittest.TestCase):

    def test_settings_browser_config(self):
        s = load_settings()
        self.assertTrue(hasattr(s, "browser_user_data_dir"))
        self.assertTrue(hasattr(s, "browser_stealth_enabled"))
        self.assertTrue(hasattr(s, "browser_vision_enabled"))
        self.assertTrue(s.browser_stealth_enabled)
        self.assertTrue(s.browser_vision_enabled)
        self.assertIn("browser_profile", str(s.browser_user_data_dir))

    def test_browser_engine_initialization(self):
        engine = DarkShadowBrowserEngine(
            headless=True,
            user_data_dir=Path(".darkshadow/test_profile"),
            stealth=True,
        )
        self.assertTrue(engine.headless)
        self.assertTrue(engine.stealth)
        self.assertEqual(engine.user_data_dir, Path(".darkshadow/test_profile"))

    def test_vision_browser_goal_schema_registration(self):
        schema = next((s for s in AUTOMATION_FUNCTION_SCHEMAS if s["name"] == "vision_browser_goal"), None)
        self.assertIsNotNone(schema)
        self.assertIn("goal", schema["parameters"]["required"])
        self.assertIn("vision_browser_goal", _AUTOMATION_FUNCTIONS)

    def test_parse_automation_command_vision_browser(self):
        q1 = "page par add to cart click karo"
        res1 = parse_automation_command(q1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.intent, "vision_browser_goal")
        self.assertIn("add to cart", res1.arguments["goal"].lower())

        q2 = "browser me close popup karo"
        res2 = parse_automation_command(q2)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.intent, "vision_browser_goal")
        self.assertIn("close popup", res2.arguments["goal"].lower())

        q3 = "webpage par submit button visually click karo"
        res3 = parse_automation_command(q3)
        self.assertIsNotNone(res3)
        self.assertEqual(res3.intent, "vision_browser_goal")
        self.assertIn("submit button", res3.arguments["goal"].lower())

    def test_parsed_command_from_tool_call(self):
        cmd = parsed_command_from_tool_call(
            "vision_browser_goal",
            {"goal": "Click checkout button", "url": "https://example.com"},
        )
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "vision_browser_goal")
        self.assertEqual(cmd.arguments["goal"], "Click checkout button")
        self.assertEqual(cmd.arguments["url"], "https://example.com")

    def test_vision_execute_goal_with_gemini(self):
        engine = DarkShadowBrowserEngine(headless=True)
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.screenshot.return_value = b"fake_jpeg_bytes"

        # Mock Set-of-Marks mapping
        marks = {
            "1": {"tag": "button", "text": "Add to Cart", "x": 500, "y": 600, "width": 100, "height": 40},
            "2": {"tag": "a", "text": "Customer Reviews", "x": 200, "y": 800, "width": 150, "height": 20},
        }

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"mark_id": 1, "action": "click", "reasoning": "Mark 1 is Add to Cart", "goal_achieved": false}'
        mock_client.models.generate_content.return_value = mock_resp

        with patch.object(engine, "is_installed", return_value=True), \
             patch.object(engine, "_ensure_page", return_value=mock_page), \
             patch.object(engine, "inject_set_of_marks", return_value=marks), \
             patch.object(engine, "clear_set_of_marks") as mock_clear, \
             patch.object(engine, "click_mark", return_value={"success": True, "mark_id": "1"}):

            res = engine.vision_execute_goal(
                goal="Click Add to Cart",
                gemini_api_key="test_key",
                client=mock_client,
                max_steps=1,
            )
            self.assertTrue(res["success"])
            self.assertEqual(len(res["steps"]), 1)
            self.assertEqual(str(res["steps"][0]["mark_id"]), "1")
            self.assertEqual(res["steps"][0]["action"], "click")
            mock_clear.assert_called()

    def test_vision_browser_goal_automation_result(self):
        mock_engine = MagicMock()
        mock_engine.vision_execute_goal.return_value = {
            "success": True,
            "message": "Clicked Add to Cart button successfully via Gemini 3.8 Flash visual locator.",
            "steps": [{"step": 1, "mark_id": 1}],
        }

        with patch("browser_engine.get_browser_engine", return_value=mock_engine):
            res = vision_browser_goal("Click Add to Cart")
            self.assertTrue(res.success)
            self.assertEqual(res.action, "vision_browser_goal")
            self.assertIn("Captain", res.message)
            self.assertIn("Clicked Add to Cart", res.message)


if __name__ == "__main__":
    unittest.main()
