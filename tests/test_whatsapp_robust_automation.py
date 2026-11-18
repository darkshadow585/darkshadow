import unittest
from unittest.mock import patch, MagicMock
from tool_registry import dispatch_tool, normalize_tool_arguments
import automation


class TestWhatsAppRobustAutomation(unittest.TestCase):
    def test_normalize_whatsapp_tool_calls(self):
        name, args = normalize_tool_arguments("send_whatsapp_message", {"contact_name": "Kuldeep", "message": "Hello"})
        self.assertEqual(name, "send_whatsapp_message")
        self.assertEqual(args.get("recipient"), "Kuldeep")
        self.assertEqual(args.get("message"), "Hello")

        name, args = normalize_tool_arguments("search_whatsapp_contact", {"contact_name": "Kuldeep"})
        self.assertEqual(name, "search_whatsapp_contact")
        self.assertEqual(args.get("contact_name"), "Kuldeep")

        name, args = normalize_tool_arguments("prepare_whatsapp_message", {"recipient": "9876543210", "message": "Draft"})
        self.assertEqual(name, "prepare_whatsapp_message")
        self.assertEqual(args.get("recipient"), "9876543210")

    def test_search_whatsapp_contact_fails_honestly_when_not_found(self):
        with patch("automation._wait_for_whatsapp_window", return_value=0):
            res = automation.search_whatsapp_contact("Kuldeep")
            self.assertFalse(res.success)
            self.assertEqual(res.error, "whatsapp_window_not_found")
            self.assertIn("WhatsApp Desktop open ya screen par focus nahi ho saka", res.message)

    def test_send_whatsapp_message_fails_honestly_when_not_found(self):
        with patch("automation._wait_for_whatsapp_window", return_value=0), \
             patch("contact.resolve_contact_phone", return_value=None):
            res = automation.send_whatsapp_message("UnknownPersonXYZ", "Hello")
            self.assertFalse(res.success)
            self.assertEqual(res.error, "whatsapp_window_not_found")

    def test_search_whatsapp_contact_success_flow(self):
        with patch("automation._wait_for_whatsapp_window", return_value=12345), \
             patch("automation._bring_window_to_foreground", return_value=True), \
             patch("pyautogui.press") as mock_press, \
             patch("pyautogui.hotkey") as mock_hotkey, \
             patch("pyperclip.copy") as mock_copy:

            res = automation.search_whatsapp_contact("Kuldeep")
            self.assertTrue(res.success)
            self.assertIn("Kuldeep", res.message)
            mock_hotkey.assert_any_call("ctrl", "n")
            mock_copy.assert_called_with("Kuldeep")
            mock_hotkey.assert_any_call("ctrl", "v")
            mock_press.assert_any_call("enter")

    def test_dispatch_tool_send_whatsapp_message_integration(self):
        with patch("automation._wait_for_whatsapp_window", return_value=12345), \
             patch("automation._bring_window_to_foreground", return_value=True), \
             patch("automation._search_contact_and_send", return_value=None):

            res = dispatch_tool("send_whatsapp_message", {"contact_name": "Kuldeep", "message": "Test msg"})
            self.assertEqual(res.get("status"), "ok")
            self.assertIn("Kuldeep", res.get("message", ""))

    def test_dummy_phone_detection_and_fallback(self):
        from contact import is_dummy_phone
        self.assertTrue(is_dummy_phone("9876543210"))
        self.assertTrue(is_dummy_phone("+919876543210"))
        self.assertTrue(is_dummy_phone("9876543212"))
        self.assertTrue(is_dummy_phone("1234567890"))
        self.assertFalse(is_dummy_phone("+917897179414"))
        self.assertFalse(is_dummy_phone("+919651912545"))

        # When recipient has a dummy phone number, send_whatsapp_message should NOT call startfile with phone URI,
        # but instead should search by contact name via _search_contact_and_send
        with patch("contact.resolve_contact_phone", return_value="+919876543210"), \
             patch("automation._wait_for_whatsapp_window", return_value=12345), \
             patch("automation._bring_window_to_foreground", return_value=True), \
             patch("automation._search_contact_and_send", return_value=None) as mock_search_send, \
             patch("os.startfile") as mock_startfile:

            res = automation.send_whatsapp_message("Kuldeep", "Hello test")
            self.assertTrue(res.success)
            mock_startfile.assert_called_with("whatsapp://")
            mock_search_send.assert_called_once_with(12345, "Kuldeep", "Hello test")


if __name__ == "__main__":
    unittest.main()
