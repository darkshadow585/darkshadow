"""Tests for DarkShadow Upgraded Automation Suite using unittest."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation import (
    get_clipboard_text,
    lock_workstation,
    parse_automation_command,
    save_quick_note,
    search_local_files,
    set_clipboard_text,
    trigger_media_key,
    _scan_windows_installed_applications,
)
from whatsapp_engine import (
    normalize_whatsapp_phone,
    send_twilio_whatsapp,
    send_whatsapp_cloud_api,
)


class TestUpgradedAutomation(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_whatsapp_phone_normalization(self):
        self.assertEqual(normalize_whatsapp_phone("9876543210"), "+919876543210")
        self.assertEqual(normalize_whatsapp_phone("+919876543210"), "+919876543210")
        self.assertEqual(normalize_whatsapp_phone("09876543210"), "+919876543210")
        self.assertEqual(normalize_whatsapp_phone("+14155552671"), "+14155552671")
        self.assertIsNone(normalize_whatsapp_phone("Rahul"))
        self.assertIsNone(normalize_whatsapp_phone(""))

    def test_whatsapp_cloud_api_mock(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b'{"messages": [{"id": "wamid.HBgL"}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            res = send_whatsapp_cloud_api(
                phone_number_id="123456789",
                access_token="test_token",
                recipient_phone="+919876543210",
                message="Hello Captain",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["provider"], "cloud_api")
            self.assertEqual(res["message_id"], "wamid.HBgL")

    def test_whatsapp_twilio_mock(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 201
            mock_resp.read.return_value = b'{"sid": "SM123456", "status": "queued"}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            res = send_twilio_whatsapp(
                account_sid="ACtest",
                auth_token="authtest",
                from_number="+14155238886",
                recipient_phone="+919876543210",
                message="Test twilio msg",
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["provider"], "twilio")
            self.assertEqual(res["message_sid"], "SM123456")

    def test_media_keys(self):
        res = trigger_media_key("play_pause")
        self.assertEqual(res.action, "trigger_media_key")
        if os.name == "nt":
            self.assertTrue(res.success)

        res_invalid = trigger_media_key("invalid_key_xyz")
        self.assertFalse(res_invalid.success)

    def test_lock_workstation(self):
        with patch("ctypes.windll.user32.LockWorkStation", return_value=1, create=True):
            res = lock_workstation()
            if os.name == "nt":
                self.assertTrue(res.success)
                self.assertIn("PC lock", res.message)

    def test_search_local_files(self):
        test_file = Path(self.test_dir) / "sample_report.pdf"
        test_file.write_text("dummy")

        res = search_local_files(query="sample_report", directory=self.test_dir)
        self.assertTrue(res.success)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertEqual(res.data["results"][0]["name"], "sample_report.pdf")

    def test_save_quick_note(self):
        with patch("config.load_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.notes_directory = Path(self.test_dir) / "notes"
            mock_settings.return_value = mock_s

            res = save_quick_note("Project Kickoff", "Launch new AI automation stack")
            self.assertTrue(res.success)
            self.assertIn("Project Kickoff", res.message)
            self.assertTrue((Path(self.test_dir) / "notes").exists())

    def test_clipboard_operations(self):
        res = set_clipboard_text("DarkShadow Copied Text")
        self.assertTrue(res.success)
        res_get = get_clipboard_text()
        self.assertTrue(res_get.success)

    def test_scan_windows_installed_applications(self):
        apps = _scan_windows_installed_applications()
        self.assertIsInstance(apps, dict)

    def test_parse_automation_command_new_intents(self):
        # Media keys
        p1 = parse_automation_command("pause song")
        self.assertIsNotNone(p1)
        self.assertEqual(p1.intent, "trigger_media_key")
        self.assertEqual(p1.arguments["key"], "play_pause")

        p2 = parse_automation_command("next song")
        self.assertIsNotNone(p2)
        self.assertEqual(p2.intent, "trigger_media_key")
        self.assertEqual(p2.arguments["key"], "next")

        # Lock workstation
        p3 = parse_automation_command("screen lock karo")
        self.assertIsNotNone(p3)
        self.assertEqual(p3.intent, "lock_workstation")

        # Clipboard
        p4 = parse_automation_command("clipboard padho")
        self.assertIsNotNone(p4)
        self.assertEqual(p4.intent, "get_clipboard_text")

        # Quick note
        p5 = parse_automation_command("note likho Meeting : Kal subah 10 baje")
        self.assertIsNotNone(p5)
        self.assertEqual(p5.intent, "save_quick_note")
        self.assertEqual(p5.arguments["title"], "Meeting")
        self.assertEqual(p5.arguments["content"], "Kal subah 10 baje")

        # File search
        p6 = parse_automation_command("search file invoice")
        self.assertIsNotNone(p6)
        self.assertEqual(p6.intent, "search_local_files")
        self.assertEqual(p6.arguments["query"], "invoice")


if __name__ == "__main__":
    unittest.main()
