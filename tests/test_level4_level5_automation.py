"""Tests for Level 4 Asynchronous Automation and Level 5 Desktop GUI Grounding."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation import (
    check_background_tasks,
    desktop_control_action,
    inspect_desktop_window,
    parse_automation_command,
    start_background_task,
)
from background_agent import BackgroundAgentManager, TaskStatus
from desktop_engine import DesktopControl, WindowsUIAutomationEngine, get_desktop_engine
from memory import SQLiteMemoryStore


class TestLevel4AndLevel5Automation(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_mem.db"
        self.mem = SQLiteMemoryStore(self.db_path)

    def tearDown(self):
        self.mem.close()
        import gc, shutil
        gc.collect()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            shutil.rmtree(self.tmp_dir.name, ignore_errors=True)

    # --- Level 4 Tests ---
    def test_background_agent_dispatch_and_status(self):
        """Test background task dispatching, completion, and status retrieval."""
        mgr = BackgroundAgentManager(max_workers=2)

        def dummy_job(x: int, y: int) -> dict:
            return {"sum": x + y, "message": f"Result is {x + y}"}

        task_id = mgr.dispatch("Math Calculation", dummy_job, 10, 20)
        self.assertIsNotNone(task_id)
        self.assertTrue(task_id.startswith("task_"))

        # Wait briefly for thread to finish
        time.sleep(0.2)
        status = mgr.get_status(task_id)
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(status["result"]["sum"], 30)

        notifs = mgr.pop_notifications()
        self.assertTrue(len(notifs) >= 1)
        self.assertTrue("Result is 30" in notifs[0] or "poora ho gaya hai" in notifs[0])

    def test_start_and_check_background_task_tools(self):
        """Test automation tools start_background_task and check_background_tasks."""
        res_start = start_background_task("Test Research", "get_system_status")
        self.assertTrue(res_start.success)
        self.assertEqual(res_start.action, "start_background_task")
        self.assertIn("background me start", res_start.message)

        res_check = check_background_tasks()
        self.assertTrue(res_check.success)
        self.assertEqual(res_check.action, "check_background_tasks")

    def test_semantic_memory_search(self):
        """Test semantic memory retrieval with local fallback."""
        self.mem.add_item("preference", "I love dark roast coffee in the morning")
        self.mem.add_item("preference", "My favorite programming language is Python")
        self.mem.add_item("note", "Captain's car registration number is DL01AB1234")

        # Test search
        results = self.mem.search_semantic_memories("coffee preference")
        self.assertTrue(len(results) >= 1)
        self.assertIn("coffee", results[0].content.lower())

        results_py = self.mem.search_semantic_memories("Python coding")
        self.assertTrue(len(results_py) >= 1)
        self.assertIn("python", results_py[0].content.lower())

    # --- Level 5 Tests ---
    def test_desktop_engine_singleton(self):
        """Test WindowsUIAutomationEngine initialization and singleton accessor."""
        eng1 = get_desktop_engine()
        eng2 = WindowsUIAutomationEngine.get_instance()
        self.assertIs(eng1, eng2)

    def test_desktop_engine_inspect_active_window(self):
        """Test active window inspection."""
        engine = get_desktop_engine()
        with patch.object(engine, "get_active_window_title", return_value="Visual Studio Code"), \
             patch.object(engine, "list_window_controls", return_value=[
                 DesktopControl(name="File", control_type="MenuItem", rect=(10, 10, 40, 30)),
                 DesktopControl(name="Run", control_type="Button", rect=(50, 10, 80, 30)),
             ]):
            info = engine.inspect_active_window()
            self.assertEqual(info["title"], "Visual Studio Code")
            self.assertEqual(info["control_count"], 2)
            self.assertEqual(info["controls"][0]["name"], "File")

    def test_desktop_control_action_tool(self):
        """Test desktop_control_action tool."""
        engine = get_desktop_engine()
        with patch.object(engine, "inspect_active_window", return_value={"title": "Notepad", "control_count": 5}), \
             patch.object(engine, "click_control", return_value={"success": True, "action": "click_control", "control_name": "Save"}), \
             patch.object(engine, "type_into_control", return_value={"success": True, "action": "type_into_control", "typed_text": "Hello"}):

            res_inspect = inspect_desktop_window()
            self.assertTrue(res_inspect.success)
            self.assertIn("Notepad", res_inspect.message)

            res_click = desktop_control_action("click", "Save")
            self.assertTrue(res_click.success)
            self.assertIn("Save", res_click.message)

            res_type = desktop_control_action("type", "Save", text="Hello")
            self.assertTrue(res_type.success)
            self.assertIn("type", res_type.message)

    def test_parse_automation_command_level4_level5(self):
        """Test deterministic parsing of Level 4 and Level 5 user commands."""
        # Level 4
        cmd1 = parse_automation_command("background me search python automation karo")
        self.assertIsNotNone(cmd1)
        self.assertEqual(cmd1.intent, "start_background_task")

        cmd2 = parse_automation_command("check background tasks status")
        self.assertIsNotNone(cmd2)
        self.assertEqual(cmd2.intent, "check_background_tasks")

        # Level 5
        cmd3 = parse_automation_command("desktop inspect karo")
        self.assertIsNotNone(cmd3)
        self.assertEqual(cmd3.intent, "inspect_desktop_window")

        cmd4 = parse_automation_command("window me Submit button click karo")
        self.assertIsNotNone(cmd4)
        self.assertEqual(cmd4.intent, "desktop_control_action")
        self.assertEqual(cmd4.arguments["action"], "click")

    def test_token_tracking_and_tool(self):
        """Test token recording and get_token_usage tool."""
        from automation import get_token_usage, record_token_usage
        record_token_usage(120, 80, 200, model="gemini-3.8-flash")
        res = get_token_usage()
        self.assertTrue(res.success)
        self.assertEqual(res.action, "get_token_usage")
        self.assertIn("tokens use huye", res.message)
        self.assertIn("200", res.message)

        # Test parser
        cmd = parse_automation_command("kitne token use hue batao")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "get_token_usage")

    def test_press_keyboard_key_hotkey_combinations(self):
        """Test that press_keyboard_key correctly handles multi-key hotkey combos."""
        from automation import press_keyboard_key
        with patch("pyautogui.hotkey") as mock_hotkey, patch("pyautogui.press") as mock_press:
            res1 = press_keyboard_key("ctrl+t")
            self.assertTrue(res1.success)
            mock_hotkey.assert_called_with("ctrl", "t")

            res2 = press_keyboard_key("alt+f4")
            self.assertTrue(res2.success)
            mock_hotkey.assert_called_with("alt", "f4")

            res3 = press_keyboard_key("enter")
            self.assertTrue(res3.success)
            mock_press.assert_called_with("enter")

    def test_open_website_local_folder_path(self):
        """Test that open_website detects Windows folder paths without URL error."""
        from automation import open_website
        with patch("subprocess.Popen") as mock_popen, patch("os.path.exists", return_value=True):
            res = open_website(r"C:\Users\Admin\Downloads")
            self.assertTrue(res.success)
            self.assertIn("Folder open kar diya", res.message)

