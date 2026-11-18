"""Unit tests verifying fixes for browser engine threading, Spotify search, and screen vision clicks."""

import threading
import unittest
from unittest.mock import MagicMock, patch

from automation import (
    AutomationResult,
    click_screen_element,
    analyze_screen_content,
    vision_browser_goal,
    search_spotify,
    play_spotify,
)
from browser_engine import DarkShadowBrowserEngine
from live_voice import _normalize_tool_call
from spotify_engine import SpotifyClient


class TestVoiceBrowserVisionFixes(unittest.TestCase):

    def test_browser_engine_worker_thread_isolation(self):
        """Verify that browser engine executes all operations strictly on its single dedicated worker thread."""
        engine = DarkShadowBrowserEngine(headless=True)
        worker_threads_recorded = []

        def dummy_action():
            worker_threads_recorded.append(threading.get_ident())
            return {"success": True}

        def call_from_thread():
            engine._run_in_worker(dummy_action)

        threads = [threading.Thread(target=call_from_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(worker_threads_recorded), 5)
        # All executions must occur on the EXACT same thread ID
        self.assertEqual(len(set(worker_threads_recorded)), 1)
        # And that thread ID must NOT be the caller thread
        self.assertNotEqual(worker_threads_recorded[0], threading.get_ident())

    def test_normalize_tool_call_spotify_separation(self):
        """Verify that search_spotify is not mistakenly collapsed into play_spotify."""
        name_s, args_s = _normalize_tool_call("search_spotify", {"query": "Love Wins All"})
        self.assertEqual(name_s, "search_spotify")
        self.assertEqual(args_s["query"], "Love Wins All")

        name_p, args_p = _normalize_tool_call("play_spotify", {"query": "Love Wins All"})
        self.assertEqual(name_p, "play_spotify")
        self.assertEqual(args_p["query"], "Love Wins All")

    def test_vision_browser_goal_fallback_to_desktop_click(self):
        """Verify that vision_browser_goal falls back to click_screen_element if Playwright fails or has no elements."""
        mock_engine = MagicMock()
        mock_engine.vision_execute_goal.return_value = {
            "success": False,
            "error": "no_interactive_elements",
            "message": "Page par koi interactive button ya link nahi mila.",
        }

        mock_screen_res = AutomationResult(
            True,
            "click_screen_element",
            "Screen par play button click kar diya.",
            {"target": "play button", "x": 500, "y": 300},
        )

        with patch("browser_engine.get_browser_engine", return_value=mock_engine), \
             patch("automation.click_screen_element", return_value=mock_screen_res) as mock_click:
            res = vision_browser_goal("Click on the big green play button next to the cover art of the song 'Love wins all'")
            self.assertTrue(res.success)
            self.assertEqual(res.action, "vision_browser_goal")
            self.assertIn("locate karke click kar diya", res.message)
            self.assertTrue(res.data.get("desktop_clicked"))
            mock_click.assert_called_once()

    def test_analyze_screen_auto_click_when_action_requested(self):
        """Verify that analyze_screen_content triggers click_screen_element when prompt contains action words."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "'Love wins all' ke cover art ke theek baaju me bada green play button hai."
        mock_client.models.generate_content.return_value = mock_resp

        mock_click_res = AutomationResult(
            True,
            "click_screen_element",
            "Screen par play button click kar diya.",
            {"target": "play button", "label": "play button", "x": 500, "y": 300},
        )

        mock_img = MagicMock()
        mock_img.size = (1920, 1080)

        with patch("automation._capture_desktop_screenshot", return_value=mock_img), \
             patch("automation._get_cached_genai_client", return_value=mock_client), \
             patch("automation.click_screen_element", return_value=mock_click_res) as mock_click:
            res = analyze_screen_content(
                prompt="Find the play button for 'Love Wins All' and visually click it.",
                api_key="fake_key",
            )
            self.assertTrue(res.success)
            self.assertIn("click kar diya hai", res.message)
            self.assertTrue(res.data.get("clicked"))
            mock_click.assert_called_once()

    def test_spotify_engine_http_403_graceful(self):
        """Verify that SpotifyClient handles HTTP 403 Forbidden without throwing unhandled exceptions."""
        import urllib.error
        client = SpotifyClient("test_id", "test_secret")
        with patch.object(client, "_get_access_token", return_value="fake_token"), \
             patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("https://api.spotify.com", 403, "Forbidden", {}, None)):
            res = client.search_track("Love Wins All")
            self.assertEqual(res, [])


if __name__ == "__main__":
    unittest.main()
