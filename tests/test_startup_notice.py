"""ai_shell.server — what the app says about the graphics card at startup.

The ordering assertion is the important one: free memory has to be sampled
before llama-server loads, or the app's own weights are counted as somebody
else's and the reading means nothing.
"""

import unittest
from unittest import mock

from ai_shell import config, models, server


class Ordering(unittest.TestCase):
    def test_free_memory_is_sampled_before_the_server_starts(self):
        events = []

        def probe():
            events.append("probe")
            return 2.6

        def start_background(argv, log):
            events.append("start")
            raise OSError("stop here — the ordering is all this test wants")

        with mock.patch.object(type(server.current), "free_vram_gb", side_effect=probe), \
             mock.patch.object(type(server.current), "start_background", side_effect=start_background), \
             mock.patch.object(server.runtime, "ensure", return_value="llama-server"), \
             mock.patch.object(server.weights, "ensure", return_value="model.gguf"), \
             mock.patch.object(config, "remember_weights"), \
             mock.patch.object(server, "_port_in_use", return_value=False):
            with self.assertRaises(server.ServerError):
                server.ensure_running()

        self.assertEqual(events, ["probe", "start"])


class Notice(unittest.TestCase):
    def tearDown(self):
        server._free_vram_at_start = None
        server._free_vram_after_load = None

    def test_an_oversized_model_is_explained(self):
        server._free_vram_at_start = 2.6
        machine = {"vram_gb": 8.0, "vram_shared": False}
        with mock.patch.object(config, "HARDWARE", machine), \
             mock.patch.object(config, "current_model",
                               return_value=models.by_id("qwen2.5-coder-7b-q6")):
            notice = server.fit_notice()
        self.assertIn("too big for your graphics card", notice)

    def test_a_merely_busy_card_is_left_to_the_measured_check(self):
        # A model that fits an idle card but not today's free memory is a
        # prediction, and one that can be wrong by a rounding error. It is the
        # session's to report, after an answer was actually slow.
        server._free_vram_at_start = 2.6
        machine = {"vram_gb": 8.0, "vram_shared": False}
        with mock.patch.object(config, "HARDWARE", machine), \
             mock.patch.object(config, "current_model",
                               return_value=models.by_id("qwen2.5-coder-7b-q4")):
            self.assertIsNone(server.fit_notice())

    def test_a_healthy_machine_is_told_nothing(self):
        server._free_vram_at_start = 7.4
        machine = {"vram_gb": 8.0, "vram_shared": False}
        with mock.patch.object(config, "HARDWARE", machine), \
             mock.patch.object(config, "current_model",
                               return_value=models.by_id("qwen2.5-coder-7b-q4")):
            self.assertIsNone(server.fit_notice())

    def test_a_machine_with_no_card_is_told_nothing(self):
        server._free_vram_at_start = None
        with mock.patch.object(config, "HARDWARE", {"vram_gb": None}), \
             mock.patch.object(config, "current_model",
                               return_value=models.by_id("qwen2.5-coder-7b-q4")):
            self.assertIsNone(server.fit_notice())


class OwnFootprint(unittest.TestCase):
    def tearDown(self):
        server._free_vram_at_start = None
        server._free_vram_after_load = None

    def test_our_own_use_is_the_difference_across_loading(self):
        server._free_vram_at_start = 5.8
        server._free_vram_after_load = 2.3
        self.assertAlmostEqual(server.our_vram_gb(), 3.5)

    def test_unknown_until_both_readings_exist(self):
        server._free_vram_at_start = 5.8
        self.assertIsNone(server.our_vram_gb())

    def test_someone_else_freeing_memory_mid_load_does_not_go_negative(self):
        server._free_vram_at_start = 2.0
        server._free_vram_after_load = 3.0
        self.assertEqual(server.our_vram_gb(), 0.0)

    def test_other_programs_exclude_our_own_model(self):
        # The bug this exists for: 8GB card, 2.2GB of desktop, and our own
        # 3.5GB of weights reported back to the user as somebody else's.
        server._free_vram_at_start = 5.8
        server._free_vram_after_load = 2.3
        with mock.patch.object(config, "HARDWARE", {"vram_gb": 8.0}):
            self.assertAlmostEqual(server.others_vram_gb(2.3), 2.2, places=6)

    def test_others_is_unknown_without_a_reading(self):
        with mock.patch.object(config, "HARDWARE", {"vram_gb": 8.0}):
            self.assertIsNone(server.others_vram_gb(None))


class Switching(unittest.TestCase):
    def test_an_unknown_model_is_refused(self):
        result = server.switch_model("not-a-model")
        self.assertFalse(result["ok"])

    def test_a_server_we_do_not_own_is_refused(self):
        with mock.patch.object(config, "MANAGED_SERVER", False):
            result = server.switch_model("qwen2.5-coder-3b-q4")
        self.assertFalse(result["ok"])
        self.assertIn("your own", result["reason"])
