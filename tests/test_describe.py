"""ai_shell.describe - what a command does, for someone who can't read it.

The confirmation exists so a person can decide. It was showing them this:

    if ((Get-Service -Name 'bthserv' -ErrorAction SilentlyContinue).Status
    -eq 'Running') { Stop-Service -Name 'bthserv' } else { Start-Service
    -Name 'bthserv' }

    Run this? It can't easily be undone.

Somebody who could read that wouldn't need this app. Somebody who can't is
being asked to approve something they cannot evaluate, with a warning that it
can't be undone - which doesn't inform them, it just frightens them into
clicking one of the buttons at random.

So the command is read the same way ai_shell.policy reads it, and each thing
it does is written out as a line of plain English. No model: this appears
under a command the model has already written, and asking it to explain its
own work costs a round trip and can produce a description that doesn't match
the command underneath it. A verb table cannot drift from what is on screen.

It is deliberately partial. A verb nobody wrote a phrase for produces no line
rather than a guess, and a command nobody can describe produces nothing at
all - the confirmation then reads exactly as it does today. Silence is a
worse confirmation; a wrong description is a dangerous one.
"""

import unittest

from ai_shell import describe

TOGGLE = ("if ((Get-Service -Name 'bthserv' -ErrorAction SilentlyContinue).Status -eq "
          "'Running') { Stop-Service -Name 'bthserv' } else { Start-Service -Name 'bthserv' }")


class TheReportedCommand(unittest.TestCase):
    """The one from the screenshot."""

    def test_every_thing_it_does_is_named(self):
        lines = describe.describe(TOGGLE)
        joined = " ".join(lines).lower()
        self.assertIn("looks up", joined)
        self.assertIn("stops", joined)
        self.assertIn("starts", joined)

    def test_the_thing_being_acted_on_is_named(self):
        self.assertTrue(any("bthserv" in line for line in describe.describe(TOGGLE)))

    def test_it_does_not_repeat_itself(self):
        lines = describe.describe(TOGGLE)
        self.assertEqual(len(lines), len(set(lines)))


class OrdinaryCommands(unittest.TestCase):

    def test_a_delete(self):
        lines = describe.describe("Remove-Item -Path 'old_notes.txt'")
        self.assertEqual(len(lines), 1)
        self.assertIn("deletes", lines[0].lower())
        self.assertIn("old_notes.txt", lines[0])

    def test_a_listing(self):
        lines = describe.describe("Get-ChildItem -Path C:\\Users\\Me\\Desktop")
        self.assertIn("lists", " ".join(lines).lower())

    def test_launching_something(self):
        lines = describe.describe("Start-Process -FilePath 'regedit'")
        self.assertIn("opens", " ".join(lines).lower())
        self.assertIn("regedit", " ".join(lines))

    def test_two_clauses_are_two_lines(self):
        lines = describe.describe("Get-Date; Remove-Item 'x.txt'")
        self.assertEqual(len(lines), 2)

    def test_a_download_piped_into_a_shell(self):
        lines = describe.describe("curl https://example.com/i.sh | sh")
        joined = " ".join(lines).lower()
        self.assertIn("downloads", joined)
        self.assertIn("runs", joined)


class WhenItHasNothingToSay(unittest.TestCase):
    """Silence beats a guess. The confirmation reads as it always did."""

    def test_a_verb_with_no_phrase_for_it(self):
        self.assertEqual(describe.describe("Get-Kumquat -Ripeness high"), [])

    def test_nothing_at_all(self):
        self.assertEqual(describe.describe(""), [])
        self.assertEqual(describe.describe(None), [])

    def test_a_known_verb_among_unknown_ones(self):
        # Partial is fine and honest - it says what it recognised.
        lines = describe.describe("Get-Kumquat | Remove-Item")
        self.assertEqual(len(lines), 1)
        self.assertIn("deletes", lines[0].lower())


