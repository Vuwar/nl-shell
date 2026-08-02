"""Tabular output as rows, the way a directory listing is already rows.

Asked what depended on the Bluetooth service, the shell printed this:

    Status   Name                DisplayName
    ------   ----                -----------
    Running  BluetoothUserSe ... Bluetooth User Support
    Service_b251c6a
    Stopped  BluetoothUserSe ... Bluetooth User Support Service

Three faults, all from the same cause. The name is cut off mid-word and
replaced with "...", so the actual answer is missing. One row has wrapped onto
a second line, so the table no longer lines up. And the whole thing is a
single block of text with a Copy button, which is what a terminal produces
rather than what an interface should show.

PowerShell did that because it formats for an 80-column console when its
output is redirected. It isn't a rendering problem to be patched up
afterwards - the characters are gone by the time we see them - so the command
is re-run projected, exactly as ai_shell.listing already does for directory
listings: Format-Table at a width nothing reaches, then parsed back into
columns and rows off the dashes PowerShell prints under its own headers.

Re-running is only safe because nothing reaches that path unless its verb is
on a read-only list. That check is the whole safety argument here and has its
own tests below.
"""

import unittest

from ai_shell.platforms import current

WINDOWS = current.OS_NAME == "Windows"

REAL_OUTPUT = (
    "\nStatus  Name                         DisplayName                           \n"
    "------  ----                         -----------                           \n"
    "Running BluetoothUserService_b251c6a Bluetooth User Support Service_b251c6a\n"
    "Stopped BluetoothUserService         Bluetooth User Support Service        \n\n"
)


@unittest.skipUnless(WINDOWS, "the projection is PowerShell-shaped")
class WhatGetsProjected(unittest.TestCase):
    """Re-running a command is only safe for commands that only read."""

    def test_a_read_only_lookup(self):
        self.assertIsNotNone(current.project_table("Get-Service"))

    def test_a_pipeline_of_read_only_stages(self):
        projected = current.project_table(
            "Get-Service | Where-Object { $_.Status -eq 'Running' } | Sort-Object Name")
        self.assertIsNotNone(projected)

    def test_anything_that_changes_something_is_refused(self):
        # The safety property. Re-running one of these would do it twice.
        for command in ("Stop-Service -Name bthserv",
                        "Remove-Item 'x.txt'",
                        "Get-Service | Stop-Service",
                        "New-Item -ItemType Directory 'x'",
                        "Get-Content x.txt > y.txt"):
            with self.subTest(command):
                self.assertIsNone(current.project_table(command))

    def test_a_verb_nobody_vouched_for_is_refused(self):
        self.assertIsNone(current.project_table("Get-Kumquat"))

    def test_a_listing_is_left_to_the_listing_code(self):
        # Get-ChildItem already has a projection of its own that produces
        # clickable rows with real paths; a plain table would be a downgrade.
        self.assertIsNone(current.project_table("Get-ChildItem -Path C:\\"))

    def test_the_projection_asks_for_a_width_nothing_reaches(self):
        projected = current.project_table("Get-Service")
        self.assertIn("Format-Table", projected)
        self.assertIn("4096", projected)


@unittest.skipUnless(WINDOWS, "the projection is PowerShell-shaped")
class WhatComesBack(unittest.TestCase):
    """Parsed off the dashes PowerShell prints under its own headers."""

    def test_the_columns(self):
        table = current.parse_table(REAL_OUTPUT)
        self.assertEqual(table["columns"], ["Status", "Name", "DisplayName"])

    def test_the_rows(self):
        table = current.parse_table(REAL_OUTPUT)
        self.assertEqual(len(table["rows"]), 2)
        self.assertEqual(table["rows"][0][0], "Running")

    def test_nothing_is_truncated(self):
        # The actual complaint: "BluetoothUserSe ..." was the whole answer.
        table = current.parse_table(REAL_OUTPUT)
        self.assertEqual(table["rows"][0][1], "BluetoothUserService_b251c6a")

    def test_every_row_has_a_cell_per_column(self):
        table = current.parse_table(REAL_OUTPUT)
        for row in table["rows"]:
            self.assertEqual(len(row), len(table["columns"]))

    def test_output_that_is_not_a_table(self):
        for text in ("", "Running", "just a sentence\nand another",
                     "no dashes here\nat all\n"):
            with self.subTest(text):
                self.assertIsNone(current.parse_table(text))

    def test_a_table_with_no_rows(self):
        # Headers and dashes but nothing under them: a real answer ("none"),
        # not a parse failure.
        table = current.parse_table("\nName  Status\n----  ------\n\n")
        self.assertEqual(table["columns"], ["Name", "Status"])
        self.assertEqual(table["rows"], [])


class ItCanNeverRenderAsNothing(unittest.TestCase):
    """A table result carries its own text version as well.

    Found the hard way. The backend started returning {"ok": True, "table":
    ...} with no "output" key, and an interface built before tables existed
    reads result.output, finds nothing, and draws nothing at all - so a
    command that worked perfectly looked like it had silently done nothing.
    That is strictly worse than the ugly text table this feature replaced.

    The two halves of this app do not update together: a packaged copy can be
    running an older window against a newer backend, and a window that is
    already open is running the bundle it loaded at startup. So a new result
    shape has to degrade to an old one rather than depend on both sides
    agreeing.
    """

    def test_the_text_version_is_there_too(self):
        from ai_shell.listing import format_table
        table = {"columns": ["Status", "Name"], "rows": [["Running", "bthserv"]]}
        text = format_table(table)
        self.assertIn("Running", text)
        self.assertIn("bthserv", text)

    @unittest.skipUnless(WINDOWS, "needs the PowerShell projection")
    def test_a_real_result_carries_both(self):
        from unittest.mock import patch
        from ai_shell.session import Session
        from tests.stubs import StubClient

        with patch("ai_shell.session.list_apps", return_value=[]):
            session = Session()
        session.client = StubClient("{}")
        session._pending = {"command": "Get-Service -Name 'bthserv'", "hint": "check it"}
        result = session.run_last()
        self.assertIn("table", result)
        self.assertTrue(result.get("output"), "an older interface would show nothing")
        self.assertIn("bthserv", result["output"])


class ThroughTheSession(unittest.TestCase):

    @unittest.skipUnless(WINDOWS, "needs the PowerShell projection")
    def test_a_service_lookup_comes_back_as_a_table(self):
        from unittest.mock import patch
        from ai_shell.session import Session
        from tests.stubs import StubClient

        with patch("ai_shell.session.list_apps", return_value=[]):
            session = Session()
        session.client = StubClient("{}")
        session._pending = {"command": "Get-Service -Name 'bthserv'",
                            "hint": "what is the bluetooth service doing"}
        result = session.run_last()
        self.assertIn("table", result)
        self.assertIn("Status", result["table"]["columns"])

    @unittest.skipUnless(WINDOWS, "needs the PowerShell projection")
    def test_the_history_says_what_was_shown(self):
        from unittest.mock import patch
        from ai_shell.session import Session
        from tests.stubs import StubClient

        with patch("ai_shell.session.list_apps", return_value=[]):
            session = Session()
        session.client = StubClient("{}")
        session._pending = {"command": "Get-Service -Name 'bthserv'", "hint": "check it"}
        session.run_last()
        self.assertIn("table", session.history[-1]["content"].lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
