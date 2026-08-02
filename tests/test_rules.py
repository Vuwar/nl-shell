"""ai_shell.rules - the frame every rule plugs into.

Separate from the tests for any one rule on purpose. These are about the parts
that don't change when a rule is added: what an Answer turns into, what a rule
is allowed to ask about the machine, what the registry does with a rule that
declines, and the fact that a recognised request never reaches the model.

The wire format is tested in exactly one place, which is the point of having
it in exactly one place. A rule that built its own dict would need its own
copy of these.
"""

import unittest
from unittest import mock
from unittest.mock import patch

from ai_shell import rules
from ai_shell.rules import base
from ai_shell.session import Session
from tests.stubs import StubClient


class WhatAnAnswerBecomes(unittest.TestCase):
    """base.Answer.as_data - the one place the field names are spelled."""

    def test_a_command_to_run(self):
        data = base.run("Get-Date", "Shows the time.").as_data()
        self.assertEqual(data, {
            "command": "Get-Date", "search": None, "risk": "safe",
            "explanation": "Shows the time.", "options": None,
        })

    def test_a_web_lookup_has_no_risk(self):
        # Nothing runs on this machine, so there is nothing to classify.
        data = base.look_up("python latest version", "Looking that up.").as_data()
        self.assertIsNone(data["risk"])
        self.assertIsNone(data["command"])
        self.assertEqual(data["search"], "python latest version")

    def test_a_question_back_to_the_user(self):
        data = base.ask("Which browser?", ["Firefox", "Edge"]).as_data()
        self.assertEqual(data["options"], ["Firefox", "Edge"])
        self.assertEqual(data["explanation"], "Which browser?")
        self.assertIsNone(data["command"])

    def test_an_answer_in_words(self):
        data = base.say("Hey! Tell me what you'd like to do.").as_data()
        self.assertIsNone(data["command"])
        self.assertIsNone(data["search"])
        self.assertIsNone(data["options"])

    def test_a_rule_can_call_its_own_command_risky(self):
        self.assertEqual(base.run("rm -rf x", "Deletes x.", risk="risky").as_data()["risk"], "risky")

    def test_a_url_goes_through_the_platform(self):
        # The rule says "open this address"; which cmdlet or binary does it is
        # the platform's business, not the rule's.
        from ai_shell.platforms import current
        self.assertEqual(
            base.open_url("https://example.com", "Opens it.").command,
            current.open_command("https://example.com"),
        )


class AskingAboutTheMachine(unittest.TestCase):
    """base.Machine - the narrow view of this computer a rule gets."""

    def test_an_installed_app_is_found(self):
        machine = base.Machine(lambda: [("Spotify", "spotify.exe")])
        self.assertTrue(machine.has_app("Spotify"))

    def test_the_match_is_exact(self):
        machine = base.Machine(lambda: [("Google Chrome", "chrome.exe")])
        self.assertFalse(machine.has_app("Google"))

    def test_case_does_not_matter(self):
        self.assertTrue(base.Machine(lambda: [("SPOTIFY", "x")]).has_app("spotify"))

    def test_nothing_is_scanned_until_a_rule_asks(self):
        # The Start Menu scan takes long enough to notice and most requests
        # never need it, so the callable is what gets passed around.
        scans = []

        def scan():
            scans.append(1)
            return []

        machine = base.Machine(scan)
        self.assertEqual(scans, [])
        machine.has_app("Spotify")
        self.assertEqual(scans, [1])

    def test_a_failed_scan_is_not_an_error(self):
        self.assertFalse(base.Machine(lambda: None).has_app("Spotify"))