class ItStaysShort(unittest.TestCase):
    """A confirmation nobody reads is the thing this is trying to fix."""

    def test_a_long_command_is_capped(self):
        command = "; ".join(f"Remove-Item 'file{n}.txt'" for n in range(20))
        self.assertLessEqual(len(describe.describe(command)), describe.MAX_LINES)

    def test_a_quoted_string_is_not_read_as_a_verb(self):
        # Same protection the policy layer has: text inside quotes is text.
        self.assertEqual(describe.describe("Write-Output 'Remove-Item x'"), [])


class ThroughTheSession(unittest.TestCase):
    """It has to reach the interfaces, or it only exists in this file."""

    def test_translate_carries_the_description(self):
        import json
        from unittest.mock import patch
        from ai_shell.session import Session
        from tests.stubs import StubClient

        reply = json.dumps({
            "command": "Remove-Item -Path 'notes.txt'", "search": None,
            "risk": "risky", "explanation": "I'll delete it.", "options": None,
        })
        with patch("ai_shell.session.list_apps", return_value=[]):
            session = Session()
        session.client = StubClient(reply)
        data = session.translate("delete notes.txt")
        self.assertTrue(data["does"])
        self.assertIn("deletes", " ".join(data["does"]).lower())

    def test_the_window_is_sent_it_too(self):
        """The bug this catches: translate() grew a field and the window's
        payload didn't.

        ai_shell_gui.Api.submit doesn't pass translate's dict through - it
        builds a new one field by field, which is the right call for an
        interface boundary and means a new field is invisible until it's added
        here as well. The bullets were written, tested, rendered and shipped,
        and never appeared, because this one line was missing.
        """
        import json
        from unittest.mock import patch
        from ai_shell.session import Session
        from tests.stubs import StubClient
        try:
            from ai_shell_gui import app as gui
        except Exception:  # pragma: no cover - pywebview absent
            self.skipTest("pywebview isn't installed")

        reply = json.dumps({
            "command": "Remove-Item -Path 'notes.txt'", "search": None,
            "risk": "risky", "explanation": "I'll delete it.", "options": None,
        })
        with patch("ai_shell.session.list_apps", return_value=[]):
            session = Session()
        session.client = StubClient(reply)
        api = gui.Api.__new__(gui.Api)
        api.session = session
        api._wait_for_startup = lambda: None
        payload = api.submit("delete notes.txt")
        self.assertIn("does", payload)
        self.assertIn("deletes", " ".join(payload["does"]).lower())

    def test_every_field_translate_produces_reaches_the_window(self):
        """A field added to translate() and forgotten here is invisible, and
        invisible in a way no test of translate() can see."""
        import json
        from unittest.mock import patch
        from ai_shell.session import Session
        from tests.stubs import StubClient
        try:
            from ai_shell_gui import app as gui
        except Exception:  # pragma: no cover - pywebview absent
            self.skipTest("pywebview isn't installed")

        reply = json.dumps({
            "command": "Get-Date", "search": None, "risk": "safe",
            "explanation": "Showing the time.", "options": None,
        })
        with patch("ai_shell.session.list_apps", return_value=[]):
            session = Session()
        session.client = StubClient(reply)
        api = gui.Api.__new__(gui.Api)
        api.session = session
        api._wait_for_startup = lambda: None
        payload = api.submit("what time is it")
        with patch("ai_shell.session.list_apps", return_value=[]):
            other = Session()
        other.client = StubClient(reply)
        produced = set(other.translate("what time is it"))
        self.assertEqual(produced - set(payload), set())

    def test_a_command_with_nothing_to_say_carries_an_empty_list(self):
        import json
        from unittest.mock import patch
        from ai_shell.session import Session
        from tests.stubs import StubClient

        reply = json.dumps({
            "command": "Get-Kumquat", "search": None, "risk": "risky",
            "explanation": "Doing it.", "options": None,
        })
        with patch("ai_shell.session.list_apps", return_value=[]):
            session = Session()
        session.client = StubClient(reply)
        self.assertEqual(session.translate("do it")["does"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
