"""ai_shell.corrections — what gets written when the user fixes a command,
and what gets scrubbed out of it on the way."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ai_shell import corrections


class Redaction(unittest.TestCase):
    def test_flag_value_is_removed(self):
        self.assertEqual(
            corrections.redact("mysql --password hunter2 -e 'select 1'"),
            "mysql --password [redacted] -e 'select 1'",
        )

    def test_powershell_style_flag_is_removed(self):
        self.assertEqual(
            corrections.redact("Invoke-Rest -Token abc123def456 -Uri x"),
            "Invoke-Rest -Token [redacted] -Uri x",
        )

    def test_equals_form_is_removed(self):
        self.assertEqual(
            corrections.redact("curl --api-key=sk-live-9f8e7d6c5b4a3210"),
            "curl --api-key=[redacted]",
        )

    def test_connection_string_password_is_removed(self):
        self.assertEqual(
            corrections.redact("psql 'host=db user=me password=s3cr3t sslmode=require'"),
            "psql 'host=db user=me password=[redacted] sslmode=require'",
        )

    def test_bearer_token_is_removed(self):
        self.assertEqual(
            corrections.redact("curl -H 'Authorization: Bearer eyJhbGci0iJIUzI1N'"),
            "curl -H 'Authorization: Bearer [redacted]'",
        )

    def test_long_hex_is_removed(self):
        self.assertEqual(
            corrections.redact("git checkout 9f8e7d6c5b4a32109f8e7d6c5b4a32109f8e7d6c"),
            "git checkout [redacted]",
        )

    def test_token_shaped_run_is_removed(self):
        self.assertEqual(
            corrections.redact("gh auth login --with-token ghp1A2b3C4d5E6f7G8h9I0j1K2l3M4n5O6p7"),
            "gh auth login --with-token [redacted]",
        )

    # The one that matters most: the dataset is worthless if ordinary paths
    # get scrubbed, and a Windows path is a long run of exactly the characters
    # a naive token pattern looks for.
    def test_windows_path_survives(self):
        command = r"Remove-Item 'C:\Users\vuqar\Downloads\quarterly_report_2026.pdf'"
        self.assertEqual(corrections.redact(command), command)

    def test_posix_path_survives(self):
        command = "rm -rf /home/vuqar/projects/nl-shell/build/artifacts"
        self.assertEqual(corrections.redact(command), command)

    def test_ordinary_command_survives(self):
        command = "Get-ChildItem ~/Desktop -Recurse | Sort-Object Length"
        self.assertEqual(corrections.redact(command), command)


class Recording(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "corrections.jsonl")
        self.addCleanup(self._dir.cleanup)

    def _read(self):
        with open(self.path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_a_correction_is_written(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", True):
            corrections.record("delete the logs", "Remove-Item a.log", "Remove-Item b.log")
        rows = self._read()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request"], "delete the logs")
        self.assertEqual(rows[0]["suggested"], "Remove-Item a.log")
        self.assertEqual(rows[0]["corrected"], "Remove-Item b.log")
        self.assertIn("at", rows[0])
        self.assertIn("model", rows[0])
        self.assertIn("os", rows[0])

    def test_an_unchanged_command_is_not_a_correction(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", True):
            corrections.record("x", "Remove-Item a.log", "Remove-Item a.log")
        self.assertFalse(os.path.exists(self.path))

    def test_records_append(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", True):
            corrections.record("one", "a", "b")
            corrections.record("two", "c", "d")
        self.assertEqual([row["request"] for row in self._read()], ["one", "two"])

    def test_secrets_are_scrubbed_before_writing(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", True):
            corrections.record(
                "log in",
                "mysql --password hunter2",
                "mysql --password hunter3 -h db",
            )
        row = self._read()[0]
        self.assertNotIn("hunter2", row["suggested"])
        self.assertNotIn("hunter3", row["corrected"])
        self.assertIn("[redacted]", row["corrected"])

    def test_disabled_writes_nothing(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", False):
            corrections.record("x", "a", "b")
        self.assertFalse(os.path.exists(self.path))

    def test_an_unwritable_location_is_not_an_error(self):
        # A directory where the file should be: opening it for append raises,
        # and running a command must not fail because of it.
        blocked = os.path.join(self._dir.name, "blocked")
        os.makedirs(blocked)
        with patch.object(corrections, "PATH", blocked), \
             patch.object(corrections, "ENABLED", True):
            corrections.record("x", "a", "b")  # must not raise


if __name__ == "__main__":
    unittest.main()
