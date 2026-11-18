"""Unit tests for RealWork Autonomous Orchestrator and Dynamic Improvement Backlog."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import load_settings
from improvement_backlog import ImprovementBacklog, ImprovementEntry
from realwork_orchestrator import RealWorkOrchestrator, RealWorkPlan, RealWorkStep
from chatbot import DarkShadowChatbot


class TestRealWorkOrchestratorAndBacklog(unittest.TestCase):
    """Test suite for mission decomposition, live execution, and backlog logging."""

    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp())
        self.jsonl_path = self.test_dir / "improvements.jsonl"
        self.md_path = self.test_dir / "improvements.md"
        self.backlog = ImprovementBacklog(jsonl_path=self.jsonl_path, md_path=self.md_path)
        self.orchestrator = RealWorkOrchestrator(backlog=self.backlog)
        self.settings = load_settings()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. Improvement Backlog Tests
    # -------------------------------------------------------------------------
    def test_01_record_missing_capability_creates_jsonl_and_markdown(self) -> None:
        """Verify recording a missing capability persists to JSONL and generates Markdown roadmap."""
        entry = self.backlog.record_missing_capability(
            capability_name="photoshop_filter",
            requested_command="Photoshop me cinematic filter lagao",
            reason="No Photoshop COM automation code written yet",
            suggested_implementation="Use pywin32 COM dispatch or Photoshop CLI",
            priority="HIGH",
        )

        self.assertIsNotNone(entry)
        self.assertTrue(entry.id.startswith("IMP-"))
        self.assertEqual(entry.capability_name, "photoshop_filter")
        self.assertEqual(entry.status, "PENDING")

        # Check JSONL
        self.assertTrue(self.jsonl_path.exists())
        content_lines = self.jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(content_lines), 1)
        record = json.loads(content_lines[0])
        self.assertEqual(record["id"], entry.id)
        self.assertEqual(record["capability_name"], "photoshop_filter")

        # Check Markdown roadmap
        self.assertTrue(self.md_path.exists())
        md_text = self.md_path.read_text(encoding="utf-8")
        self.assertIn("DarkShadow Autonomous Improvements Backlog", md_text)
        self.assertIn("photoshop_filter", md_text)
        self.assertIn(entry.id, md_text)

    def test_02_backlog_deduplication(self) -> None:
        """Verify identical pending capabilities are not duplicated."""
        e1 = self.backlog.record_missing_capability(
            capability_name="convert_pdf_to_audio",
            requested_command="Convert this pdf to audio",
        )
        e2 = self.backlog.record_missing_capability(
            capability_name="convert_pdf_to_audio",
            requested_command="Ek aur baar pdf to audio convert karo",
        )

        self.assertEqual(e1.id, e2.id)
        entries = self.backlog.load_entries()
        self.assertEqual(len(entries), 1)

    def test_03_format_summary_for_captain(self) -> None:
        """Verify friendly Hinglish readout reflects backlog count and names."""
        # Empty backlog
        summary_empty = self.backlog.format_summary_for_captain()
        self.assertIn("koi pending feature nahi hai", summary_empty)

        # Non-empty backlog
        self.backlog.record_missing_capability(
            capability_name="export_to_notion",
            requested_command="Notion me export karo",
        )
        summary_filled = self.backlog.format_summary_for_captain()
        self.assertIn("export_to_notion", summary_filled)
        self.assertIn("Captain", summary_filled)

    # -------------------------------------------------------------------------
    # 2. Mission Decomposition Tests
    # -------------------------------------------------------------------------
    def test_04_heuristic_mission_decomposition(self) -> None:
        """Verify complex natural phrase decomposes into ordered steps."""
        goal = "Pehle system status check karo, fir YouTube par lo-fi play karo, aur fir Photoshop me filter lagao"
        plan = self.orchestrator.decompose_mission(goal)

        self.assertIsInstance(plan, RealWorkPlan)
        self.assertGreaterEqual(len(plan.steps), 3)

        # Step 1: System Status
        self.assertEqual(plan.steps[0].tool_name, "get_system_status")
        # Step 2: YouTube
        self.assertEqual(plan.steps[1].tool_name, "play_youtube")
        # Step 3: Unimplemented custom tool (Photoshop)
        self.assertIn("photoshop", plan.steps[2].tool_name.lower())

    def test_05_gemini_mission_decomposition(self) -> None:
        """Verify Gemini model response parses structured steps."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps([
            {"step_idx": 1, "title": "Check RAM", "tool_name": "get_system_telemetry", "arguments": {}, "description": "Check PC memory"},
            {"step_idx": 2, "title": "Synthesize Research", "tool_name": "deep_research", "arguments": {"topic": "AI"}, "description": "Deep research"},
            {"step_idx": 3, "title": "Export Notion", "tool_name": "notion_export", "arguments": {}, "description": "Send to Notion"},
        ])
        mock_client.models.generate_content.return_value = mock_response

        plan = self.orchestrator.decompose_mission("Research AI and send to Notion", client=mock_client)
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(plan.steps[0].tool_name, "get_system_telemetry")
        self.assertEqual(plan.steps[2].tool_name, "notion_export")

    # -------------------------------------------------------------------------
    # 3. Live Execution & Backlog Reporting Tests
    # -------------------------------------------------------------------------
    def test_06_execution_live_progress_and_missing_capability_handling(self) -> None:
        """Verify steps execute with live callbacks and missing tools are captured in backlog."""
        steps = [
            RealWorkStep(
                step_idx=1,
                title="System Diagnostics",
                tool_name="get_system_status",
                description="Check health",
            ),
            RealWorkStep(
                step_idx=2,
                title="Unwritten Tool Action",
                tool_name="unwritten_video_upscaler",
                description="Upscale 4k video",
            ),
            RealWorkStep(
                step_idx=3,
                title="Save Notes",
                tool_name="save_note",
                arguments={"text": "Mission completed with 1 backlogged item"},
                description="Save mission status",
            ),
        ]
        plan = RealWorkPlan(mission_goal="Run Diagnostics and Upscale Video", steps=steps)

        progress_log: list[str] = []

        def track_progress(msg: str) -> None:
            progress_log.append(msg)

        # Mock tool execution for step 1 & 3
        with patch.object(self.orchestrator, "_execute_step_tool", return_value={"success": True, "message": "Done"}):
            result = self.orchestrator.execute_mission(plan, progress_callback=track_progress)

        self.assertTrue(result["success"])
        self.assertEqual(result["completed_steps"], 2)
        self.assertEqual(result["backlogged_steps"], 1)

        # Verify callbacks notified Captain at each step
        callback_text = "\n".join(progress_log)
        self.assertIn("Step 1/3 shuru kar raha hoon", callback_text)
        self.assertIn("Step 1 complete", callback_text)
        self.assertIn("Step 2 ('Unwritten Tool Action') ke liye abhi code nahi likha gaya hai", callback_text)
        self.assertIn("improvements.md", callback_text)
        self.assertIn("Step 3 complete", callback_text)

        # Verify missing capability was saved into backlog
        entries = self.backlog.load_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].capability_name, "unwritten_video_upscaler")

    def test_07_camera_privacy_enforcement_in_mission(self) -> None:
        """Verify camera-related steps are hard-blocked during real-work execution."""
        steps = [
            RealWorkStep(
                step_idx=1,
                title="Record Face Camera",
                tool_name="webcam_record",
                description="Attempting webcam",
            ),
        ]
        plan = RealWorkPlan(mission_goal="Record Webcam", steps=steps)

        res = self.orchestrator.execute_mission(plan)
        self.assertEqual(res["failed_steps"], 1)
        self.assertIn("privacy", steps[0].result_message.lower())

    # -------------------------------------------------------------------------
    # 4. Chatbot Integration Tests
    # -------------------------------------------------------------------------
    def test_08_chatbot_improvements_commands(self) -> None:
        """Verify chatbot responds to /improvements and natural queries."""
        bot = DarkShadowChatbot(settings=self.settings, client=MagicMock())

        with patch("improvement_backlog.ImprovementBacklog.get_instance", return_value=self.backlog):
            # Slash command
            resp1 = bot.respond("/improvements")
            self.assertEqual(resp1.intent, "show_improvements")
            self.assertIn("Captain", resp1.display_text)

            # Natural query
            resp2 = bot.respond("kya kya improvements baki hai")
            self.assertEqual(resp2.intent, "show_improvements")
            self.assertIn("Captain", resp2.display_text)

    def test_09_chatbot_multi_step_mission_trigger(self) -> None:
        """Verify chatbot detects multi-step command and routes through RealWorkOrchestrator."""
        bot = DarkShadowChatbot(settings=self.settings, client=MagicMock())

        with patch("realwork_orchestrator.RealWorkOrchestrator.get_instance", return_value=self.orchestrator):
            with patch.object(self.orchestrator, "_execute_step_tool", return_value={"success": True, "message": "Success"}):
                resp = bot.respond(
                    "/mission Pehle system status check karo, fir YouTube par gaana bajao, aur fir Photoshop kholo"
                )
                self.assertEqual(resp.intent, "realwork_mission_concluded")
                self.assertIn("Mission Concluded", resp.display_text)
                self.assertIn("Captain", resp.display_text)


if __name__ == "__main__":
    unittest.main()
