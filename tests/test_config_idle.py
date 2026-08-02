"""ai_shell.config - how long the app waits before giving the card back."""

import unittest

from ai_shell import config


class IdleUnload(unittest.TestCase):
    def read(self, environ=None, settings=None):
        return config._idle_unload_minutes(environ or {}, settings or {})

    def test_the_default_when_nothing_is_configured(self):
        self.assertEqual(self.read(), config.DEFAULT_IDLE_UNLOAD_MINUTES)

    def test_settings_are_used(self):
        self.assertEqual(self.read(settings={"idle_unload_minutes": 20}), 20.0)

    def test_the_environment_wins(self):
        self.assertEqual(
            self.read({"AI_SHELL_IDLE_UNLOAD": "1"}, {"idle_unload_minutes": 20}),
            1.0,
        )

    def test_zero_survives(self):
        # Zero is the off switch, so it must not be read as "nothing set here"
        # and quietly replaced by the default.
        self.assertEqual(self.read(settings={"idle_unload_minutes": 0}), 0.0)
        self.assertEqual(self.read({"AI_SHELL_IDLE_UNLOAD": "0"}), 0.0)

    def test_nonsense_falls_back_rather_than_refusing_to_start(self):
        # This reads a file the user is free to edit by hand.
        self.assertEqual(
            self.read(settings={"idle_unload_minutes": "soon"}),
            config.DEFAULT_IDLE_UNLOAD_MINUTES,
        )

    def test_a_negative_is_off_not_a_negative_timeout(self):
        self.assertEqual(self.read({"AI_SHELL_IDLE_UNLOAD": "-5"}), 0.0)

    def test_the_module_settled_on_a_number(self):
        self.assertIsInstance(config.IDLE_UNLOAD_MINUTES, float)


if __name__ == "__main__":
    unittest.main()
