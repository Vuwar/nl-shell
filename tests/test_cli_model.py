"""The console's `model` command — the same picker, typed.

The CLI has no slash commands; `update` is already a bare word, and this
follows it.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from ai_shell import config, server
from ai_shell_cli import app

MACHINE = {"vram_gb": 8.0, "ram_gb": 32.0, "vram_shared": False}


class ModelCommand(unittest.TestCase):
    def test_listing_shows_numbered_models_and_marks_the_current_one(self):
        out = io.StringIO()
        with mock.patch.object(config, "HARDWARE", MACHINE), \
             mock.patch.object(config, "installed_models", return_value=set()), \
             mock.patch.object(config, "MODEL", "qwen2.5-coder-7b-q6"), \
             redirect_stdout(out):
            app._model_command("")
        printed = out.getvalue()
        self.assertIn("1.", printed)
        self.assertIn("in use", printed)
        self.assertIn("too big for your card", printed)

    def test_a_number_switches(self):
        out = io.StringIO()
        with mock.patch.object(config, "HARDWARE", MACHINE), \
             mock.patch.object(config, "installed_models", return_value=set()), \
             mock.patch.object(server, "switch_model", return_value={"ok": True}) as switched, \
             redirect_stdout(out):
            app._model_command("2")
        switched.assert_called_once()
        self.assertEqual(switched.call_args[0][0], "qwen2.5-coder-3b-q4")

    def test_a_number_out_of_range_is_refused_without_switching(self):
        out = io.StringIO()
        with mock.patch.object(config, "HARDWARE", MACHINE), \
             mock.patch.object(config, "installed_models", return_value=set()), \
             mock.patch.object(server, "switch_model") as switched, \
             redirect_stdout(out):
            app._model_command("99")
        switched.assert_not_called()
        self.assertIn("1 to 6", out.getvalue())

    def test_a_failed_switch_prints_why(self):
        out = io.StringIO()
        with mock.patch.object(config, "HARDWARE", MACHINE), \
             mock.patch.object(config, "installed_models", return_value=set()), \
             mock.patch.object(server, "switch_model",
                               return_value={"ok": False, "reason": "The download stopped."}), \
             redirect_stdout(out):
            app._model_command("2")
        self.assertIn("The download stopped.", out.getvalue())

    def test_the_one_already_running_is_not_reswitched(self):
        out = io.StringIO()
        with mock.patch.object(config, "HARDWARE", MACHINE), \
             mock.patch.object(config, "installed_models", return_value=set()), \
             mock.patch.object(config, "MODEL", "qwen2.5-coder-3b-q4"), \
             mock.patch.object(server, "switch_model") as switched, \
             redirect_stdout(out):
            app._model_command("2")
        switched.assert_not_called()
        self.assertIn("already running", out.getvalue())
