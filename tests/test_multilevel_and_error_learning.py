"""Tests for Multi-Level Agent Workflows and Interactive Error Learning with error.py Logger."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import load_settings
from memory import SQLiteMemoryStore
from error_logger import ErrorCorrectionDetector, ErrorLogger
from desktop_workflow_agent import WhatsAppInChatSearchAgent, HierarchicalTaskExecutor
from skill import get_skill_registry
from chatbot import DarkShadowChatbot, ConversationTurn


class TestMultiLevelAndErrorLearning(unittest.TestCase):
    """Verify Multi-Level desktop agent workflows and error learning."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_memory.db"
        self.test_error_py = Path(self.temp_dir) / "error.py"
        self.test_error_py.write_text("ERROR_LOGS = []\n", encoding="utf-8")
        self.memory_store = SQLiteMemoryStore(self.db_path)
        self.settings = load_settings()

    def tearDown(self) -> None:
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    # =========================================================================
    # 1. ERROR CORRECTION DETECTION & LOGGING TESTS
    # =========================================================================
    def test_correction_detector_matches_feedback_phrases(self) -> None:
        """Verify detector catches various correction phrases in Hindi/Hinglish/English."""
        correction_phrases = [
            "tumne yaha galat kiya",
            "ye galat hai aisa nahi hota",
            "ye nahi ye hota hai",
            "aise nahi karna tha",
            "you made a mistake here",
            "wrong action perform kiya",
            "ye galti dubara mat karna",
        ]
        for phrase in correction_phrases:
            self.assertTrue(
                ErrorCorrectionDetector.is_correction(phrase),
                f"Expected '{phrase}' to be detected as a correction",
            )

        # Normal queries must NOT be flagged as corrections
        normal_phrases = [
            "open Chrome",
            "Delhi weather today",
            "play lofi beats",
            "volume 40 karo",
        ]
        for phrase in normal_phrases:
            self.assertFalse(
                ErrorCorrectionDetector.is_correction(phrase),
                f"Expected '{phrase}' to NOT be detected as a correction",
            )

    def test_error_logger_appends_to_error_py_and_saves_lesson(self) -> None:
        """Verify ErrorLogger writes valid python code to error.py and updates SQLite memory."""
        last_turn = ConversationTurn(
            user_text="WhatsApp par Saloni ko message draft karo",
            assistant_text="WhatsApp web khol kar draft kiya.",
        )
        correction = "Tumne yaha galat kiya, ye nahi WhatsApp desktop app me draft karna hota hai"

        res = ErrorLogger.log_correction(
            captain_correction=correction,
            last_turn=last_turn,
            memory_store=self.memory_store,
            error_file_path=self.test_error_py,
        )

        self.assertTrue(res["success"])
        self.assertIn("ERR-", res["error_id"])
        self.assertIn("error.py", res["message"])

        # Check error.py file on disk has valid Python content
        content = self.test_error_py.read_text(encoding="utf-8")
        self.assertIn(res["error_id"], content)
        self.assertIn("Saloni", content)
        self.assertIn("PENDING_FIX", content)

        # Verify syntax by executing the file
        local_scope: dict = {}
        exec(content, {}, local_scope)
        self.assertIn("ERROR_LOGS", local_scope)
        self.assertEqual(len(local_scope["ERROR_LOGS"]), 1)
        self.assertEqual(local_scope["ERROR_LOGS"][0]["id"], res["error_id"])

        # Check SQLite memory learned_lessons
        lessons = self.memory_store.get_lessons()
        self.assertGreaterEqual(len(lessons), 1)
        self.assertIn("Correction by Captain", lessons[0]["lesson"])

    # =========================================================================
    # 2. MULTI-LEVEL DESKTOP WORKFLOW & WHATSAPP IN-CHAT SEARCH TESTS
    # =========================================================================
    @patch("pyautogui.press")
    @patch("pyautogui.hotkey")
    @patch("pyperclip.copy")
    @patch("desktop_workflow_agent.WhatsAppInChatSearchAgent._get_whatsapp_hwnd", return_value=12345)
    def test_whatsapp_in_chat_search_flow(
        self,
        mock_hwnd: MagicMock,
        mock_copy: MagicMock,
        mock_hotkey: MagicMock,
        mock_press: MagicMock,
    ) -> None:
        """Verify WhatsApp in-chat search navigates contact, triggers search, and extracts message."""
        with patch.object(
            WhatsAppInChatSearchAgent,
            "_extract_messages_from_ui",
            return_value=["Saloni: Tum bilkul pagal ho haha", "Saloni: pagal kahin ke"],
        ):
            res = WhatsAppInChatSearchAgent.search_and_read(
                contact_name="Saloni",
                search_term="pagal",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["contact"], "Saloni")
            self.assertEqual(res["query"], "pagal")
            self.assertEqual(res["count"], 2)
            self.assertIn("2 message(s) mile hain", res["summary"])
            self.assertIn("Tum bilkul pagal ho", res["summary"])

    def test_skills_catalog_includes_multilevel_workflow_skills(self) -> None:
        """Verify new skills are registered in the global catalog."""
        registry = get_skill_registry()

        s1 = registry.get("whatsapp_in_chat_search")
        self.assertIsNotNone(s1)
        self.assertTrue(s1.enabled)
        self.assertFalse(s1.requires_camera)

        s2 = registry.get("execute_multi_level_task")
        self.assertIsNotNone(s2)
        self.assertTrue(s2.enabled)

    # =========================================================================
    # 3. CHATBOT INTEGRATION WITH ERROR LEARNER & MULTI-LEVEL FLOW
    # =========================================================================
    def test_chatbot_handles_correction_turn(self) -> None:
        """Verify chatbot detects correction, logs it, and returns humble acknowledgement."""
        bot = DarkShadowChatbot(settings=self.settings, client=MagicMock())
        bot._history.append(
            ConversationTurn(
                user_text="WhatsApp par message bhejo",
                assistant_text="Opening browser for WhatsApp web...",
            )
        )

        with patch("error_logger.ERROR_PY_PATH", self.test_error_py):
            resp = bot.respond(
                "Tumne yaha galat kiya, ye nahi desktop app use kiya karo",
                memory_store=self.memory_store,
            )
            self.assertEqual(resp.intent, "correction_logged")
            self.assertIn("error.py", resp.display_text)
            self.assertIn("Captain", resp.display_text)


if __name__ == "__main__":
    unittest.main()
