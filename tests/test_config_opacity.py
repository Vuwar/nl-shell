"""ai_shell.config - the window opacity setting.

A number the user drags a slider to, which means it arrives as whatever the
front end felt like sending and has to survive a hand-edited settings.json.
The tests here are mostly about what happens to values nobody should have
sent: the window has to open at *some* opacity regardless.
"""

import unittest
from unittest import mock

from ai_shell import config


class Clamping(unittest.TestCase):
    def test_a_value_in_range_is_kept(self):
        self.assertEqual(config._clamp_opacity(55), 55)

    def test_below_the_floor_comes_back_at_the_floor(self):
        # The floor exists so that a slider dragged to the end still leaves a
        # window the user can find on their desktop.
        self.assertEqual(config._clamp_opacity(4), config.MIN_OPACITY)

    def test_above_a_hundred_comes_back_at_a_hundred(self):
        self.assertEqual(config._clamp_opacity(400), 100)

    def test_a_fractional_value_is_rounded_to_a_whole_percent(self):
        self.assertEqual(config._clamp_opacity(72.6), 73)

    def test_nonsense_falls_back_to_the_default(self):
        # A hand-mangled settings.json is the same situation as no setting at
        # all, which is how _read_settings already treats an unreadable file.
        self.assertEqual(config._clamp_opacity("very see-through"), config.DEFAULT_OPACITY)

    def test_nothing_stored_falls_back_to_the_default(self):
        self.assertEqual(config._clamp_opacity(None), config.DEFAULT_OPACITY)


class Resolution(unittest.TestCase):
    def test_the_stored_setting_is_used_when_there_is_no_override(self):
        self.assertEqual(config._opacity_setting({}, {"opacity": 40}), 40)

    def test_the_environment_wins_over_the_stored_setting(self):
        self.assertEqual(
            config._opacity_setting({"AI_SHELL_OPACITY": "55"}, {"opacity": 40}), 55)

    def test_an_empty_override_is_not_an_override(self):
        self.assertEqual(
            config._opacity_setting({"AI_SHELL_OPACITY": ""}, {"opacity": 40}), 40)

    def test_neither_source_gives_the_default(self):
        self.assertEqual(config._opacity_setting({}, {}), config.DEFAULT_OPACITY)


class SetOpacity(unittest.TestCase):
    def setUp(self):
        before = config.OPACITY
        self.addCleanup(lambda: setattr(config, "OPACITY", before))

    def test_setting_updates_the_global_and_persists(self):
        with mock.patch.object(config, "_write_settings") as written:
            self.assertEqual(config.set_opacity(45), 45)
        self.assertEqual(config.OPACITY, 45)
        self.assertEqual(written.call_args[0][0]["opacity"], 45)

    def test_an_out_of_range_value_persists_as_the_clamped_one(self):
        # What the window is showing and what the file records have to be the
        # same number, or the next launch moves on its own.
        with mock.patch.object(config, "_write_settings") as written:
            self.assertEqual(config.set_opacity(500), 100)
        self.assertEqual(config.OPACITY, 100)
        self.assertEqual(written.call_args[0][0]["opacity"], 100)


if __name__ == "__main__":
    unittest.main()
