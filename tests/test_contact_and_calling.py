import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import contact
from automation import make_phone_call
from tool_registry import dispatch_tool


class TestContactAndCalling(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_json_path = Path(self.temp_dir.name) / "test_contacts.json"
        sample_contacts = [
            {"name": "Papa", "phone": "+919876543210", "aliases": ["dad", "pitaji"]},
            {"name": "Mummy", "phone": "+919876543211", "aliases": ["mom", "mataji"]},
            {"name": "Rohan Friend", "phone": "+919876543213", "aliases": ["rohan"]},
        ]
        self.test_json_path.write_text(json.dumps(sample_contacts, indent=2), encoding="utf-8")
        contact._CURRENT_CONTACTS_FILE = self.test_json_path

    def tearDown(self):
        contact._CURRENT_CONTACTS_FILE = None
        self.temp_dir.cleanup()

    def test_resolve_contact_phone_exact_and_fuzzy(self):
        self.assertEqual(contact.resolve_contact_phone("Papa"), "+919876543210")
        self.assertEqual(contact.resolve_contact_phone("papa"), "+919876543210")
        self.assertEqual(contact.resolve_contact_phone("dad"), "+919876543210")
        self.assertEqual(contact.resolve_contact_phone("Rohan"), "+919876543213")

    def test_add_contact_and_load(self):
        contact.add_contact("Vikas Brother", "+919988776655")
        loaded = contact.load_contacts()
        names = [c["name"] for c in loaded]
        self.assertIn("Vikas Brother", names)

    def test_import_contacts_json(self):
        import_file = Path(self.temp_dir.name) / "whatsapp_export.json"
        import_data = [
            {"name": "Aman", "number": "+919111222333"},
            {"name": "Sunita Di", "phone": "+919444555666"},
        ]
        import_file.write_text(json.dumps(import_data), encoding="utf-8")
        res = contact.import_contacts_file(import_file)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("imported"), 2)
        self.assertEqual(contact.resolve_contact_phone("Aman"), "+919111222333")

    def test_make_phone_call_adb_success(self):
        with patch("contact._find_adb_path", return_value="adb"), \
             patch("subprocess.check_output", return_value=b"List of devices attached\nemulator-5554\tdevice\n"), \
             patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc

            res = contact.make_phone_call("Papa")
            self.assertTrue(res["success"])
            self.assertEqual(res["method"], "adb")
            self.assertEqual(res["phone"], "+919876543210")
            mock_run.assert_called_once()
            call_cmd = mock_run.call_args[0][0]
            self.assertIn("android.intent.action.CALL", call_cmd)

    def test_make_phone_call_fallback_to_phonelink(self):
        with patch("contact._find_adb_path", return_value=None), \
             patch("os.startfile", create=True) as mock_startfile:
            res = contact.make_phone_call("9876543210")
            self.assertTrue(res["success"])
            self.assertEqual(res["method"], "phone_link")
            mock_startfile.assert_called_once_with("tel:+919876543210")

    def test_automation_make_phone_call_integration(self):
        with patch("contact._find_adb_path", return_value="adb"), \
             patch("subprocess.check_output", return_value=b"List of devices attached\nemulator-5554\tdevice\n"), \
             patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc

            res = make_phone_call("Papa")
            self.assertTrue(res.success)
            self.assertIn("Android phone se", res.message)
            self.assertIn("call laga diya", res.message)

    def test_dispatch_tool_make_phone_call(self):
        mock_mpc = MagicMock()
        from automation import AutomationResult
        mock_mpc.return_value = AutomationResult(True, "make_phone_call", "Call lag gayi", {})
        with patch.dict("automation._AUTOMATION_FUNCTIONS", {"make_phone_call": mock_mpc}):
            out = dispatch_tool("call_phone", {"contact": "Papa"})
            self.assertEqual(out.get("status"), "ok")
            mock_mpc.assert_called_once_with(recipient="Papa")

    def test_make_phone_call_explicit_phonelink(self):
        """Even if ADB is available, method='phone_link' forces Microsoft Mobile Link (Phone Link)."""
        with patch("contact._find_adb_path", return_value="adb"), \
             patch("subprocess.check_output", return_value=b"List of devices attached\nemulator-5554\tdevice\n"), \
             patch("os.startfile", create=True) as mock_startfile, \
             patch("subprocess.run") as mock_run:
            res = contact.make_phone_call("Papa", method="phone_link")
            self.assertTrue(res["success"])
            self.assertEqual(res["method"], "phone_link")
            self.assertEqual(res["phone"], "+919876543210")
            self.assertIn("Microsoft Mobile Link", res["message"])
            mock_startfile.assert_called_once_with("tel:+919876543210")

    def test_make_phone_call_tel_fails_falls_back_to_ms_phone(self):
        """When tel: protocol raises an exception, it falls back to ms-phone: URI."""
        with patch("contact._find_adb_path", return_value=None), \
             patch("os.startfile", create=True) as mock_startfile, \
             patch("subprocess.run"):
            def startfile_side_effect(uri):
                if uri.startswith("tel:"):
                    raise OSError("No tel protocol registered")
                return None
            mock_startfile.side_effect = startfile_side_effect

            res = contact.make_phone_call("Papa", method="phone_link")
            self.assertTrue(res["success"])
            self.assertEqual(res["method"], "phone_link")
            self.assertEqual(mock_startfile.call_count, 2)
            mock_startfile.assert_any_call("tel:+919876543210")
            mock_startfile.assert_any_call("ms-phone:")

    def test_make_phone_call_contact_not_found(self):
        res = contact.make_phone_call("NonExistentPersonXYZ")
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "contact_not_found")
        self.assertIn("NonExistentPersonXYZ", res["message"])

    def test_parse_automation_command_phone_call_intents(self):
        from automation import parse_automation_command

        test_cases = [
            ("Papa ko call lagao", "Papa", "phone_link"),
            ("Rahul ko phone karo", "Rahul", "phone_link"),
            ("Papa ko call kar do", "Papa", "phone_link"),
            ("Mummy ko phone laga do", "Mummy", "phone_link"),
            ("call Papa", "Papa", "phone_link"),
            ("phone Rahul", "Rahul", "phone_link"),
            ("dial 9876543210", "9876543210", "phone_link"),
            ("call lagao Papa ko", "Papa", "phone_link"),
            ("call karo 9876543210 ko", "9876543210", "phone_link"),
            ("mobile link se Papa ko call karo", "Papa", "phone_link"),
            ("phone link se Mummy ko call lagao", "Mummy", "phone_link"),
            ("microsoft mobile link se call lagao 9876543210 ko", "9876543210", "phone_link"),
            ("call Papa using mobile link", "Papa", "phone_link"),
            ("make a call to Shivani", "Shivani", "phone_link"),
            ("9876543210 par call lagao", "9876543210", "phone_link"),
            ("Papa ko phone", "Papa", "phone_link"),
        ]

        for query, expected_recip, expected_method in test_cases:
            with self.subTest(query=query):
                cmd = parse_automation_command(query)
                self.assertIsNotNone(cmd, f"Failed to parse call command: {query}")
                self.assertEqual(cmd.intent, "make_phone_call")
                self.assertEqual(cmd.arguments.get("recipient"), expected_recip)
                self.assertEqual(cmd.arguments.get("method"), expected_method)

    def test_parse_automation_command_non_calling_queries(self):
        from automation import parse_automation_command

        # Ensure non-calling commands don't trigger phone calls
        cmd1 = parse_automation_command("open phone link")
        self.assertIsNotNone(cmd1)
        self.assertEqual(cmd1.intent, "open_application")

        cmd2 = parse_automation_command("call center")
        self.assertIsNone(cmd2)

        cmd3 = parse_automation_command("phone ki battery kitni hai")
        self.assertIsNone(cmd3)

    def test_looks_like_automation_request_calling(self):
        from automation import looks_like_automation_request

        self.assertTrue(looks_like_automation_request("call Papa please"))
        self.assertTrue(looks_like_automation_request("phone lagao"))
        self.assertTrue(looks_like_automation_request("mobile link se call karo"))
        self.assertTrue(looks_like_automation_request("dial 9876543210"))


if __name__ == "__main__":
    unittest.main()

