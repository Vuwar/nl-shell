"""Session.run_last with a command the user edited - what runs, and what gets
recorded."""

import json
import unittest
from unittest.mock import patch

from ai_shell.session import Session
from tests.stubs import StubClient


def _reply(command, risk="risky"):
    return json.dumps({
        "command": command, "search": None, "risk": risk,
        "explanation": "does a thing", "options": None,
    })


class _Ran:
    """Stands in for subprocess.CompletedProcess."""

    def __init__(self):
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""


class EditedCommands(unittest.TestCase):
    def setUp(self):
        # The app scan runs on a thread and shells out; nothing here needs it.
        patcher = patch("ai_shell.session.list_apps", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _session(self, command):
        session = Session()
        session.client = StubClient(_reply(command))
        session.translate("delete the logs")
        return session

    def test_the_edited_command_is_what_runs(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record"):
            run.return_value = [("Remove-Item b.log", _Ran())]
            session.run_last("Remove-Item b.log")
        self.assertEqual(run.call_args[0][0], "Remove-Item b.log")

    def test_no_argument_runs_the_models_command(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run:
            run.return_value = [("Remove-Item a.log", _Ran())]
            session.run_last()
        self.assertEqual(run.call_args[0][0], "Remove-Item a.log")

    def test_an_edit_is_recorded(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record") as record:
            run.return_value = [("Remove-Item b.log", _Ran())]
            session.run_last("Remove-Item b.log")
        record.assert_called_once_with(
            "delete the logs", "Remove-Item a.log", "Remove-Item b.log"
        )

    def test_an_unchanged_command_records_nothing(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record") as record:
            run.return_value = [("Remove-Item a.log", _Ran())]
            session.run_last("Remove-Item a.log")
        record.assert_not_called()

    def test_no_argument_records_nothing(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record") as record:
            run.return_value = [("Remove-Item a.log", _Ran())]
            session.run_last()
        record.assert_not_called()

    def test_the_edited_command_still_resolves_listed_paths(self):
        # The user types a name they can see in the listing; it has to reach
        # the folder they are looking at, not the process working directory.
        session = self._session("Remove-Item wrong.txt")
        session._last_listing = [
            {"name": "report.pdf", "path": r"C:\Users\x\Desktop\report.pdf",
             "dir": False, "size": 1, "modified": None},
        ]
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record"):
            run.return_value = [("x", _Ran())]
            session.run_last("Remove-Item report.pdf")
        self.assertIn("Desktop", run.call_args[0][0])

    def test_the_recorded_text_is_what_the_user_typed(self):
        # Raw against raw: the model's command is recorded before resolution
        # too, so the pair compares like with like.
        session = self._session("Remove-Item wrong.txt")
        session._last_listing = [
            {"name": "report.pdf", "path": r"C:\Users\x\Desktop\report.pdf",
             "dir": False, "size": 1, "modified": None},
        ]
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record") as record:
            run.return_value = [("x", _Ran())]
            session.run_last("Remove-Item report.pdf")
        self.assertEqual(record.call_args[0][2], "Remove-Item report.pdf")

    def test_borrowed_runs_are_unaffected(self):
        # A click elsewhere in the window must not consume the pending command.
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record"):
            run.return_value = [("open x", _Ran())]
            session._run_borrowed("open x", "open x")
        self.assertEqual(session._pending["command"], "Remove-Item a.log")


if __name__ == "__main__":
    unittest.main()
