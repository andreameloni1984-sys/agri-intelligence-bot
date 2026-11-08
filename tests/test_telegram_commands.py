import unittest
from unittest.mock import patch
from oracle.telegram_commands import handle_command


class TelegramCommandTests(unittest.TestCase):
    def test_help_lists_read_only_commands(self):
        result = handle_command("/help")
        self.assertIn("/status", result)
        self.assertIn("/report", result)
        self.assertIn("/calendario", result)
        self.assertNotIn("ordine", result.lower())

    def test_bot_mention_is_accepted(self):
        with patch("oracle.telegram_commands._format_status", return_value="OK"):
            self.assertEqual(handle_command("/status@oracle_bot"), "OK")

    def test_unknown_command_is_safe(self):
        self.assertIn("non riconosciuto", handle_command("/buy"))


if __name__ == "__main__":
    unittest.main()
