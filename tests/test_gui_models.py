"""The window's model picker, on the Python side.

Switching stops a running server, so the guards are the substance here: not
while it is still starting, and not out from under a risky command the user
hasn't answered yet.
"""

import unittest
from unittest import mock

from ai_shell import config, server
from ai_shell_gui.app import Api


def _api():
    with mock.patch.object(Api, "_start_server"), \
         mock.patch("ai_shell_gui.app.updater.Updater"), \
         mock.patch("ai_shell.session.Session._scan_apps", return_value=[]):
        api = Api()
    api._settled.set()
    api._startup = {"state": "ready", "message": ""}
    return api


class Listing(unittest.TestCase):
    def test_every_model_is_listed_with_what_fits(self):
        api = _api()
        with mock.patch.object(config, "HARDWARE", {"vram_gb": 8.0, "ram_gb": 32.0, "vram_shared": False}), \
             mock.patch.object(config, "installed_models", return_value=set()):
            listed = api.list_models()
        self.assertTrue(listed["ok"])
        rows = {row["id"]: row for row in listed["models"]}
        self.assertFalse(rows["qwen2.5-coder-7b-q6"]["fits"])
        self.assertTrue(rows["qwen2.5-coder-7b-q4"]["fits"])

    def test_a_server_the_user_started_is_read_only(self):
        api = _api()
        with mock.patch.object(config, "MANAGED_SERVER", False), \
             mock.patch.object(config, "installed_models", return_value=set()):
            listed = api.list_models()
        self.assertFalse(listed["editable"])


class Switching(unittest.TestCase):
    def test_switching_while_still_starting_is_refused(self):
        api = _api()
        api._startup = {"state": "starting", "message": "Downloading…"}
        result = api.switch_model("qwen2.5-coder-3b-q4")
        self.assertFalse(result["ok"])

    def test_switching_with_a_command_awaiting_confirmation_is_refused(self):
        api = _api()
        api.session._pending = {"command": "Remove-Item x", "hint": "delete x"}
        result = api.switch_model("qwen2.5-coder-3b-q4")
        self.assertFalse(result["ok"])
        self.assertIn("waiting", result["reason"])

    def test_a_clean_switch_hands_off_to_the_server(self):
        api = _api()
        done = []
        with mock.patch.object(server, "switch_model", return_value={"ok": True}) as switched:
            result = api.switch_model("qwen2.5-coder-3b-q4")
            api._settled.wait(timeout=5)
            done.append(api.startup_status()["state"])
        self.assertTrue(result["ok"])
        switched.assert_called_once()
        self.assertEqual(switched.call_args[0][0], "qwen2.5-coder-3b-q4")


class StartupNotice(unittest.TestCase):
    def test_the_notice_arrives_with_ready_not_during_the_wait(self):
        api = _api()
        api._startup = {"state": "starting", "message": "Starting the model…"}
        with mock.patch.object(server, "fit_notice", return_value="card is full"):
            self.assertIsNone(api.startup_status()["notice"])
            api._startup = {"state": "ready", "message": ""}
            self.assertEqual(api.startup_status()["notice"], "card is full")
