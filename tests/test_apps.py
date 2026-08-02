"""ai_shell.rules.apps - the system tools, answered the same way every time.

"Open registry editor" was going through the model, and the model's answer
depended on what had been typed before it: a fresh session called it safe and
ran it, a session with a few turns of history above it called it risky and
stopped to ask. Same request, same machine, same temperature, different
answer. Inconsistency is its own bug - a confirmation that appears sometimes
teaches nothing except that confirmations are noise.

These tools also aren't in the Start Menu index under the names people call
them, so the app-launch fallback can't rescue a wrong guess. `taskmgr`,
`devmgmt.msc` and `ms-settings:bluetooth` are facts, and facts belong in a
table.

Ordinary applications are deliberately not in it. Notepad and Chrome are in
the Start Menu, the model handles them, and a second list of them would be one
more thing to keep in step.
"""

import unittest

from ai_shell import policy, rules
from ai_shell.platforms import current

HAS_TABLE = bool(current.SYSTEM_APPS)
WINDOWS = current.OS_NAME == "Windows"


def _resolve(text):
    return rules.resolve(text, rules.Machine(tuple))


@unittest.skipUnless(WINDOWS, "the targets asserted here are Windows ones")
class TheWindowsTools(unittest.TestCase):

    def test_task_manager(self):
        answer = _resolve("open task manager")
        self.assertIn("taskmgr", answer.command)
        self.assertEqual(answer.explanation, "Opening Task Manager.")

    def test_registry_editor(self):
        self.assertIn("regedit", _resolve("open registry editor").command)

    def test_a_management_console(self):
        self.assertIn("devmgmt.msc", _resolve("open device manager").command)

    def test_a_settings_page(self):
        # The case from the bug report. "Bluetooth settings are already open"
        # was invented; this can't invent anything.
        self.assertIn("ms-settings:bluetooth", _resolve("open bluetooth settings").command)

    def test_the_recycle_bin(self):
        self.assertIn("RecycleBinFolder", _resolve("open the recycle bin").command)


@unittest.skipUnless(HAS_TABLE, "this platform has no system-tool table")
class HowItReads(unittest.TestCase):
    """Wording that should reach the same tool."""

    def _first_alias(self):
        return next(iter(current.SYSTEM_APPS))

    def test_a_definite_article_changes_nothing(self):
        alias = self._first_alias()
        self.assertEqual(_resolve(f"open {alias}").command,
                         _resolve(f"open the {alias}").command)

    def test_other_launch_verbs(self):
        alias = self._first_alias()
        for verb in ("open", "launch", "start", "bring up", "pull up"):
            with self.subTest(verb):
                self.assertIsNotNone(_resolve(f"{verb} {alias}"))

    def test_politeness_and_punctuation(self):
        alias = self._first_alias()
        self.assertIsNotNone(_resolve(f"can you open {alias}?"))


@unittest.skipUnless(HAS_TABLE, "this platform has no system-tool table")
class ItIsAlwaysTheSameAnswer(unittest.TestCase):
    """The property the model could not provide."""

    def test_the_model_is_never_asked(self):
        alias = self._alias()
        self.assertIsNotNone(_resolve(f"open {alias}"))

    def test_opening_a_tool_is_never_risky(self):
        # Opening one of these shows a window and changes nothing, so the
        # rules that read the finished command must agree - otherwise a rule
        # would produce a confirmation for something it just called safe.
        for alias, (_, target) in current.SYSTEM_APPS.items():
            with self.subTest(alias):
                answer = _resolve(f"open {alias}")
                self.assertEqual(answer.risk, "safe")
                self.assertIsNone(policy.escalate(answer.command))

    def _alias(self):
        return next(iter(current.SYSTEM_APPS))


@unittest.skipUnless(HAS_TABLE, "this platform has no system-tool table")
class NotASystemTool(unittest.TestCase):
    """What this must keep its hands off."""

    def _rejected(self, text):
        self.assertIsNone(_resolve(text), f"should not have matched: {text}")

    def test_a_question_about_a_tool(self):
        self._rejected(f"how do i open {next(iter(current.SYSTEM_APPS))}")

    def test_an_ordinary_application(self):
        # In the Start Menu, so the model and the app fallback handle it.
        self._rejected("open notepad")
        self._rejected("open chrome")

    def test_a_file_that_shares_a_word_with_a_tool(self):
        self._rejected("open settings.json")
        self._rejected("open my settings notes on the desktop")

    def test_doing_something_else_to_a_tool(self):
        self._rejected("delete task manager")
        self._rejected("what is the registry editor")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
