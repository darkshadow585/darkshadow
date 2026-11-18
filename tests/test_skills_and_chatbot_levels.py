"""Tests for 5-Level Chatbot Upgrades, Skill Architecture, and Camera Privacy Lock."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from config import load_settings
from safety import (
    is_physical_camera_intent,
    CAMERA_BLOCKED_MESSAGE,
)
from skill import (
    get_skill_registry,
    SkillLevel,
    SkillCategory,
    SkillResult,
)
from chatbot import DarkShadowChatbot


class TestSkillsAndChatbotLevels(unittest.TestCase):
    """Verify 5-level capabilities, skill registry, and strict camera privacy."""

    def setUp(self) -> None:
        self.settings = load_settings()
        self.mock_client = MagicMock()
        self.chatbot = DarkShadowChatbot(settings=self.settings, client=self.mock_client)
        self.registry = get_skill_registry()

    def test_camera_privacy_intent_detection(self) -> None:
        """Verify various physical camera/webcam phrases are detected and intercepted."""
        test_queries = [
            "webcam on karo",
            "camera open karo",
            "mera chehra dekho",
            "face recording start karo",
            "take selfie now",
            "turn on webcam",
            "camera chalao",
        ]
        for query in test_queries:
            self.assertTrue(
                is_physical_camera_intent(query),
                f"Expected query to be flagged as camera intent: {query}",
            )

        # Screen-only requests must NOT be blocked as camera
        self.assertFalse(is_physical_camera_intent("screen par kya error hai"))
        self.assertFalse(is_physical_camera_intent("notepad kholo"))
        self.assertFalse(is_physical_camera_intent("open google"))

    def test_chatbot_blocks_physical_camera_request(self) -> None:
        """Verify chatbot.respond immediately refuses physical camera access."""
        resp = self.chatbot.respond("webcam on karke mera face dekho")
        self.assertEqual(resp.intent, "privacy_blocked")
        self.assertEqual(resp.error, "camera_access_denied")
        self.assertIn("physical camera/webcam", resp.display_text)
        self.assertIn("disabled", resp.display_text)

    def test_skill_registry_camera_skill_blocked(self) -> None:
        """Verify invoking a camera-dependent skill directly is rejected."""
        res = self.registry.execute("webcam_record")
        self.assertFalse(res.success)
        self.assertEqual(res.error, "camera_access_denied")
        self.assertEqual(res.message, CAMERA_BLOCKED_MESSAGE)

    def test_skill_registry_5_levels_registered(self) -> None:
        """Verify skills exist across all 5 capability levels."""
        l1_skills = self.registry.list_skills(level=SkillLevel.LEVEL_1_SCREEN_VISION)
        l2_skills = self.registry.list_skills(level=SkillLevel.LEVEL_2_REACT_REASONING)
        l3_skills = self.registry.list_skills(level=SkillLevel.LEVEL_3_WORKFLOW_ORCHESTRATION)
        l4_skills = self.registry.list_skills(level=SkillLevel.LEVEL_4_EPISODIC_MEMORY)
        l5_skills = self.registry.list_skills(level=SkillLevel.LEVEL_5_PROACTIVE_AMBIENT)

        self.assertGreater(len(l1_skills), 0, "Level 1 skills missing")
        self.assertGreater(len(l2_skills), 0, "Level 2 skills missing")
        self.assertGreater(len(l3_skills), 0, "Level 3 skills missing")
        self.assertGreater(len(l4_skills), 0, "Level 4 skills missing")
        self.assertGreater(len(l5_skills), 0, "Level 5 skills missing")

    def test_skills_command_and_catalog(self) -> None:
        """Verify /skills command returns the complete formatted catalog."""
        resp = self.chatbot.respond("/skills")
        self.assertEqual(resp.intent, "skills")
        self.assertIn("Level 1: Screen Vision", resp.display_text)
        self.assertIn("Level 2: Autonomous ReAct", resp.display_text)
        self.assertIn("Level 3: Advanced Cross-App", resp.display_text)
        self.assertIn("Level 4: Hierarchical Long-Term Memory", resp.display_text)
        self.assertIn("Level 5: Proactive Ambient Desktop Co-Pilot", resp.display_text)
        self.assertIn("PERMANENTLY DISABLED", resp.display_text)

    def test_level_2_react_solve_camera_block(self) -> None:
        """Verify react_solve also respects the camera privacy lock."""
        resp = self.chatbot.react_solve("open camera and record face")
        self.assertEqual(resp.intent, "privacy_blocked")
        self.assertEqual(resp.error, "camera_access_denied")

    def test_level_3_workflow_chain_execution(self) -> None:
        """Verify Level 3 workflow orchestrates multiple steps and blocks camera steps."""
        steps = [
            {"name": "get_current_time", "args": {}},
            {"name": "webcam_record", "args": {}},  # Must be blocked safely
        ]
        resp = self.chatbot.run_workflow_chain("test_multi_app", steps)
        self.assertEqual(resp.intent, "workflow_complete")
        self.assertIn("BLOCKED", resp.display_text)
        self.assertIn("get_current_time", resp.display_text)

    def test_level_5_proactive_alert(self) -> None:
        """Verify Level 5 proactive alerts format properly without camera requirement."""
        resp = self.chatbot.dispatch_proactive_alert(
            title="Terminal Build",
            message="pytest completed with 0 errors.",
        )
        self.assertEqual(resp.intent, "proactive_alert")
        self.assertIn("Captain", resp.display_text)
        self.assertIn("Terminal Build", resp.display_text)
        self.assertIn("pytest completed", resp.display_text)


if __name__ == "__main__":
    unittest.main()
