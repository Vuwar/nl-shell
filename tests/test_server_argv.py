"""ai_shell.server - what llama-server is actually told to do.

The command line is the whole contract with the inference engine, and it is
the one part of starting a server that can be checked without starting one.
"""

import contextlib
import threading
import unittest
from unittest import mock

from ai_shell import config, models, server


class Argv(unittest.TestCase):
    def test_the_layer_count_is_decided_per_start(self):
        # What else is on the card changes between launches, so this is not a
        # setting worked out once at install time.
        argv = server._argv("/bin/llama-server", "/models/model.gguf", 24)
        self.assertEqual(argv[argv.index("-ngl") + 1], "24")

    def test_without_a_free_reading_it_falls_back_to_the_configured_answer(self):
        with mock.patch.object(server, "_free_vram_at_start", None):
            self.assertEqual(server._gpu_layers(), config.GPU_LAYERS)

    def test_one_slot_not_four(self):
        # Left to itself this build opens four slots and gives each the full
        # context, so -c 8192 becomes four caches of 8192 - about 1.8GB of a
        # 7B's graphics memory held for three conversations nobody is having,
        # taken out of the budget the weights need.
        argv = server._argv("/bin/llama-server", "/models/model.gguf")
        self.assertEqual(argv[argv.index("-np") + 1], "1")

    def test_the_model_is_a_path_not_a_repo_reference(self):
        argv = server._argv("/bin/llama-server", "/models/model-q6_k.gguf")
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "/models/model-q6_k.gguf")
        # -hf would make llama.cpp fetch the weights itself, which is the
        # download this app took over precisely because it can't be resumed.
        self.assertNotIn("-hf", argv)

    def test_the_rest_of_the_flags_are_unchanged(self):
        argv = server._argv("/bin/llama-server", "/models/model.gguf")
        self.assertEqual(argv[0], "/bin/llama-server")
        self.assertEqual(argv[argv.index("--host") + 1], config.HOST)
        self.assertEqual(argv[argv.index("--port") + 1], str(config.PORT))
        self.assertEqual(argv[argv.index("-c") + 1], str(config.CONTEXT_SIZE))
        self.assertEqual(argv[argv.index("-ngl") + 1], str(config.GPU_LAYERS))
        self.assertIn("--jinja", argv)


class ProgressDecoration(unittest.TestCase):
    """What ai_shell.weights cannot know about its own download: how many
    layers the model has, how many of them fit on the card, and whether this
    installation has any weights at all yet.

    Starting a real server is out of the question here, so everything that
    touches the disk, the card or a process is stubbed and what is left is
    the bookkeeping this adds.
    """

    def setUp(self):
        # ensure_running writes module globals. Left set, the next test finds
        # a "running" server and returns before doing anything.
        def reset():
            server._process = None
            server._keepalive = None
            server._log = None

        self.addCleanup(reset)

    @contextlib.contextmanager
    def _stubbed(self, weights_ensure=None, installed=(), gpu_layers=19):
        model = models.by_id("qwen2.5-coder-7b-q4")
        self.assertEqual(model.layers, 28)   # the fixture, not the code

        def ensure(ref, label, on_status=None, on_progress=None):
            if weights_ensure:
                weights_ensure(on_progress)
            return "/models/model.gguf"

        with contextlib.ExitStack() as stack:
            for patch in (
                mock.patch.object(server, "_lock", threading.Lock()),
                mock.patch.object(server, "_process", None),
                mock.patch.object(server, "_port_in_use", return_value=False),
                mock.patch.object(server, "_gpu_layers", return_value=gpu_layers),
                mock.patch.object(server, "_wait_until_ready"),
                mock.patch.object(server.runtime, "ensure", return_value="/bin/llama-server"),
                mock.patch.object(server.weights, "ensure", ensure),
                mock.patch.object(server.config, "current_model", return_value=model),
                mock.patch.object(server.config, "installed_models", return_value=list(installed)),
                mock.patch.object(server.config, "remember_weights"),
                mock.patch.object(server.config, "MANAGED_SERVER", True),
                mock.patch.object(server.current, "free_vram_gb", return_value=8.0),
                mock.patch.object(
                    server.current, "start_background",
                    return_value=(mock.Mock(**{"poll.return_value": None}), None),
                ),
                mock.patch.object(server.os, "makedirs"),
                mock.patch("builtins.open", mock.mock_open()),
                mock.patch("atexit.register"),
            ):
                stack.enter_context(patch)
            yield

    def test_payloads_gain_layers_and_first_install(self):
        seen = []
        sent = lambda emit: emit({"phase": "downloading", "label": "Test", "percent": 5})
        with self._stubbed(weights_ensure=sent, installed=[]):
            server.ensure_running(on_progress=seen.append)

        downloading = [p for p in seen if p["phase"] == "downloading"]
        self.assertEqual(len(downloading), 1)
        self.assertEqual(downloading[0]["layers"], 28)
        self.assertTrue(downloading[0]["first_install"])
        # Untouched on the way past, so a field added in weights.py later
        # needs no change here.
        self.assertEqual(downloading[0]["percent"], 5)

    def test_a_loading_payload_says_what_goes_on_the_card(self):
        seen = []
        sent = lambda emit: emit({"phase": "downloading", "label": "Test", "percent": 5})
        with self._stubbed(weights_ensure=sent, gpu_layers=19):
            server.ensure_running(on_progress=seen.append)

        loading = [p for p in seen if p["phase"] == "loading"]
        self.assertEqual(len(loading), 1)
        self.assertEqual(loading[0]["gpu_layers"], 19)
        self.assertEqual(loading[0]["layers"], 28)

    def test_all_on_the_card_is_reported_as_a_count(self):
        # -1 is llama.cpp's argument for "all of them", not a number of
        # layers. Passed through, it said "-1 of 28 layers on your graphics
        # card" and left every brick cool, because no index is below -1.
        seen = []
        sent = lambda emit: emit({"phase": "downloading", "label": "Test", "percent": 5})
        with self._stubbed(weights_ensure=sent, gpu_layers=-1):
            server.ensure_running(on_progress=seen.append)
        loading = [p for p in seen if p["phase"] == "loading"][0]
        self.assertEqual(loading["gpu_layers"], 28)

    def test_none_on_the_card_is_reported_as_zero(self):
        seen = []
        sent = lambda emit: emit({"phase": "downloading", "label": "Test", "percent": 5})
        with self._stubbed(weights_ensure=sent, gpu_layers=0):
            server.ensure_running(on_progress=seen.append)
        loading = [p for p in seen if p["phase"] == "loading"][0]
        self.assertEqual(loading["gpu_layers"], 0)

    def test_a_start_with_nothing_to_download_says_nothing(self):
        # Loading is the end of an install, not an event of its own. Emitting
        # it on every start puts a progress ring around the folded tile of an
        # app that is merely opening, which is what shipped once already.
        seen = []
        with self._stubbed(installed=["qwen2.5-coder-7b-q4"]):
            server.ensure_running(on_progress=seen.append)
        self.assertEqual(seen, [])

    def test_first_install_is_false_when_something_is_already_here(self):
        seen = []
        sent = lambda emit: emit({"phase": "downloading", "label": "Test", "percent": 5})
        with self._stubbed(weights_ensure=sent, installed=["qwen2.5-coder-3b-q4"]):
            server.ensure_running(on_progress=seen.append)
        self.assertFalse(seen[0]["first_install"])

    def test_no_on_progress_starts_the_server_as_before(self):
        with self._stubbed():
            self.assertTrue(server.ensure_running())


if __name__ == "__main__":
    unittest.main()
