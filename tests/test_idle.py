"""ai_shell.idle - when the app should let go of the graphics card.

Every test here drives check() directly against a fake clock. Nothing waits on
a thread, because a test that sleeps to see whether a watchdog fired is a test
that fails on a slow machine.
"""

import unittest

from ai_shell import idle
from tests.stubs import forget_idle


class Policy(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.woke = 0
        self.released = 0
        self.busy = False

        idle._clock = lambda: self.now
        self.addCleanup(setattr, idle, "_clock", idle.time.monotonic)
        # This module's state outlives the test that set it, and the callbacks
        # left behind would be called by the next file's model calls.
        self.addCleanup(forget_idle)

    def wake(self):
        self.woke += 1

    def release(self):
        self.released += 1

    def pressure(self):
        return self.busy

    def watch(self, idle_seconds=300):
        idle.configure(self.wake, self.release, self.pressure, idle_seconds)

    def test_released_once_the_app_has_been_quiet_for_the_timeout(self):
        self.watch(idle_seconds=300)
        self.now += 299
        self.assertFalse(idle.check())
        self.now += 2
        self.assertTrue(idle.check())
        self.assertEqual(self.released, 1)

    def test_released_only_once(self):
        # The watchdog ends itself after a release, but check() is also called
        # directly; stopping an already stopped server would be harmless and
        # confusing in the logs.
        self.watch(idle_seconds=300)
        self.now += 400
        self.assertTrue(idle.check())
        self.assertFalse(idle.check())
        self.assertEqual(self.released, 1)

    def test_a_model_call_resets_the_clock(self):
        self.watch(idle_seconds=300)
        self.now += 200
        with idle.active():
            pass
        self.now += 200          # 400 since configure, but only 200 since the call
        self.assertFalse(idle.check())
        self.assertEqual(self.released, 0)

    def test_a_call_in_flight_is_never_released_out_from_under_itself(self):
        # A web answer can take longer than the timeout. The timestamp is only
        # written when the call ends, so the in-flight count is what protects it.
        self.watch(idle_seconds=300)
        with idle.active():
            self.now += 400
            self.assertFalse(idle.check())
        self.assertEqual(self.released, 0)

    def test_pressure_releases_before_the_timeout(self):
        self.watch(idle_seconds=300)
        self.busy = True
        self.now += idle.PRESSURE_GRACE + 1
        self.assertTrue(idle.check())
        self.assertEqual(self.released, 1)

    def test_pressure_inside_the_grace_window_waits(self):
        # A gigabyte can move because a browser opened tabs, and the user's
        # next question may be seconds away. Thirty seconds of quiet is the
        # difference between that and a game.
        self.watch(idle_seconds=300)
        self.busy = True
        self.now += idle.PRESSURE_GRACE - 1
        self.assertFalse(idle.check())

    def test_no_pressure_means_waiting_out_the_clock(self):
        self.watch(idle_seconds=300)
        self.busy = False
        self.now += 100
        self.assertFalse(idle.check())

    def test_zero_turns_the_whole_thing_off(self):
        self.watch(idle_seconds=0)
        self.busy = True
        self.now += 10000
        self.assertFalse(idle.check())
        self.assertEqual(self.released, 0)

    def test_the_next_call_wakes_it_exactly_once(self):
        self.watch(idle_seconds=300)
        self.now += 400
        idle.check()
        with idle.active():
            pass
        self.assertEqual(self.woke, 1)
        with idle.active():
            pass
        self.assertEqual(self.woke, 1)   # awake now; nothing to start

    def test_parking_from_inside_a_release_does_not_hang(self):
        # The real release is server.stop(), which calls park() on the way
        # past - on the watchdog's own thread, holding this module's lock.
        idle.configure(self.wake, idle.park, self.pressure, 300)
        self.now += 400
        self.assertTrue(idle.check())

    def test_configuring_again_ends_the_previous_watch(self):
        self.watch(idle_seconds=300)
        first = idle._watching
        self.watch(idle_seconds=300)
        self.assertTrue(first.is_set())
        self.assertIsNot(idle._watching, first)


if __name__ == "__main__":
    unittest.main()
