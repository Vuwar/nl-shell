"""The payload the install screen is drawn from.

The front end polls one method. Everything it needs has to survive in what
that method returns, including after the failure that is the moment it most
needs something to show.
"""

import unittest
from unittest import mock

try:
    from ai_shell_gui.app import Api
except Exception:  # pragma: no cover - pywebview absent from this environment
    Api = None


def _api():
    with mock.patch.object(Api, "_start_server"), \
         mock.patch("ai_shell_gui.app.updater.Updater"), \
         mock.patch("ai_shell.session.Session._scan_apps", return_value=[]):
        return Api()


@unittest.skipIf(Api is None, "pywebview isn't installed")
class StartupProgress(unittest.TestCase):
    def test_progress_is_none_before_anything_starts(self):
        api = _api()
        self.assertIsNone(api.startup_status()["progress"])

    def test_a_payload_is_handed_through_untouched(self):
        api = _api()
        payload = {"phase": "downloading", "percent": 47, "layers": 28}
        api._set_progress(payload)
        self.assertEqual(api.startup_status()["progress"], payload)

    def test_the_message_is_unchanged_by_any_of_this(self):
        api = _api()
        api._set_startup("starting", "Downloading Test Model - 47%")
        self.assertEqual(
            api.startup_status()["message"], "Downloading Test Model - 47%"
        )

    def test_a_failure_keeps_the_last_payload_and_marks_it(self):
        api = _api()
        api._set_progress({"phase": "downloading", "percent": 47, "layers": 28})
        api._set_startup("failed", "The connection went away.")
        status = api.startup_status()
        self.assertEqual(status["progress"]["phase"], "failed")
        self.assertEqual(status["progress"]["percent"], 47)

    def test_ready_clears_it(self):
        api = _api()
        api._set_progress({"phase": "loading", "gpu_layers": 19, "layers": 28})
        with mock.patch("ai_shell_gui.app.server.fit_notice", return_value=None):
            api._set_startup("ready", "")
            self.assertIsNone(api.startup_status()["progress"])

    def test_a_retry_starts_from_a_clean_slate(self):
        api = _api()
        api._set_progress({"phase": "downloading", "percent": 47, "layers": 28})
        api._set_startup("failed", "The connection went away.")
        with mock.patch.object(api, "_start_server"):
            self.assertTrue(api.retry_startup()["ok"])
        self.assertIsNone(api.startup_status()["progress"])


if __name__ == "__main__":
    unittest.main()
