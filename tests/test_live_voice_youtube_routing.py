import unittest
from unittest.mock import patch, MagicMock

from live_voice import _normalize_tool_call, _execute_tool_call
from automation import (
    ALLOWED_APPLICATIONS,
    AUTOMATION_FUNCTION_SCHEMAS,
    APPLICATION_ALIASES,
    open_application,
)


class TestLiveVoiceYouTubeRouting(unittest.TestCase):
    """Test suite for strict YouTube routing, VLC removal, and Edge browser preference."""

    def test_vlc_removed_from_allowed_applications(self):
        """Verify VLC Media Player is not in ALLOWED_APPLICATIONS and Edge is prioritized."""
        self.assertNotIn("VLC Media Player", ALLOWED_APPLICATIONS)
        self.assertEqual(ALLOWED_APPLICATIONS[0], "Edge")
        self.assertIn("Edge", ALLOWED_APPLICATIONS)
        self.assertIn("Chrome", ALLOWED_APPLICATIONS)

    def test_youtube_aliases_in_automation(self):
        """Verify youtube aliases are mapped properly."""
        self.assertEqual(APPLICATION_ALIASES.get("youtube"), "youtube")
        self.assertEqual(APPLICATION_ALIASES.get("youtube.com"), "youtube")
        self.assertEqual(APPLICATION_ALIASES.get("yt"), "youtube")

    def test_open_application_schema_directive(self):
        """Verify open_application and open_website schemas have strict directives."""
        app_schema = next(s for s in AUTOMATION_FUNCTION_SCHEMAS if s["name"] == "open_application")
        self.assertIn("NEVER use this tool for YouTube", app_schema["description"])
        self.assertIn("Microsoft Edge", app_schema["description"])

        web_schema = next(s for s in AUTOMATION_FUNCTION_SCHEMAS if s["name"] == "open_website")
        self.assertIn("ALWAYS use this tool for opening YouTube", web_schema["description"])
        self.assertIn("Microsoft Edge", web_schema["description"])

    def test_normalize_tool_call_direct_youtube_app_name(self):
        """open_application with YouTube should normalize to open_website(https://youtube.com)."""
        name, args = _normalize_tool_call("open_application", {"app_name": "YouTube"})
        self.assertEqual(name, "open_website")
        self.assertEqual(args.get("url_or_name"), "https://youtube.com")

        name, args = _normalize_tool_call("open_application", {"app_name": "youtube.com"})
        self.assertEqual(name, "open_website")
        self.assertEqual(args.get("url_or_name"), "https://youtube.com")

    def test_normalize_tool_call_vlc_hallucination_intercept(self):
        """When user context is YouTube, open_application(VLC) must normalize to open_website(YouTube)."""
        # Scenario from actual bug: Captain said "ओपन YouTube", model called VLC Media Player
        name, args = _normalize_tool_call(
            "open_application",
            {"app_name": "VLC Media Player"},
            user_context="ओपन YouTube।",
        )
        self.assertEqual(name, "open_website")
        self.assertEqual(args.get("url_or_name"), "https://youtube.com")

    def test_normalize_tool_call_chrome_hallucination_intercept(self):
        """When user context is YouTube correction, open_application(Chrome) must normalize to open_website(YouTube)."""
        # Scenario from actual bug: Captain said "मैंने YouTube ओपन करने के लिए बोला", model called Chrome
        name, args = _normalize_tool_call(
            "open_application",
            {"app_name": "Chrome"},
            user_context="मैंने YouTube ओपन करने के लिए बोला",
        )
        self.assertEqual(name, "open_website")
        self.assertEqual(args.get("url_or_name"), "https://youtube.com")

    def test_normalize_tool_call_explicit_chrome_allowed(self):
        """When Captain explicitly asks for Chrome, Chrome should be opened."""
        name, args = _normalize_tool_call(
            "open_application",
            {"app_name": "Chrome"},
            user_context="Chrome open karo",
        )
        self.assertEqual(name, "open_application")
        self.assertEqual(args.get("app_name"), "Chrome")

    def test_normalize_tool_call_generic_browser_defaults_to_edge(self):
        """When Captain asks for 'browser', it should open Edge."""
        name, args = _normalize_tool_call(
            "open_application",
            {"app_name": "browser"},
            user_context="browser open karo",
        )
        self.assertEqual(name, "open_application")
        self.assertEqual(args.get("app_name"), "Edge")

    def test_normalize_tool_call_open_website_youtube(self):
        """open_website with youtube should normalize to https://youtube.com."""
        name, args = _normalize_tool_call("open_website", {"url_or_name": "youtube"})
        self.assertEqual(name, "open_website")
        self.assertEqual(args.get("url_or_name"), "https://youtube.com")

    @patch("automation.open_website")
    def test_open_application_delegates_youtube_to_open_website(self, mock_open_website):
        """Calling open_application('YouTube') directly in automation delegates to open_website."""
        mock_open_website.return_value = MagicMock(success=True, message="Website open kar di: https://youtube.com")
        res = open_application("YouTube")
        mock_open_website.assert_called_once_with("https://youtube.com")


if __name__ == "__main__":
    unittest.main()
