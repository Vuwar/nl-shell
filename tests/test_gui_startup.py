"""ai_shell_gui.Api - starting the model server, and starting it again.

The window opens before the server is up, so every failure here happens on a
thread nobody is waiting on. What matters is that the failure is recoverable
without closing the window, and that a request typed during a retry waits for
that retry rather than being answered against a server that isn't listening.
"""

import socket
import threading
import unittest
from unittest import mock

try:
    from ai_shell_gui import app as gui
except Exception:  # pragma: no cover - pywebview absent from this environment
    gui = None


@unittest.skipIf(gui is None, "pywebview isn't installed")
class Startup(unittest.TestCase):
    def make(self, *outcomes, gate=None):
        """An Api whose server start produces `outcomes` in order.

        An outcome is None for success, or an exception to raise. `gate` holds
        every start after the first until it is set, which is how a test keeps
        a retry in progress for as long as it needs to look at something.

        The patch outlives this call rather than being scoped to it: a retry
        starts a second thread, and one that reached the real ensure_running
        would go looking for a llama-server.
        """
        calls = []

        def ensure_running(on_status=None):
            outcome = outcomes[min(len(calls), len(outcomes) - 1)]
            calls.append(outcome)
            if gate is not None and len(calls) > 1:
                gate.wait(timeout=5)
            if outcome is not None:
                raise outcome

        self.calls = calls
        for patch in (mock.patch.object(gui.server, "ensure_running", ensure_running),
                      mock.patch.object(gui.updater, "Updater")):
            patch.start()
            self.addCleanup(patch.stop)

        api = gui.Api()
        api._settled.wait(timeout=5)
        return api

    def test_a_failed_start_is_reported_and_can_be_retried(self):
        api = self.make(gui.server.ServerError("no weights"), None)
        self.assertEqual(api.startup_status()["state"], "failed")

        self.assertEqual(api.retry_startup(), {"ok": True})
        api._settled.wait(timeout=5)
        self.assertEqual(api.startup_status()["state"], "ready")
        self.assertEqual(len(self.calls), 2)

    def test_retrying_a_start_that_didnt_fail_does_nothing(self):
        api = self.make(None)
        self.assertEqual(api.retry_startup(), {"ok": False})
        self.assertEqual(len(self.calls), 1)

    def test_a_retry_landing_between_the_wait_and_the_read_is_not_missed(self):
        """The interleaving _wait_for_startup loops for.

        submit() waits on _settled and then reads the status - two steps. A
        retry between them clears the event and sets the state back to
        "starting", so a single wait would find no failure, conclude all was
        well, and translate against a server that isn't up. Forced here by
        firing the retry from inside the wait, because it is a real ordering
        and too narrow to hit by chance.
        """
        gate = threading.Event()
        api = self.make(gui.server.ServerError("first attempt"), None, gate=gate)
        states = []

        def translate(_text):
            states.append(api.startup_status()["state"])
            return {"command": "echo hi"}

        real_wait = api._settled.wait
        fired = []

        def wait_then_retry(timeout=None):
            result = real_wait(timeout)
            if not fired:
                fired.append(True)
                api.retry_startup()
            return result

        api._settled.wait = wait_then_retry

        with mock.patch.object(api.session, "translate", translate):
            answers = []
            waiter = threading.Thread(target=lambda: answers.append(api.submit("hi")))
            waiter.start()
            # The retry is still inside ensure_running, so submit must not
            # have answered - with the stale failure or with anything else.
            waiter.join(timeout=0.3)
            self.assertTrue(waiter.is_alive(), "submit answered during a retry")
            gate.set()
            waiter.join(timeout=5)

        self.assertEqual(answers[0]["command"], "echo hi")
        self.assertEqual(states, ["ready"])


@unittest.skipIf(gui is None, "pywebview isn't installed")
class FrontEndPort(unittest.TestCase):
    """Which port the built front end is served on.

    pywebview serves it over HTTP, and with private_mode off - which this app
    needs, because the settings screen keeps its choices in localStorage - it
    falls back to one fixed port for every application on the machine. Two
    copies of this app then share it, and the second one's window quietly
    renders the first one's front end.
    """

    def test_the_chosen_port_is_actually_free(self):
        port = gui._free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))  # must not raise

    def test_the_window_is_not_left_on_pywebviews_shared_default(self):
        started = {}
        # HTML_PATH is pointed at a file that certainly exists, because main()
        # refuses to open a window when the front end hasn't been built - and
        # the front end is a build product that CI produces *after* running the
        # tests. Nothing here looks at the file; create_window is a mock.
        with mock.patch.object(gui, "HTML_PATH", __file__), \
             mock.patch.object(gui.webview, "create_window"), \
             mock.patch.object(gui.webview, "start", lambda **kw: started.update(kw)), \
             mock.patch.object(gui.webview, "screens", [mock.Mock(width=1920, height=1080)]), \
             mock.patch.object(gui, "Api"):
            gui.main()

        self.assertIn("http_port", started)
        self.assertNotEqual(started["http_port"], 42001)
        # The reason the default applies at all, so this test fails loudly if
        # somebody "fixes" the collision by turning private mode back on and
        # silently wiping the settings screen's storage instead.
        self.assertIs(started["private_mode"], False)


if __name__ == "__main__":
    unittest.main()
