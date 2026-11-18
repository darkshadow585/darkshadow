"""Comprehensive automated test suite for DarkShadow Next-Gen Upgrades.

Covers:
1. Model Context Protocol (MCP) Client & Manager
2. Vision-Driven GUI Agent & Computer Use Executor
3. Autonomous Organic Memory Distiller & Retriever
4. Ambient Screen & Proactive Sentinel Copilot
5. Multi-Agent Swarm (DeepResearch, WorkspaceAuditor, SystemCleanup)
6. SkillRegistry Integration & Privacy Lock
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import load_settings
from mcp_client import MCPClient, MCPManager, MCPToolDefinition
from vision_agent import (
    ComputerUseExecutor,
    ScreenCaptureEngine,
    VisionCoordinateGrounder,
    VisualElementTarget,
)
from memory import SQLiteMemoryStore
from auto_memory import AutonomousMemoryDistiller, AutonomousMemoryRetriever
from sentinel_copilot import (
    ErrorWatcherSentinel,
    MorningBriefingSentinel,
    SystemHealthSentinel,
    SentinelCoordinator,
)
from agent_swarm import (
    DeepResearchAgent,
    WorkspaceAuditorAgent,
    SystemCleanupAgent,
    SwarmCoordinator,
)
from skill import get_skill_registry, SkillCategory, SkillLevel


class TestNextGenUpgrades(unittest.TestCase):
    """Verify all 5 pillars of the next-generation DarkShadow upgrades."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_memory.db"
        self.memory_store = SQLiteMemoryStore(self.db_path)

    def tearDown(self) -> None:
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    # =========================================================================
    # 1. MCP (MODEL CONTEXT PROTOCOL) TESTS
    # =========================================================================
    def test_mcp_tool_definition_to_gemini_schema(self) -> None:
        """Verify MCP tool schema translates correctly to Gemini function calling declaration."""
        tool_def = MCPToolDefinition(
            server_name="sqlite",
            name="execute_query",
            description="Run a read-only SQL query on database",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL query text"}
                },
                "required": ["query"],
            },
        )
        gemini_schema = tool_def.to_gemini_schema()
        self.assertEqual(gemini_schema["name"], "mcp_sqlite_execute_query")
        self.assertIn("[MCP:sqlite]", gemini_schema["description"])
        self.assertEqual(gemini_schema["parameters"]["type"], "object")
        self.assertIn("query", gemini_schema["parameters"]["properties"])

    def test_mcp_manager_registration_and_execution(self) -> None:
        """Verify MCPManager can register mock clients, export schemas, and route tool calls."""
        mgr = MCPManager(config_path=Path(self.temp_dir) / "empty_mcp.json")

        mock_client = MagicMock(spec=MCPClient)
        mock_client.server_name = "mock_calc"
        tool_def = MCPToolDefinition(
            server_name="mock_calc",
            name="add",
            description="Add two numbers",
            input_schema={"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
        )
        mock_client.list_tools.return_value = [tool_def]
        mock_client.call_tool.return_value = {"success": True, "output": "Result: 42"}

        mgr.register_server("mock_calc", mock_client)

        self.assertTrue(mgr.is_mcp_tool("mcp_mock_calc_add"))
        schemas = mgr.get_all_tool_schemas()
        self.assertTrue(any(s["name"] == "mcp_mock_calc_add" for s in schemas))

        res = mgr.execute_tool("mcp_mock_calc_add", {"a": 20, "b": 22})
        self.assertTrue(res["success"])
        self.assertEqual(res["output"], "Result: 42")

    # =========================================================================
    # 2. VISION-DRIVEN GUI AGENT & COMPUTER USE TESTS
    # =========================================================================
    def test_screen_resolution_safe_fallback(self) -> None:
        """ScreenCaptureEngine returns valid positive screen dimensions."""
        width, height = ScreenCaptureEngine.get_screen_resolution()
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)

    @patch("vision_agent.ScreenCaptureEngine.capture_screenshot")
    @patch("pyautogui.click")
    @patch("pyautogui.moveTo")
    def test_computer_use_visual_click(self, mock_move: MagicMock, mock_click: MagicMock, mock_capture: MagicMock) -> None:
        """Verify ComputerUseExecutor coordinates click accurately."""
        grounder = MagicMock(spec=VisionCoordinateGrounder)
        grounder.locate_element.return_value = VisualElementTarget(
            target_name="SubmitButton",
            pixel_x=450,
            pixel_y=300,
            confidence=0.95,
            method="ui_automation",
        )
        executor = ComputerUseExecutor(grounder=grounder)
        res = executor.visual_click(target="SubmitButton", verify_delta=False)

        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "visual_click")
        self.assertEqual(res["coordinates"], (450, 300))
        mock_move.assert_called_once_with(450, 300, duration=0.2)
        mock_click.assert_called_once_with(450, 300)

    @patch("pyautogui.write")
    def test_computer_use_visual_type(self, mock_write: MagicMock) -> None:
        """Verify ComputerUseExecutor types text properly."""
        executor = ComputerUseExecutor()
        res = executor.visual_type(target=None, text="DarkShadow test")
        self.assertTrue(res["success"])
        self.assertEqual(res["typed_text"], "DarkShadow test")
        mock_write.assert_called_once()

    # =========================================================================
    # 3. AUTONOMOUS ORGANIC MEMORY LAYER TESTS
    # =========================================================================
    def test_autonomous_facts_storage_and_retrieval(self) -> None:
        """Verify autonomous facts are persisted into SQLite and searchable."""
        store_res = self.memory_store.store_autonomous_fact(
            category="preference",
            subject="theme",
            fact="Captain prefers OLED dark theme",
            confidence=0.9,
        )
        self.assertTrue(store_res.success)

        # Retrieve by keyword match
        matches = self.memory_store.search_autonomous_facts("theme pasand hai", limit=3)
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0]["subject"], "theme")
        self.assertIn("dark theme", matches[0]["fact"])

        # Knowledge summary injection check
        summary = self.memory_store.get_formatted_captain_knowledge_summary()
        self.assertIn("ORGANICALLY OBSERVED FACTS ABOUT CAPTAIN", summary)
        self.assertIn("dark theme", summary)

    def test_autonomous_distiller_heuristic_extraction(self) -> None:
        """Verify conversation text automatically yields structured facts without /remember."""
        distiller = AutonomousMemoryDistiller(self.memory_store)

        # 1. Preference
        facts = distiller._extract_heuristics("Mujhe mechanical keyboard pasand hai")
        self.assertGreaterEqual(len(facts), 1)
        self.assertEqual(facts[0][0], "preference")
        self.assertIn("mechanical keyboard", facts[0][1])

        # 2. Project
        facts_proj = distiller._extract_heuristics("I am working on DarkShadow AI")
        self.assertGreaterEqual(len(facts_proj), 1)
        self.assertEqual(facts_proj[0][0], "project")
        self.assertIn("darkshadow ai", facts_proj[0][1].casefold())

        # 3. Relationship
        facts_rel = distiller._extract_heuristics("Mera dost Kuldeep sonkar hai")
        self.assertGreaterEqual(len(facts_rel), 1)
        self.assertEqual(facts_rel[0][0], "relationship")

    def test_autonomous_memory_retriever_injection(self) -> None:
        """Verify retriever prepares clean context injection string."""
        self.memory_store.store_autonomous_fact("preference", "editor", "Captain codes in VS Code")
        retriever = AutonomousMemoryRetriever(self.memory_store)
        injection = retriever.get_context_injection("editor kaunsa use karte ho")
        self.assertIn("ORGANIC CONTEXTUAL MEMORIES", injection)
        self.assertIn("VS Code", injection)

    # =========================================================================
    # 4. AMBIENT SCREEN & PROACTIVE SENTINEL COPILOT TESTS
    # =========================================================================
    def test_error_watcher_sentinel_detection(self) -> None:
        """Verify ErrorWatcherSentinel spots Python traceback in terminal windows."""
        sentinel = ErrorWatcherSentinel(cooldown_seconds=60)
        with patch("desktop_engine.get_desktop_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_engine.get_active_window_title.return_value = "Visual Studio Code - main.py"
            mock_engine.get_active_window_context.return_value = (
                'Active Window: "VS Code"\n'
                'Traceback (most recent call last):\n'
                '  File "test.py", line 12\n'
                'ModuleNotFoundError: No module named \'uninstalled_pkg\''
            )
            mock_get_engine.return_value = mock_engine

            alert = sentinel.check()
            self.assertIsNotNone(alert)
            self.assertIn("error dikh raha hai", alert)
            self.assertIn("ModuleNotFoundError", alert)

            # Debouncing: immediate second call should be suppressed
            second_alert = sentinel.check()
            self.assertIsNone(second_alert)

    def test_morning_briefing_sentinel(self) -> None:
        """Verify MorningBriefingSentinel triggers with proper date during morning hours."""
        sentinel = MorningBriefingSentinel()
        with patch("datetime.datetime") as mock_datetime:
            mock_now = MagicMock()
            mock_now.hour = 9  # 9 AM (morning window)
            mock_now.strftime.side_effect = lambda fmt: datetime(2026, 9, 6, 9, 30).strftime(fmt)
            mock_datetime.now.return_value = mock_now

            briefing = sentinel.check(memory_store=self.memory_store)
            self.assertIsNotNone(briefing)
            self.assertIn("Good morning Captain", briefing)

            # Same day check must return None
            second = sentinel.check(memory_store=self.memory_store)
            self.assertIsNone(second)

    def test_system_health_sentinel(self) -> None:
        """Verify SystemHealthSentinel triggers when disk is critically low."""
        sentinel = SystemHealthSentinel(cooldown_seconds=60)
        with patch("shutil.disk_usage") as mock_usage:
            # Simulate 2 GB free (critically low < 5GB)
            mock_usage.return_value = (100 * (1024**3), 98 * (1024**3), 2 * (1024**3))
            alert = sentinel.check()
            self.assertIsNotNone(alert)
            self.assertIn("storage critically low", alert)

    # =========================================================================
    # 5. MULTI-AGENT SWARM TESTS
    # =========================================================================
    def test_deep_research_agent_generates_report(self) -> None:
        """Verify DeepResearchAgent creates structured report file in .darkshadow/reports."""
        agent = DeepResearchAgent(topic="Quantum AI Benchmarks")
        with patch("realtimeinfo.RealtimeInfoService.answer") as mock_answer:
            mock_res = MagicMock()
            mock_res.display_text = "Quantum computing is scaling with superconducting qubits."
            mock_res.error = None
            mock_res.sources = [MagicMock(title="Nature Physics", url="https://nature.com")]
            mock_answer.return_value = mock_res

            report = agent.run()
            self.assertTrue(report.success)
            self.assertEqual(report.agent_name, "DeepResearchAgent")
            self.assertIsNotNone(report.report_file)
            self.assertTrue(Path(report.report_file).exists())
            self.assertIn("deep research complete", report.summary)

            # Cleanup generated test report
            try:
                Path(report.report_file).unlink(missing_ok=True)
            except Exception:
                pass

    def test_workspace_auditor_agent(self) -> None:
        """Verify WorkspaceAuditorAgent audits workspace without errors."""
        agent = WorkspaceAuditorAgent(workspace_path=".")
        report = agent.run()
        self.assertTrue(report.success)
        self.assertIn("workspace audit complete", report.summary)
        self.assertIn("git_branch", report.details)

    def test_system_cleanup_agent_dry_run(self) -> None:
        """Verify SystemCleanupAgent in dry_run mode calculates reclaimable space without deleting."""
        # Create a dummy test cache dir
        test_cache = Path(self.temp_dir) / "__pycache__"
        test_cache.mkdir(parents=True)
        (test_cache / "dummy.pyc").write_bytes(b"0" * 1024)

        agent = SystemCleanupAgent(target_dir=self.temp_dir, dry_run=True)
        report = agent.run()
        self.assertTrue(report.success)
        self.assertTrue(report.details["dry_run"])
        self.assertGreaterEqual(report.details["folders_count"], 1)
        self.assertTrue(test_cache.exists())  # Must not delete in dry run

    # =========================================================================
    # 6. SKILL REGISTRY & CAMERA PRIVACY ENFORCEMENT
    # =========================================================================
    def test_new_skills_registered_in_catalog(self) -> None:
        """Verify all new Computer Use and Swarm skills are in the global registry."""
        registry = get_skill_registry()

        new_skill_names = [
            "visual_click_element",
            "visual_type_text",
            "dispatch_deep_research",
            "run_workspace_audit",
            "run_system_cleanup",
        ]
        for name in new_skill_names:
            skill = registry.get(name)
            self.assertIsNotNone(skill, f"Skill '{name}' missing from catalog")
            self.assertFalse(skill.requires_camera, f"Skill '{name}' must not require camera")
            self.assertTrue(skill.enabled, f"Skill '{name}' must be enabled")

    def test_physical_camera_remains_permanently_blocked(self) -> None:
        """Ensure webcam and face camera skills remain hard-blocked for Captain's privacy."""
        registry = get_skill_registry()
        blocked_skills = ["webcam_record", "face_camera_feed"]
        for name in blocked_skills:
            skill = registry.get(name)
            self.assertIsNotNone(skill)
            self.assertTrue(skill.requires_camera)
            self.assertFalse(skill.enabled)
            res = registry.execute(name)
            self.assertFalse(res.success)
            self.assertEqual(res.error, "camera_access_denied")


if __name__ == "__main__":
    unittest.main()
