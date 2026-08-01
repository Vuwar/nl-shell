"""ai_shell.config — the model choice, and changing it without a restart.

Everything here is module state that other modules read. The tests that matter
are the ones asserting they read it *late*: a value bound at import time is a
value that keeps naming the old model after a switch.
"""

import os
import tempfile
import unittest
from unittest import mock

from ai_shell import config, models


class OversizedFlag(unittest.TestCase):
    def test_a_stored_model_too_big_for_the_card_is_flagged_not_swapped(self):
        settings = {"model": "qwen2.5-coder-7b-q6",
                    "hardware": {"ram_gb": 31.6, "vram_gb": 8.0, "vram_shared": False}}
        with mock.patch.object(config, "_read_settings", return_value=settings), \
             mock.patch.object(config, "_write_settings") as written:
            resolved, model, first_run = config._resolve()
        self.assertEqual(model.id, "qwen2.5-coder-7b-q6")   # not replaced
        written.assert_not_called()                          # settings.json untouched
        self.assertTrue(config._oversized(model, resolved))

    def test_a_fitting_stored_model_is_not_flagged(self):
        settings = {"model": "qwen2.5-coder-7b-q4",
                    "hardware": {"ram_gb": 31.6, "vram_gb": 8.0, "vram_shared": False}}
        with mock.patch.object(config, "_read_settings", return_value=settings):
            resolved, model, _ = config._resolve()
        self.assertFalse(config._oversized(model, resolved))


class SetModel(unittest.TestCase):
    def setUp(self):
        self.before = (
            config._MODEL, config.MODEL, config.MODEL_REF,
            config.MODEL_LABEL, config.GPU_LAYERS, config.SUMMARY_CAVEAT,
        )
        self.addCleanup(self._restore)

    def _restore(self):
        (config._MODEL, config.MODEL, config.MODEL_REF,
         config.MODEL_LABEL, config.GPU_LAYERS, config.SUMMARY_CAVEAT) = self.before

    def test_switching_updates_every_derived_value(self):
        with mock.patch.object(config, "_write_settings"):
            self.assertTrue(config.set_model("qwen2.5-coder-3b-q4"))
        self.assertEqual(config.MODEL, "qwen2.5-coder-3b-q4")
        self.assertIn("3B", config.MODEL_LABEL)
        self.assertEqual(config.MODEL_REF, models.by_id("qwen2.5-coder-3b-q4").ref)

    def test_the_caveat_follows_the_model(self):
        # The small-model warning applies to a 3B and not to a 7B, and the
        # interfaces read it after a switch, not before.
        with mock.patch.object(config, "_write_settings"), \
             mock.patch.object(config, "MANAGED_SERVER", True):
            config.set_model("qwen2.5-coder-3b-q4")
            self.assertIsNotNone(config.SUMMARY_CAVEAT)
            config.set_model("qwen2.5-coder-7b-q4")
            self.assertIsNone(config.SUMMARY_CAVEAT)

    def test_an_unknown_id_changes_nothing(self):
        with mock.patch.object(config, "_write_settings") as written:
            self.assertFalse(config.set_model("not-a-model"))
        written.assert_not_called()


class InstalledWeights(unittest.TestCase):
    def test_a_recorded_file_that_exists_counts_as_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "model.gguf")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("x")
            with mock.patch.object(config, "_SETTINGS", {"weights": {"qwen2.5-coder-3b-q4": path}}):
                self.assertIn("qwen2.5-coder-3b-q4", config.installed_models())

    def test_a_recorded_file_that_was_deleted_does_not(self):
        with mock.patch.object(config, "_SETTINGS", {"weights": {"qwen2.5-coder-3b-q4": "/gone.gguf"}}):
            self.assertEqual(config.installed_models(), set())


class LateReads(unittest.TestCase):
    def test_llm_reads_the_model_name_at_call_time(self):
        # llm.py used to do `from ai_shell.config import MODEL`, which is a
        # copy taken at import. After a switch it names the old model.
        import ai_shell.llm as llm

        self.assertFalse(hasattr(llm, "MODEL"),
                         "llm must read config.MODEL at call time, not bind it at import")

    def test_session_reads_the_caveat_at_call_time(self):
        import ai_shell.session as session

        self.assertFalse(hasattr(session, "SUMMARY_CAVEAT"),
                         "session must read config.SUMMARY_CAVEAT at call time")
