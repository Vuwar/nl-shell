"""The console REPL's edit step.

Only the type-over path is exercised: a test run has redirected stdin, so
prefill_input returns None, which is the branch that actually runs in CI.
"""

import unittest
from unittest.mock import patch

from ai_shell_cli import app


class EditCommand(unittest.TestCase):
    def test_the_typed_command_replaces_the_original(self):
        with patch.object(app.current, "prefill_input", return_value=None), \
             patch("builtins.input", return_value="Remove-Item b.log"):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "Remove-Item b.log")

    def test_an_empty_line_cancels(self):
        with patch.object(app.current, "prefill_input", return_value=None), \
             patch("builtins.input", return_value=""):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "")

    def test_whitespace_only_cancels(self):
        with patch.object(app.current, "prefill_input", return_value=None), \
             patch("builtins.input", return_value="   "):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "")

    def test_a_prefilled_line_is_used_as_given(self):
        with patch.object(app.current, "prefill_input", return_value="Remove-Item c.log"):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "Remove-Item c.log")

    def test_a_cleared_prefilled_line_cancels(self):
        # "" from prefill_input is a user who deleted the whole line, which is
        # not the same answer as None.
        with patch.object(app.current, "prefill_input", return_value=""):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "")

    def test_the_fallback_is_not_used_when_prefill_works(self):
        with patch.object(app.current, "prefill_input", return_value="edited"), \
             patch("builtins.input") as fallback:
            app._edit_command("original")
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
