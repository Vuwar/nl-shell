"""ai_shell.server - letting go of the card, and taking it back on the terms
the card offers at the time.

The point of stopping the whole process rather than using llama.cpp's own
--sleep-idle-seconds is that -ngl is frozen at launch. Waking into a smaller
share of the card has to produce a smaller share of the model on it, and
test_a_wake_into_a_busier_card_puts_less_on_it is the test that says so.
"""

import contextlib
import threading
import unittest
from unittest import mock

from ai_shell import config, models, server
from tests.stubs import forget_idle


class Pressure(unittest.TestCase):
    """Whether another program has taken the card since our weights landed."""

    @contextlib.contextmanager
    def _card(self, after_load, free_now):
        with mock.patch.object(server, "_free_vram_after_load", after_load), \
             mock.patch.object(server.current, "free_vram_gb", return_value=free_now):
            yield

    def test_a_card_that_cannot_be_read_is_never_under_pressure(self):
        # nvidia-smi is the only reading available, so this is every AMD card,
        # every Intel one, and every machine without a GPU. The clock still
        # covers them; only the early release is lost.
        with self._card(after_load=3.0, free_now=None):
            self.assertFalse(server._under_pressure())

    def test_nothing_loaded_yet_is_never_under_pressure(self):
        with self._card(after_load=None, free_now=0.2):
            self.assertFalse(server._under_pressure())

    def test_a_gigabyte_taken_since_we_loaded_is_pressure(self):
        with self._card(after_load=3.0, free_now=1.5):
            self.assertTrue(server._under_pressure())

    def test_a_browser_opening_tabs_is_not(self):
        with self._card(after_load=3.0, free_now=2.5):
            self.assertFalse(server._under_pressure())


class Wiring(unittest.TestCase):
    """That a start begins a watch, and a stop ends one."""

    def setUp(self):
        def reset():
            server._process = None
            server._keepalive = None
            server._log = None

        self.addCleanup(reset)
        # test_a_wake_into_a_busier_card_puts_less_on_it runs the real
        # idle.configure, which leaves a watchdog holding callbacks that start
        # and stop a real server. Left behind, the next file's stub model call
        # goes looking for llama-server.
        self.addCleanup(forget_idle)

    @contextlib.contextmanager
    def _stubbed(self, free_vram=8.0, started=None):
        model = models.by_id("qwen2.5-coder-7b-q4")
        self.assertEqual(model.layers, 28)      # the fixture, not the code

        def start_background(argv, log):
            if started is not None:
                started.append(argv)
            return mock.Mock(**{"poll.return_value": None}), None

        with contextlib.ExitStack() as stack:
            for patch in (
                mock.patch.object(server, "_lock", threading.Lock()),
                mock.patch.object(server, "_process", None),
                mock.patch.object(server, "_port_in_use", return_value=False),
                mock.patch.object(server, "_wait_until_ready"),
                mock.patch.object(server.runtime, "ensure", return_value="/bin/llama-server"),
                mock.patch.object(server.weights, "ensure", return_value="/models/model.gguf"),
                mock.patch.object(server.config, "current_model", return_value=model),
                mock.patch.object(server.config, "installed_models", return_value=[model.id]),
                mock.patch.object(server.config, "remember_weights"),
                mock.patch.object(server.config, "MANAGED_SERVER", True),
                mock.patch.object(server.current, "free_vram_gb", return_value=free_vram),
                mock.patch.object(server.current, "start_background", start_background),
                mock.patch.object(server.os, "makedirs"),
                mock.patch("builtins.open", mock.mock_open()),
            ):
                stack.enter_context(patch)
            yield

    def test_a_start_begins_a_watch(self):
        with mock.patch.object(server.idle, "configure") as configure:
            with self._stubbed():
                server.ensure_running()
        configure.assert_called_once()
        kwargs = configure.call_args.kwargs
        self.assertIs(kwargs["wake"], server.ensure_awake)
        self.assertIs(kwargs["release"], server.stop)
        self.assertIs(kwargs["pressure"], server._under_pressure)
        self.assertEqual(kwargs["idle_seconds"], config.IDLE_UNLOAD_MINUTES * 60)

    def test_a_server_that_is_not_ours_is_never_watched(self):
        with mock.patch.object(server.idle, "configure") as configure, \
             mock.patch.object(server.config, "MANAGED_SERVER", False):
            self.assertFalse(server.ensure_running())
        configure.assert_not_called()

    def test_stopping_ends_the_watch(self):
        with mock.patch.object(server.idle, "park") as park:
            server.stop()
        park.assert_called_once()

    def test_a_wake_into_a_busier_card_puts_less_on_it(self):
        # The whole reason this design restarts the process instead of using
        # llama.cpp's --sleep-idle-seconds: that flag reloads with the -ngl it
        # was started with, and the card the user alt-tabbed away from is not
        # the card they are coming back to.
        started = []
        with self._stubbed(free_vram=8.0, started=started):
            server.ensure_running()
        server.stop()
        with self._stubbed(free_vram=3.0, started=started):
            server.ensure_running()

        self.assertEqual(len(started), 2)
        roomy = started[0][started[0].index("-ngl") + 1]
        busy = started[1][started[1].index("-ngl") + 1]
        # -1 is llama.cpp's "all of them"; 10 is what fit.gpu_layers gives a
        # 7B-Q4 with 3GB free. Both come from ai_shell.fit, not from here.
        self.assertEqual(roomy, "-1")
        self.assertEqual(busy, "10")
        self.assertLess(int(busy), 28)


if __name__ == "__main__":
    unittest.main()