class TidyingUp(unittest.TestCase):
    """base.clean and the shared reasons to hand a request back."""

    def test_politeness_comes_off(self):
        self.assertEqual(base.clean("can you open youtube"), "open youtube")

    def test_more_than_one_softener_comes_off(self):
        self.assertEqual(base.clean("hey can you open youtube"), "open youtube")

    def test_whitespace_is_collapsed(self):
        self.assertEqual(base.clean("  open    youtube  "), "open youtube")

    def test_trailing_punctuation_comes_off(self):
        self.assertEqual(base.clean("open youtube!!"), "open youtube")

    def test_nothing_typed_is_nothing_cleaned(self):
        self.assertEqual(base.clean(""), "")
        self.assertEqual(base.clean(None), "")

    def test_a_wh_question_is_recognised(self):
        self.assertTrue(base.is_question("how do i open youtube"))
        self.assertFalse(base.is_question("open youtube"))

    def test_a_question_is_offered_not_imposed(self):
        # clean() deliberately leaves questions alone: a future rule about
        # disk space wants "how much free space do i have".
        self.assertEqual(base.clean("how much free space do i have"),
                         "how much free space do i have")

    def test_the_doubtful_cases(self):
        self.assertTrue(base.doubtful("it"))
        self.assertTrue(base.doubtful("C:\\Users\\Me\\clip.mp4"))
        self.assertTrue(base.doubtful("resume.pdf"))
        self.assertTrue(base.doubtful("a " * 40))
        self.assertFalse(base.doubtful("eminem"))
        self.assertFalse(base.doubtful("st. louis"))


class TheRegistry(unittest.TestCase):
    """rules.resolve - what happens with more than one rule in the list."""

    def _with(self, *fake_rules):
        return mock.patch.object(rules, "RULES", fake_rules)

    def test_the_first_rule_that_recognises_it_wins(self):
        first = lambda text, machine: base.run("first", "first")
        second = lambda text, machine: base.run("second", "second")
        with self._with(first, second):
            self.assertEqual(rules.resolve("anything").command, "first")

    def test_a_rule_that_declines_passes_the_turn_on(self):
        with self._with(lambda text, machine: None, lambda text, machine: base.run("b", "b")):
            self.assertEqual(rules.resolve("anything").command, "b")

    def test_no_rule_recognising_it_is_not_a_failure(self):
        # The normal case. It means the model gets the request, which is what
        # the app is for.
        with self._with(lambda text, machine: None):
            self.assertIsNone(rules.resolve("anything"))

    def test_rules_are_handed_the_tidied_text(self):
        seen = []
        with self._with(lambda text, machine: seen.append(text)):
            rules.resolve("  can you   open youtube?  ")
        self.assertEqual(seen, ["open youtube"])

    def test_an_empty_request_reaches_no_rule(self):
        seen = []
        with self._with(lambda text, machine: seen.append(text)):
            rules.resolve("   ")
        self.assertEqual(seen, [])

    def test_a_rule_gets_a_machine_even_when_the_caller_gives_none(self):
        seen = []
        with self._with(lambda text, machine: seen.append(machine)):
            rules.resolve("open youtube")
        self.assertFalse(seen[0].has_app("Spotify"))


class EveryInputTheRulesClaim(unittest.TestCase):
    """A place to paste inputs and say what should happen to them.

    This is the table to grow while trying things out: the request as typed,
    and either a piece of the command it must produce or None for "the model
    handles this one". Both columns matter - a rule that quietly took over
    "open notepad" would be a worse bug than one that missed a website.
    """

    CASES = (
        ("open eminem on youtube", "youtube.com/results?search_query=eminem"),
        ("open eminem in youtube", "youtube.com/results?search_query=eminem"),
        ("play lofi on youtube", "youtube.com/results?search_query=lofi"),
        ("open youtube", "https://www.youtube.com"),
        ("open google", "https://www.google.com"),
        ("open twitter", "https://x.com"),
        ("open x", "https://x.com"),
        ("open reddit", "https://www.reddit.com"),
        ("open github", "https://github.com"),
        ("open chatgpt", "https://chatgpt.com"),
        ("open netflix", "https://www.netflix.com"),
        ("open spotify", "https://open.spotify.com"),
        ("open spotify and play rap", "open.spotify.com/search/rap"),
        ("look up mount everest on wikipedia", "en.wikipedia.org"),
        ("find coffee on google maps", "google.com/maps/search/coffee"),

        ("play some music", None),
        ("search for cheap flights to istanbul", None),
        ("open my github profile", None),
        ("open the calculator", None),
        ("open notepad", None),
        ("open paint", None),
        ("open vscode", None),
        ("open vscode in this folder", None),
        ("open this folder in explorer", None),
        ("open my downloads folder", None),
        ("open my desktop", None),
        ("open a new terminal window", None),
        # "open file explorer", "open command prompt" and "open the recycle
        # bin" used to sit here. A rule claims them now, and what it produces
        # depends on the OS, so they're asserted in test_apps.py instead of
        # against a fixed string here.
        ("open powershell as admin", None),
        ("open X photo", None),
        ("open the photo i took yesterday", None),
        ("open the newest image in downloads", None),
        ("open all the pdfs on my desktop", None),
        ("open resume.pdf", None),
        ("open the last file i edited", None),
        ("open notes.txt in notepad", None),
        ("what's the latest version of python", None),
        ("how much disk space have i got left", None),
        ("delete the youtube shortcut on my desktop", None),
        ("hey", None),
    )

    def test_every_case(self):
        machine = base.Machine(tuple)
        for text, expected in self.CASES:
            with self.subTest(text):
                answer = rules.resolve(text, machine)
                if expected is None:
                    self.assertIsNone(answer, f"a rule took over {text!r}")
                else:
                    self.assertIsNotNone(answer, f"no rule handled {text!r}")
                    self.assertIn(expected, answer.command)


