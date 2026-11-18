"""Tests for DarkShadow Strict Payment & Financial Shield."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from automation import (
    ParsedAutomationCommand,
    ecommerce_multi_cart,
    execute_automation_command,
    handle_automation_command,
    vision_browser_goal,
)
from browser_engine import DarkShadowBrowserEngine
from chatbot import DarkShadowChatbot
from config import Settings
from safety import (
    PAYMENT_BLOCKED_MESSAGE,
    is_payment_or_checkout_intent,
)


class TestPaymentShield(unittest.TestCase):

    def test_payment_intent_detection(self):
        """Test identification of payment and checkout keywords across languages."""
        self.assertTrue(is_payment_or_checkout_intent("buy now"))
        self.assertTrue(is_payment_or_checkout_intent("proceed to pay"))
        self.assertTrue(is_payment_or_checkout_intent("payment karo"))
        self.assertTrue(is_payment_or_checkout_intent("UPI pin enter karo"))
        self.assertTrue(is_payment_or_checkout_intent("credit card se checkout"))
        self.assertTrue(is_payment_or_checkout_intent("kharido yeh product"))
        self.assertTrue(is_payment_or_checkout_intent("order place karo"))
        self.assertTrue(is_payment_or_checkout_intent("enter cvv 123"))

        # Benign non-payment requests
        self.assertFalse(is_payment_or_checkout_intent("laptop search karo"))
        self.assertFalse(is_payment_or_checkout_intent("cart me add karo"))
        self.assertFalse(is_payment_or_checkout_intent("open chrome"))
        self.assertFalse(is_payment_or_checkout_intent("play youtube video"))

    def test_ecommerce_cart_blocks_payment(self):
        """ecommerce_multi_cart must strictly block payment/checkout intents."""
        res = ecommerce_multi_cart("buy now iphone 15")
        self.assertFalse(res.success)
        self.assertEqual(res.action, "payment_blocked")
        self.assertEqual(res.error, "payment_prohibited")
        self.assertIn("Security protocol", res.message)

    def test_vision_browser_goal_blocks_payment(self):
        """vision_browser_goal must refuse execution on checkout or payment screens."""
        res = vision_browser_goal("Click Proceed to Pay button")
        self.assertFalse(res.success)
        self.assertEqual(res.action, "payment_blocked")
        self.assertEqual(res.error, "payment_prohibited")

    def test_handle_automation_command_blocks_payment(self):
        """handle_automation_command blocks direct payment requests."""
        res = handle_automation_command("Amazon par payment karo")
        self.assertIsNotNone(res)
        self.assertFalse(res.success)
        self.assertEqual(res.action, "payment_blocked")

    def test_execute_automation_command_blocks_payment(self):
        """execute_automation_command intercepts any payment intent."""
        cmd = ParsedAutomationCommand("open_website", {"url_or_name": "https://payment.gateway.com/pay_now"})
        res = execute_automation_command(cmd)
        self.assertFalse(res.success)
        self.assertEqual(res.action, "payment_blocked")

    def test_browser_engine_methods_block_payment(self):
        """Browser engine methods refuse payment intents."""
        engine = DarkShadowBrowserEngine(headless=True)
        res_amz = engine.search_and_cart_amazon("buy now laptop")
        self.assertFalse(res_amz["success"])
        self.assertEqual(res_amz["error"], "payment_prohibited")

        res_flip = engine.search_and_cart_flipkart("proceed to pay phone")
        self.assertFalse(res_flip["success"])
        self.assertEqual(res_flip["error"], "payment_prohibited")

    def test_chatbot_respond_blocks_payment(self):
        """Chatbot layer aborts with payment blocked response."""
        bot = DarkShadowChatbot(Settings(api_key="test_key"), client=MagicMock())
        resp = bot.respond("Credit card se payment kardo")
        self.assertEqual(resp.intent, "payment_blocked")
        self.assertEqual(resp.error, "payment_prohibited")
        self.assertIn("Security protocol", resp.display_text)
