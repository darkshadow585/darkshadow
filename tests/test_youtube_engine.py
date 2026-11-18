"""Unit tests for YouTube Full Potential Engine (Summarizer, Comments, Metadata)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from automation import (
    analyze_youtube_comments,
    get_youtube_video_details,
    parse_automation_command,
    summarize_youtube_video,
)
from youtube_engine import (
    extract_youtube_video_id,
    fetch_video_comments,
    fetch_video_details,
    parse_iso8601_duration,
)


class TestYouTubeEngine(unittest.TestCase):
    def test_extract_youtube_video_id(self):
        # Various YouTube URL formats
        self.assertEqual(extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertIsNone(extract_youtube_video_id(""))

    def test_parse_iso8601_duration(self):
        text1, sec1 = parse_iso8601_duration("PT1H15M33S")
        self.assertEqual(text1, "1 hr 15 min 33 sec")
        self.assertEqual(sec1, 4533)

        text2, sec2 = parse_iso8601_duration("PT4M20S")
        self.assertEqual(text2, "4 min 20 sec")
        self.assertEqual(sec2, 260)

        text3, sec3 = parse_iso8601_duration("PT45S")
        self.assertEqual(text3, "45 sec")
        self.assertEqual(sec3, 45)

    def test_fetch_video_details_mock(self):
        mock_api_resp = {
            "items": [
                {
                    "snippet": {
                        "title": "Kesariya Song",
                        "channelTitle": "Sony Music India",
                        "description": "Official audio video",
                    },
                    "contentDetails": {"duration": "PT4M28S"},
                    "statistics": {
                        "viewCount": "500000000",
                        "likeCount": "4000000",
                        "commentCount": "120000",
                    },
                }
            ]
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_api_resp).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            details = fetch_video_details("dQw4w9WgXcQ", api_key="dummy_key")
            self.assertIsNotNone(details)
            self.assertEqual(details["title"], "Kesariya Song")
            self.assertEqual(details["channel"], "Sony Music India")
            self.assertEqual(details["duration"], "4 min 28 sec")
            self.assertEqual(details["view_count"], 500000000)

    def test_fetch_video_comments_mock(self):
        mock_comments_resp = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "Rohan",
                                "textDisplay": "Amazing song!",
                                "likeCount": 150,
                            }
                        }
                    }
                }
            ]
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_comments_resp).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            comments = fetch_video_comments("dQw4w9WgXcQ", api_key="dummy_key")
            self.assertEqual(len(comments), 1)
            self.assertEqual(comments[0]["author"], "Rohan")
            self.assertEqual(comments[0]["text"], "Amazing song!")

    def test_summarize_youtube_video_wrapper(self):
        with patch("youtube_engine.summarize_youtube_video_ai") as mock_ai:
            mock_ai.return_value = {
                "success": True,
                "title": "Python Tutorial",
                "summary": "1. Python basics\n2. Key functions",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            }
            res = summarize_youtube_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            self.assertTrue(res.success)
            self.assertEqual(res.action, "summarize_youtube_video")
            self.assertIn("Python Tutorial", res.message)

    def test_analyze_youtube_comments_wrapper(self):
        with patch("youtube_engine.analyze_youtube_comments_ai") as mock_ai:
            mock_ai.return_value = {
                "success": True,
                "title": "Tech Review",
                "analysis": "Overall 90% positive audience sentiment.",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            }
            res = analyze_youtube_comments("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            self.assertTrue(res.success)
            self.assertEqual(res.action, "analyze_youtube_comments")
            self.assertIn("Tech Review", res.message)

    def test_get_youtube_video_details_wrapper(self):
        with patch("youtube_engine.fetch_video_details") as mock_details:
            mock_details.return_value = {
                "title": "Podcast Episode 1",
                "channel": "Tech Show",
                "duration": "1 hr 10 min",
                "view_count": 100000,
                "like_count": 5000,
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            }
            res = get_youtube_video_details("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            self.assertTrue(res.success)
            self.assertIn("Podcast Episode 1", res.message)
            self.assertIn("Tech Show", res.message)

    def test_parse_automation_command_youtube_intents(self):
        p1 = parse_automation_command("is video ka summary batao https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIsNotNone(p1)
        self.assertEqual(p1.intent, "summarize_youtube_video")
        self.assertEqual(p1.arguments["url_or_name"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        p2 = parse_automation_command("is video ke comments analyze karo https://youtu.be/dQw4w9WgXcQ")
        self.assertIsNotNone(p2)
        self.assertEqual(p2.intent, "analyze_youtube_comments")
        self.assertEqual(p2.arguments["url_or_name"], "https://youtu.be/dQw4w9WgXcQ")

        p3 = parse_automation_command("video details https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIsNotNone(p3)
        self.assertEqual(p3.intent, "get_youtube_video_details")
        self.assertEqual(p3.arguments["url_or_name"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")


if __name__ == "__main__":
    unittest.main()