class ThroughTheSession(unittest.TestCase):
    """What the user sees: a command, not a search - and no model round trip."""

    def setUp(self):
        patcher = patch("ai_shell.session.list_apps", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _session(self, apps=None):
        session = Session()
        session.client = StubClient('{"command": null, "search": "eminem youtube", '
                                    '"risk": null, "explanation": "Looking that up.", '
                                    '"options": null}')
        if apps is not None:
            session._apps = apps
        return session

    def test_the_request_becomes_a_command(self):
        data = self._session().translate("open eminem on youtube")
        self.assertIn("https://www.youtube.com/results?search_query=eminem", data["command"])
        self.assertEqual(data["risk"], "safe")

    def test_it_is_not_a_web_search(self):
        self.assertIsNone(self._session().translate("open eminem on youtube")["search"])

    def test_the_model_is_never_asked(self):
        # The whole point of answering these here: no GPU, no waiting, no
        # chance of a 3B model deciding this one is a question after all.
        session = self._session()
        session.translate("open eminem on youtube")
        self.assertEqual(session.client.calls, 0)

    def test_the_command_is_ready_to_run(self):
        session = self._session()
        data = session.translate("open eminem on youtube")
        self.assertEqual(session._pending["command"], data["command"])

    def test_a_request_no_rule_claims_still_reaches_the_model(self):
        session = self._session()
        session.translate("what's the latest version of python")
        self.assertEqual(session.client.calls, 1)

    def test_the_turn_is_recorded_so_follow_ups_still_work(self):
        session = self._session()
        session.translate("open eminem on youtube")
        self.assertEqual(session.history[0]["content"], "open eminem on youtube")
        self.assertEqual(len(session.history), 2)

    def test_the_installed_app_question_reaches_the_session_scan(self):
        # The wiring that lets a rule ask about this machine: the Machine the
        # session hands over has to be reading the session's own app scan.
        session = self._session(apps=[("Spotify", "spotify.exe")])
        session.translate("open spotify")
        self.assertEqual(session.client.calls, 1)

    def test_the_rules_do_not_report_a_model_speed(self):
        # Nothing was generated, so there is nothing to time - and the
        # graphics-card notice must not appear for a request that never
        # touched the card.
        session = self._session()
        self.assertIsNone(session.translate("open eminem on youtube")["notice"])

    def test_policy_still_reads_what_a_rule_produced(self):
        # A rule saying "safe" is not the last word. If one ever emits
        # something destructive, the same rules that check the model's output
        # have to catch it.
        session = self._session()
        with mock.patch.object(rules, "RULES",
                               (lambda text, machine: base.run("Remove-Item notes.txt", "Deletes."),)):
            data = session.translate("do the thing")
        self.assertEqual(data["risk"], "risky")
        self.assertIn("delete", data["risk_reason"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
