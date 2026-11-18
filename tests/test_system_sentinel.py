"""Unit tests for JARVIS System Sentinel & Hardware Telemetry Suite."""

import unittest
from unittest.mock import MagicMock, patch

from system_sentinel import HardwareTelemetry, SystemSentinel, PROTECTED_PROCESS_NAMES
from tool_registry import dispatch_tool


class TestSystemSentinel(unittest.TestCase):
    """Test suite for SystemSentinel hardware diagnostics and process manager."""

    def setUp(self) -> None:
        self.sentinel = SystemSentinel.get_instance()

    def test_01_get_telemetry_returns_valid_metrics(self) -> None:
        """Verify telemetry snapshot extracts valid CPU, RAM, and Disk metrics."""
        t = self.sentinel.get_telemetry()
        self.assertIsInstance(t, HardwareTelemetry)
        self.assertGreaterEqual(t.cpu_percent, 0.0)
        self.assertGreater(t.ram_total_gb, 0.0)
        self.assertGreater(t.disk_total_gb, 0.0)
        self.assertTrue(bool(t.hostname))
        self.assertGreaterEqual(t.uptime_hours, 0.0)

    def test_02_get_top_processes(self) -> None:
        """Verify top processes extraction returns requested count with memory and CPU."""
        procs = self.sentinel.get_top_processes(limit=3)
        self.assertIsInstance(procs, list)
        self.assertLessEqual(len(procs), 3)
        if procs:
            first = procs[0]
            self.assertIn("pid", first)
            self.assertIn("name", first)
            self.assertIn("memory_mb", first)
            self.assertIn("cpu_percent", first)

    def test_03_safe_terminate_process_protects_system_and_self(self) -> None:
        """Verify critical OS processes and self PID cannot be terminated."""
        import os
        my_pid = os.getpid()

        # Cannot terminate self
        res_self = self.sentinel.safe_terminate_process(my_pid)
        self.assertFalse(res_self["success"])
        self.assertIn("DarkShadow", res_self["message"])

        # Cannot terminate explorer.exe or svchost.exe
        res_sys = self.sentinel.safe_terminate_process("explorer.exe")
        self.assertFalse(res_sys["success"])
        self.assertIn("critical", res_sys["message"].lower())

    def test_04_format_telemetry_report(self) -> None:
        """Verify formatted report includes Captain address, metrics, and top apps."""
        report = self.sentinel.format_telemetry_report(include_top_procs=True)
        self.assertIn("Captain", report)
        self.assertIn("CPU:", report)
        self.assertIn("RAM:", report)
        self.assertIn("Storage", report)

    def test_05_dispatch_tool_telemetry_and_processes(self) -> None:
        """Verify tool registry dispatches telemetry tools cleanly."""
        res1 = dispatch_tool("get_system_telemetry", {})
        self.assertEqual(res1["status"], "ok")
        self.assertIn("Captain", res1["message"])
        self.assertIn("CPU:", res1["message"])

        res2 = dispatch_tool("get_top_processes", {"limit": 2})
        self.assertEqual(res2["status"], "ok")
        self.assertIn("Captain", res2["message"])
        self.assertIn("processes", res2["data"])


if __name__ == "__main__":
    unittest.main()
