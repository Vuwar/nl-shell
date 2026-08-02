"""The console's `model` command - the same picker, typed.

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
        # A 14B or 32B on an 8GB card is not "slower", it is unusable - the
        # distinction the speed grades exist to draw.
        self.assertIn("far too big for this machine", printed)

    def test_a_downloaded_model_says_so_even_where_it_will_be_slower(self):
        # Both facts, not one: an already-downloaded model is a free switch,
        # and hiding that behind "too big" made it look like a 6.3GB download.
        out = io.StringIO()
        with mock.patch.object(config, "HARDWARE", MACHINE), \
             mock.patch.object(config, "installed_models",
                               return_value={"qwen2.5-coder-7b-q6"}), \
             mock.patch.object(config, "MODEL", "qwen2.5-coder-7b-q4"), \
             redirect_stdout(out):
            app._model_command("")
        line = next(l for l in out.getvalue().splitlines() if "higher quality" in l)
        self.assertIn("downloaded", line)
        self.assertIn("slower", line)
        self.assertNotIn("GB download", line)

    def test_a_number_switches(self):
        out = io.StringIO()
        # MODEL is patched for the same reason HARDWARE is: unpatched it's
        # whatever this machine resolved to at import, and on a machine that
        # already resolved to choice 2 the command correctly declines to
        # switch to what is already running - so the test fails on that
        # machine and nowhere else. It did, on macOS arm64, where unified
        # memory puts the default somewhere different from every other
        # runner.
        with mock.patch.object(config, "HARDWARE", MACHINE), \
             mock.patch.object(config, "MODEL", "qwen2.5-coder-7b-q6"), \
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
        # MODEL patched for the reason given in test_a_number_switches.
        with mock.patch.object(config, "HARDWARE", MACHINE), \
             mock.patch.object(config, "MODEL", "qwen2.5-coder-7b-q6"), \
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
