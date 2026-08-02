"""Where the app notices it is being used, and what it says when waking fails."""

import unittest
from unittest import mock

from ai_shell import idle, llm, server
from ai_shell.session import Session
from tests.stubs import forget_idle


class EveryCallCountsAsActivity(unittest.TestCase):
    def setUp(self):
        self.addCleanup(forget_idle)

    def test_a_completion_runs_inside_idle_active(self):
        # _complete is the single point every model call in this app passes
        # through, which is the only reason one wrap covers all four callers.
        inside = []

        client = mock.Mock()
        client.chat.completions.create.side_effect = (
            lambda **kwargs: inside.append(idle._in_flight)
        )

        llm._complete(client, [{"role": "user", "content": "hi"}], 10)

        self.assertEqual(inside, [1])
        self.assertEqual(idle._in_flight, 0)


class AFailedWakeIsAnAnswer(unittest.TestCase):
    def test_translate_reports_it_instead_of_raising(self):
        # Before idle unloading this could only mean something was broken, so
        # it was left to propagate. It is now an ordinary start-of-turn event,
        # and both interfaces already know how to draw a sentence.
        with mock.patch.object(Session, "_scan_apps", return_value=[]):
            session = Session()

        with mock.patch("ai_shell.session.ask_model",
                        side_effect=server.ServerError("no weights here")):
            data = session.translate("zip the desktop folder")

        self.assertIsNone(data["command"])
        self.assertIsNone(data["search"])
        self.assertIn("no weights here", data["explanation"])
        self.assertTrue(data["error"])
        # Nothing was translated, so nothing may be left waiting to be run.
        self.assertIsNone(session._pending)


if __name__ == "__main__":
    unittest.main()
