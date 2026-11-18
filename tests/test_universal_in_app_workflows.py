"""Unit tests for Universal In-App Search, Same-Tab YouTube Search, and Multi-Level Workflows."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from automation import (
    parse_automation_command,
    search_youtube,
    search_in_active_app,
)
from desktop_workflow_agent import UniversalInAppOperator
from skill import get_skill_registry


class TestUniversalInAppWorkflows(unittest.TestCase):
    """Test suite verifying cross-app multi-level workflows and tab preservation."""

    def setUp(self) -> None:
        self.registry = get_skill_registry()

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("youtube", 12345, "YouTube - Google Chrome"))
    @patch("pyautogui.press")
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    def test_youtube_in_page_search_same_tab(self, mock_copy, mock_hotkey, mock_press, mock_fg):
        """Verify YouTube search uses in-page search bar without opening duplicate tabs."""
        result = UniversalInAppOperator.search_in_active_or_open_app("arijit singh live song")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "youtube_in_page_search")
        self.assertEqual(result["app"], "youtube")
        self.assertTrue(result["same_tab"])
        self.assertIn("arijit singh live song", result["query"])

        mock_press.assert_any_call("enter")
        mock_hotkey.assert_any_call("ctrl", "l")
        mock_hotkey.assert_any_call("ctrl", "v")
        self.assertTrue(mock_copy.called)
        self.assertIn("youtube.com/results?search_query=", mock_copy.call_args[0][0])

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("notepad", 1111, "Untitled - Notepad"))
    @patch.object(UniversalInAppOperator, "find_open_app_window", return_value=(9999, "Arijit Singh - YouTube - Brave"))
    @patch.object(UniversalInAppOperator, "bring_to_foreground", return_value=True)
    @patch("pyautogui.press")
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    def test_youtube_target_brings_existing_window_to_foreground(
        self, mock_copy, mock_hotkey, mock_press, mock_bring, mock_find, mock_fg
    ):
        """When targeting YouTube specifically, an existing window should be focused without new tab."""
        result = UniversalInAppOperator.search_in_active_or_open_app("kesariya", target_app="youtube")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "youtube_in_page_search")
        self.assertTrue(result["same_tab"])
        mock_find.assert_called_with("youtube")
        mock_bring.assert_called_with(9999)

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("spotify", 2222, "Spotify Free"))
    @patch("pyautogui.press")
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    def test_spotify_in_app_search(self, mock_copy, mock_hotkey, mock_press, mock_fg):
        """Verify Spotify search uses native Ctrl+K in-app shortcut."""
        result = UniversalInAppOperator.search_in_active_or_open_app("Arijit Singh")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "spotify_in_app_search")
        self.assertEqual(result["app"], "spotify")
        mock_hotkey.assert_any_call("ctrl", "k")
        mock_copy.assert_called_with("Arijit Singh")

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("vscode", 3333, "darkshadow - Visual Studio Code"))
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    def test_vscode_in_editor_search(self, mock_copy, mock_hotkey, mock_fg):
        """Verify VS Code uses Ctrl+P quick open/search shortcut."""
        result = UniversalInAppOperator.search_in_active_or_open_app("desktop_workflow_agent.py")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "vscode_in_editor_search")
        self.assertEqual(result["app"], "vscode")
        mock_hotkey.assert_any_call("ctrl", "p")

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("explorer", 4444, "Downloads - File Explorer"))
    @patch("pyautogui.press")
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    def test_explorer_in_folder_search(self, mock_copy, mock_hotkey, mock_press, mock_fg):
        """Verify File Explorer uses Ctrl+E in-folder search."""
        result = UniversalInAppOperator.search_in_active_or_open_app("report.pdf")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "explorer_in_folder_search")
        self.assertEqual(result["app"], "explorer")
        mock_hotkey.assert_any_call("ctrl", "e")

    def test_parse_contextual_in_app_search_commands(self):
        """Test parsing of 'is par', 'ispe', 'isme', 'is tab me' search phrases."""
        test_cases = [
            ("is par arijit singh live song search karo", "arijit singh live song"),
            ("ispe pagal dhoondo", "pagal"),
            ("isme python code search karo", "python code"),
            ("is tab me darkshadow search karo", "darkshadow"),
            ("yahan arijit singh live song search karo", "arijit singh live song"),
            ("is window me readme.md dhoondo", "readme.md"),
        ]
        for phrase, expected_query in test_cases:
            cmd = parse_automation_command(phrase)
            self.assertIsNotNone(cmd, f"Failed to parse: {phrase}")
            self.assertEqual(cmd.intent, "search_in_active_app")
            self.assertEqual(cmd.arguments["query"], expected_query)

    def test_parse_youtube_search_variations(self):
        """Test parsing of various natural language YouTube search commands."""
        test_cases = [
            ("youtube par arijit singh live song search karo", "arijit singh live song"),
            ("youtube pe arijit singh search karo", "arijit singh"),
            ("youtube search arijit singh live", "arijit singh live"),
            ("search on youtube for kesariya song", "kesariya song"),
        ]
        for phrase, expected_query in test_cases:
            cmd = parse_automation_command(phrase)
            self.assertIsNotNone(cmd, f"Failed to parse: {phrase}")
            self.assertEqual(cmd.intent, "search_youtube")
            self.assertEqual(cmd.arguments["query"], expected_query)

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("youtube", 5555, "YouTube - Google Chrome"))
    @patch.object(UniversalInAppOperator, "search_in_active_or_open_app", return_value={"success": True, "action": "youtube_in_page_search", "message": "Done"})
    @patch("automation._open_browser_url")
    def test_search_youtube_reuses_existing_tab(self, mock_open_url, mock_in_app_search, mock_fg):
        """search_youtube should reuse active tab and NOT invoke _open_browser_url."""
        res = search_youtube("arijit singh live song")

        self.assertTrue(res.success)
        self.assertEqual(res.action, "search_youtube")
        self.assertTrue(res.data.get("same_tab"))
        mock_in_app_search.assert_called_once_with("arijit singh live song", target_app="youtube")
        mock_open_url.assert_not_called()

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("unknown", 0, ""))
    @patch.object(UniversalInAppOperator, "find_open_app_window", return_value=(0, ""))
    @patch("automation._open_browser_url")
    def test_search_youtube_opens_new_tab_only_when_not_open(self, mock_open_url, mock_find, mock_fg):
        """When YouTube is NOT open, search_youtube opens standard URL."""
        res = search_youtube("arijit singh live song")

        self.assertTrue(res.success)
        mock_open_url.assert_called_once()

    def test_skill_registry_has_search_in_active_app(self):
        """Verify search_in_active_app is registered in skill registry."""
        skill = self.registry.get("search_in_active_app")
        self.assertIsNotNone(skill)
        self.assertFalse(skill.requires_camera)
        self.assertTrue(skill.enabled)

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("youtube", 7777, "YouTube - Microsoft Edge"))
    @patch.object(UniversalInAppOperator, "search_in_active_or_open_app", return_value={"success": True, "action": "youtube_in_page_search"})
    @patch("automation._open_browser_url")
    def test_open_website_reuses_tab_on_youtube_search_url(self, mock_open_url, mock_in_app, mock_fg):
        """open_website with youtube search results URL should search in same tab without opening new tab."""
        from automation import open_website
        res = open_website("https://www.youtube.com/results?search_query=Arijit+Singh+live+song")

        self.assertTrue(res.success)
        self.assertTrue(res.data.get("same_tab"))
        mock_in_app.assert_called_once_with("Arijit Singh live song", target_app="youtube")
        mock_open_url.assert_not_called()

    @patch.object(UniversalInAppOperator, "get_foreground_app_info", return_value=("notepad", 8888, "Notepad"))
    @patch.object(UniversalInAppOperator, "find_open_app_window", return_value=(7777, "YouTube - Microsoft Edge"))
    @patch.object(UniversalInAppOperator, "bring_to_foreground", return_value=True)
    @patch("automation._open_browser_url")
    def test_open_website_focuses_existing_youtube_window(self, mock_open_url, mock_bring, mock_find, mock_fg):
        """open_website('youtube.com') when YouTube is already open focuses window without duplicate tab."""
        from automation import open_website
        res = open_website("https://youtube.com")

        self.assertTrue(res.success)
        self.assertTrue(res.data.get("focused_existing"))
        mock_bring.assert_called_once_with(7777)
        mock_open_url.assert_not_called()

    def test_live_voice_normalizes_youtube_search_url_and_browser(self):
        """Test live_voice normalization for Edge preference and YouTube search URLs."""
        from live_voice import _normalize_tool_call

        # YouTube URL to in-app search
        n, a = _normalize_tool_call("open_website", {"url_or_name": "youtube.com/results?search_query=Arijit+Singh+live+song"})
        self.assertEqual(n, "search_in_active_app")
        self.assertEqual(a["query"], "Arijit Singh live song")

        # Browser fill input to in-app search
        n, a = _normalize_tool_call("browser_fill_input", {"text": "Kesariya song", "selector": "input[name='search_query']"})
        self.assertEqual(n, "search_in_active_app")
        self.assertEqual(a["query"], "Kesariya song")

        # Generic browser to Microsoft Edge
        n, a = _normalize_tool_call("open_application", {"app_name": "browser"})
        self.assertEqual(n, "open_application")
        self.assertEqual(a["app_name"], "Edge")

    @patch("error_logger.ErrorLogger.log_lesson_record")
    @patch("memory.SQLiteMemoryStore.save_lesson")
    def test_save_captain_lesson_logs_to_error_py(self, mock_save_lesson, mock_log_record):
        """save_captain_lesson must invoke ErrorLogger.log_lesson_record for error.py."""
        from automation import save_captain_lesson
        mock_save_lesson.return_value = MagicMock(success=True, message="Lesson saved", data={})

        res = save_captain_lesson("Browser Preference", "Captain prefers Edge over Chrome")
        self.assertTrue(res.success)
        mock_log_record.assert_called_once_with(
            topic="Browser Preference",
            lesson="Captain prefers Edge over Chrome",
        )


if __name__ == "__main__":
    unittest.main()
