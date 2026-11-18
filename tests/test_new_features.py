"""Unit tests for the 6 new next-gen capabilities in DarkShadow."""

import dataclasses
import unittest
from unittest.mock import MagicMock, patch

import config
import chatbot
import automation
import youtube_engine
import realtimeinfo
import live_voice


class TestNewCapabilities(unittest.TestCase):
    """Test suite covering all 6 newly added capabilities."""

    def test_01_config_next_gen_settings(self):
        """Feature 1 & 2 & 5 & 6: Verify config settings have proper defaults and types."""
        settings = config.load_settings()
        self.assertTrue(settings.youtube_agentic_video_enabled)
        self.assertIn("gemini", settings.agentic_video_model)
        self.assertEqual(settings.thinking_budget_technical, 2048)
        self.assertEqual(settings.thinking_budget_creative, 1024)
        self.assertEqual(settings.thinking_budget_casual, 0)
        self.assertEqual(settings.thinking_budget_automation, 1024)
        self.assertTrue(settings.context_caching_enabled)
        self.assertEqual(settings.context_cache_ttl_seconds, 3600)
        self.assertEqual(settings.search_grounding_provider, "auto")

    def test_02_hybrid_reasoning_thinking_budget(self):
        """Feature 2: Verify thinking budget allocation based on query category and settings."""
        settings = config.load_settings()

        casual_p = chatbot.response_profile("hello kaise ho", settings)
        self.assertEqual(casual_p.thinking_budget, 0)
        self.assertEqual(casual_p.mode, chatbot.ResponseMode.CASUAL)

        tech_p = chatbot.response_profile("diagnose and fix this complex algorithm error", settings)
        self.assertEqual(tech_p.thinking_budget, 2048)
        self.assertEqual(tech_p.mode, chatbot.ResponseMode.TECHNICAL)

        creative_p = chatbot.response_profile("write a story about space", settings)
        self.assertEqual(creative_p.thinking_budget, 1024)
        self.assertEqual(creative_p.mode, chatbot.ResponseMode.CREATIVE)

    def test_03_agentic_video_understanding(self):
        """Feature 1: Verify agentic video function resolves video and calls interactions API."""
        mock_client = MagicMock()
        mock_interaction = MagicMock()
        mock_interaction.output_text = "🎯 Main Gist: Video explains AI agents.\n⏱️ 02:15 Code demo."
        mock_client.interactions.create.return_value = mock_interaction

        with patch("automation._get_cached_genai_client", return_value=mock_client):
            res = youtube_engine.analyze_youtube_video_agentic(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                prompt="Explain the key moments",
                gemini_api_key="test-api-key",
            )
            self.assertTrue(res["success"])
            self.assertTrue(res.get("agentic_mode"))
            self.assertIn("Video explains AI agents", res["summary"])
            self.assertEqual(res["video_id"], "dQw4w9WgXcQ")

    def test_04_screen_vision_command_parsing(self):
        """Feature 3: Verify screen analysis, screen click, and screenshot commands parse properly."""
        p_screen = automation.parse_automation_command("screen dekho")
        self.assertIsNotNone(p_screen)
        self.assertEqual(p_screen.intent, "analyze_screen")

        p_screen_custom = automation.parse_automation_command("screen analyze karke batao ki kya chal raha hai")
        self.assertIsNotNone(p_screen_custom)
        self.assertEqual(p_screen_custom.intent, "analyze_screen")

        p_click = automation.parse_automation_command("screen par Download button par click karo")
        self.assertIsNotNone(p_click)
        self.assertEqual(p_click.intent, "click_screen_element")
        self.assertEqual(p_click.arguments.get("target"), "Download button")

        p_shot = automation.parse_automation_command("screenshot lo")
        self.assertIsNotNone(p_shot)
        self.assertEqual(p_shot.intent, "save_screenshot")

    def test_05_video_summarize_command_parsing(self):
        """Feature 1 & 3: Verify video summarization natural intent parsing."""
        p_video = automation.parse_automation_command("summarize video https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIsNotNone(p_video)
        self.assertEqual(p_video.intent, "summarize_youtube_video")
        self.assertEqual(p_video.arguments.get("url_or_name"), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_06_context_caching_helper(self):
        """Feature 5: Verify context caching creates cache with correct TTL and reuses existing."""
        settings = config.load_settings()
        mock_client = MagicMock()
        mock_cache = MagicMock()
        mock_cache.name = "cachedContents/test-cache-12345"
        mock_client.caches.create.return_value = mock_cache

        bot = chatbot.DarkShadowChatbot(settings, client=mock_client)
        cache_id = bot._get_or_create_context_cache("gemini-3.7-flash", "A" * 1200)
        self.assertEqual(cache_id, "cachedContents/test-cache-12345")
        mock_client.caches.create.assert_called_once()

        # Second call with same instruction should reuse cache from dictionary
        cache_id2 = bot._get_or_create_context_cache("gemini-3.7-flash", "A" * 1200)
        self.assertEqual(cache_id2, "cachedContents/test-cache-12345")
        self.assertEqual(mock_client.caches.create.call_count, 1)

    def test_07_google_search_grounding(self):
        """Feature 6: Verify Google Search Grounding produces grounded response with web citations."""
        settings = dataclasses.replace(config.load_settings(), api_key="test-gemini-key")
        mock_client = MagicMock()

        mock_resp = MagicMock()
        mock_resp.text = "Aaj Mumbai me weather 28 degree Celsius aur clear sky hai."
        candidate = MagicMock()
        chunk = MagicMock()
        chunk.web.uri = "https://weather.com/mumbai"
        chunk.web.title = "Mumbai Weather Today"
        candidate.grounding_metadata.grounding_chunks = [chunk]
        mock_resp.candidates = [candidate]

        mock_client.models.generate_content.return_value = mock_resp

        service = realtimeinfo.RealtimeInfoService(settings, client=MagicMock())
        with patch("automation._get_cached_genai_client", return_value=mock_client):
            res = service._answer_with_google_search("aaj weather kaisa hai")
            self.assertIsNotNone(res)
            self.assertIn("weather", res.display_text.lower())
            self.assertEqual(len(res.sources), 1)
            self.assertEqual(res.sources[0].url, "https://weather.com/mumbai")

    def test_08_live_voice_tool_dispatch(self):
        """Feature 4: Verify live voice tool execution dispatches video and screen tools."""
        mock_res = automation.AutomationResult(True, "summarize_youtube_video", "Summary ready")
        with patch.dict(automation._AUTOMATION_FUNCTIONS, {"summarize_youtube_video": MagicMock(return_value=mock_res)}):
            res = live_voice._execute_tool_call("summarize_youtube_video", {"url_or_name": "test_video"})
            self.assertEqual(res["status"], "ok")
            automation._AUTOMATION_FUNCTIONS["summarize_youtube_video"].assert_called_once_with(url_or_name="test_video")


if __name__ == "__main__":
    unittest.main()
