"""Switches the shell can't flip, and choices it can't vouch for.

Both halves of the same failure. Asked to "toggle bluetooth", the model had no
honest command available - the radio is not a service, disabling the device
needs administrator rights, the real switch is a WinRT call - so it invented
its way out:

    Which Bluetooth device would you like to toggle?
    [ Bluetooth Adapter 1 ]  [ Bluetooth Adapter 2 ]  [ Other... ]

    > Bluetooth Adapter 1
    Set-Service -Name 'bthserv' -StartupType 'Automatic'

One adapter on the machine, named neither of those. The pick told the model
nothing, and the command it produced changes a startup type and toggles
nothing at all.

The fix has two parts, because either alone leaves the hole open. The request
now has a real answer that needs no model (open the page the switch is on),
and choices that the shell could not check against something real are dropped
instead of shown.
"""

import unittest
from unittest.mock import patch

from ai_shell import rules
from ai_shell.platforms import current
from ai_shell.session import Session
from tests.stubs import StubClient

HAS_TOGGLES = bool(current.SETTINGS_TOGGLES)
WINDOWS = current.OS_NAME == "Windows"


def _resolve(text):
    return rules.resolve(text, rules.Machine(tuple))


@unittest.skipUnless(WINDOWS, "the pages asserted here are Windows ones")
class TheReportedRequest(unittest.TestCase):

    def test_toggle_bluetooth_opens_the_page(self):
        answer = _resolve("toggle bluetooth")
        self.assertIn("ms-settings:bluetooth", answer.command)

    def test_it_says_it_is_not_the_switch(self):
        # Substituting quietly would be worse than failing. Substituting
        # openly, when the honest alternative is a command that cannot work,
        # is the better answer - but only if it says so.
        answer = _resolve("toggle bluetooth")
        self.assertIn("can't flip it", answer.explanation)

    def test_wifi_too(self):
        self.assertIn("ms-settings:network-wifi", _resolve("toggle wifi").command)

    def test_it_never_asks_which_device(self):
        for text in ("toggle bluetooth", "turn off bluetooth", "toggle wifi"):
            with self.subTest(text):
                self.assertIsNone(_resolve(text).options)


@unittest.skipUnless(HAS_TOGGLES, "this platform has no toggle table")
class HowItIsPhrased(unittest.TestCase):

    def test_the_state_can_come_first_or_last(self):
        first = _resolve("turn off bluetooth")
        last = _resolve("turn bluetooth off")
        self.assertEqual(first.command, last.command)

    def test_the_other_verbs(self):
        for text in ("switch off bluetooth", "enable bluetooth", "disable bluetooth",
                     "toggle bluetooth", "put bluetooth back on",
                     "turn the microphone off"):
            with self.subTest(text):
                self.assertIsNotNone(_resolve(text))

    def test_opening_it_is_safe(self):
        # Opening a settings page changes nothing, so nothing should stop to
        # ask - which is the whole reason this beats a Set-Service.
        self.assertEqual(_resolve("toggle bluetooth").risk, "safe")


@unittest.skipUnless(HAS_TOGGLES, "this platform has no toggle table")
class NotAToggle(unittest.TestCase):

    def _rejected(self, text):
        self.assertIsNone(_resolve(text), f"should not have matched: {text}")

    def test_a_question_about_it(self):
        self._rejected("is bluetooth on")
        self._rejected("how do i turn off bluetooth")

    def test_something_not_in_the_table(self):
        self._rejected("toggle the firewall")
        self._rejected("turn off the printer")

    def test_a_file_that_shares_a_word(self):
        self._rejected("delete bluetooth.log")

    def test_asking_for_the_page_itself_is_the_other_rules_job(self):
        # "open bluetooth settings" is a system tool being opened, not a
        # switch being flipped, so it answers plainly rather than explaining
        # what it can't do.
        answer = _resolve("open bluetooth settings")
        self.assertNotIn("can't flip", answer.explanation)


class ChoicesTheShellCannotCheck(unittest.TestCase):
    """The second half: options are dropped unless they were grounded."""

    def _session(self, options, request, apps=None):
        import json
        reply = json.dumps({
            "command": None, "search": None, "risk": None,
            "explanation": "Which one did you mean?", "options": options,
        })
        with patch("ai_shell.session.list_apps", return_value=[]):
            session = Session()
        session.client = StubClient(reply)
        session._apps = apps if apps is not None else []
        return session.translate(request)

    def test_invented_devices_are_dropped(self):
        data = self._session(["Bluetooth Adapter 1", "Bluetooth Adapter 2"],
                             "toggle the firewall")
        self.assertIsNone(data["options"])

    def test_the_question_itself_survives(self):
        # Dropping the choices must not drop the question - the user can
        # still answer in words.
        data = self._session(["Network 1", "Network 2"], "toggle the firewall")
        self.assertEqual(data["explanation"], "Which one did you mean?")

    def test_app_choices_are_still_grounded_not_dropped(self):
        # The launch path still checks against the installed list and keeps
        # what matches, which is what makes "open a browser" work.
        with patch("ai_shell.session.pick_installed_apps", return_value=["Firefox"]):
            data = self._session(["Firefox", "Safari"], "open a browser",
                                 apps=[("Firefox", "firefox.exe")])
        self.assertEqual(data["options"], ["Firefox"])

    def test_a_broken_app_scan_keeps_the_models_suggestions(self):
        # An empty scan means the scan failed, not that nothing is installed.
        # Degrading the question because our own lookup fell over would be
        # the wrong way round.
        data = self._session(["Firefox", "Chrome"], "open a browser", apps=[])
        self.assertEqual(data["options"], ["Firefox", "Chrome"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
