"""Platform.prefill_input - asking for a line that already has something in it.

The prefilled paths can't be exercised here: a test run has redirected stdin
and no console to inject keystrokes into. What is tested is the contract the
CLI depends on - that "can't do that here" is reported as None and is
distinguishable from an empty answer.
"""

import unittest

from ai_shell.platforms.base import Platform


class BaseContract(unittest.TestCase):
    def test_the_base_platform_cannot_prefill(self):
        self.assertIsNone(Platform().prefill_input("> ", "Remove-Item a.log"))

    def test_none_is_not_an_empty_string(self):
        # The CLI tells "this platform can't" from "the user cleared the line"
        # by identity, so these must never collapse into each other.
        self.assertIsNot(Platform().prefill_input("> ", "x"), "")


if __name__ == "__main__":
    unittest.main()
