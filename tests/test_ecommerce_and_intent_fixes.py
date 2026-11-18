import unittest
from unittest.mock import MagicMock, patch

from automation import (
    parse_automation_command,
    parse_ordinal_selection,
    parsed_command_from_tool_call,
    ecommerce_multi_cart,
    APPLICATION_ALIASES,
)


class TestEcommerceAndIntentFixes(unittest.TestCase):

    def test_instagram_in_aliases(self):
        self.assertIn("instagram", APPLICATION_ALIASES)
        self.assertEqual(APPLICATION_ALIASES["instagram"], "instagram")

    def test_instagram_open_commands(self):
        queries = [
            "instagram open karo",
            "open instagram",
            "instagram kholo",
            "instagram open kar do",
            "instagram khol kar do",
            "instagram app open karo",
        ]
        for q in queries:
            res = parse_automation_command(q)
            self.assertIsNotNone(res, f"Failed to parse query: {q}")
            self.assertEqual(res.intent, "open_application", f"Query {q} did not resolve to open_application: {res}")
            self.assertIn("instagram", res.arguments["app_name"].lower())

    def test_hindi_verbs_do_not_trigger_youtube_ordinals(self):
        # Sentences with "kar do", "khol do", "bhej do" must not trigger play_youtube
        res1 = parse_automation_command("instagram open kar do")
        self.assertEqual(res1.intent, "open_application")
        self.assertNotEqual(res1.intent, "play_youtube")

        res2 = parse_automation_command("notepad khol kar do")
        self.assertEqual(res2.intent, "open_application")
        self.assertNotEqual(res2.intent, "play_youtube")

    def test_ordinal_selection_intact(self):
        self.assertEqual(parse_ordinal_selection("2nd wala chala do"), 2)
        self.assertEqual(parse_ordinal_selection("second video play karo"), 2)
        self.assertEqual(parse_ordinal_selection("doosra gana bajao"), 2)
        self.assertEqual(parse_ordinal_selection("2 number play karo"), 2)
        self.assertEqual(parse_ordinal_selection("do wala chalao"), 2)
        self.assertIsNone(parse_ordinal_selection("instagram open kar do"))
        self.assertIsNone(parse_ordinal_selection("gaana chala do"))

    def test_ecommerce_multi_cart_parsing(self):
        q1 = "Amazon aur Flipkart par 40000 ke neeche laptop cart me add karo"
        res1 = parse_automation_command(q1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.intent, "ecommerce_multi_cart")
        self.assertEqual(res1.arguments["product"], "laptop")
        self.assertEqual(res1.arguments["max_price"], 40000.0)
        self.assertIn("amazon", res1.arguments["platforms"])
        self.assertIn("flipkart", res1.arguments["platforms"])

        q2 = "Amazon pe gaming mouse add to cart karo"
        res2 = parse_automation_command(q2)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.intent, "ecommerce_multi_cart")
        self.assertEqual(res2.arguments["product"], "gaming mouse")
        self.assertEqual(res2.arguments["platforms"], ["amazon"])

        q3 = "Flipkart par headphones cart me daalo"
        res3 = parse_automation_command(q3)
        self.assertIsNotNone(res3)
        self.assertEqual(res3.intent, "ecommerce_multi_cart")
        self.assertEqual(res3.arguments["product"], "headphones")
        self.assertEqual(res3.arguments["platforms"], ["flipkart"])

    def test_tool_call_schema_validation(self):
        cmd = parsed_command_from_tool_call(
            "ecommerce_multi_cart",
            {"product": "laptop", "max_price": 40000.0, "platforms": ["amazon", "flipkart"]},
        )
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.intent, "ecommerce_multi_cart")
        self.assertEqual(cmd.arguments["product"], "laptop")
        self.assertEqual(cmd.arguments["max_price"], 40000.0)
        self.assertEqual(cmd.arguments["platforms"], ["amazon", "flipkart"])

    def test_ecommerce_multi_cart_execution(self):
        mock_engine = MagicMock()
        mock_engine.search_and_cart_amazon.return_value = {
            "success": True,
            "platform": "Amazon",
            "product": "ASUS Vivobook 15",
            "price": "₹38,990",
            "cart_success": True,
            "url": "https://www.amazon.in/dp/example",
        }
        mock_engine.search_and_cart_flipkart.return_value = {
            "success": True,
            "platform": "Flipkart",
            "product": "HP 15s Ryzen 3",
            "price": "₹36,490",
            "cart_success": True,
            "url": "https://www.flipkart.com/example",
        }

        with patch("browser_engine.get_browser_engine", return_value=mock_engine):
            res = ecommerce_multi_cart(
                product="laptop",
                max_price=40000,
                platforms=["amazon", "flipkart"],
            )
            self.assertTrue(res.success)
            self.assertIn("Amazon", res.message)
            self.assertIn("Flipkart", res.message)
            self.assertIn("ASUS Vivobook 15", res.message)
            self.assertIn("HP 15s Ryzen 3", res.message)


if __name__ == "__main__":
    unittest.main()
