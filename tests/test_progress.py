"""ai_shell.progress - turning byte counts into a rate somebody can read.

The numbers here are shown to a user for minutes at a time, so the two
failures that matter are a rate computed from one chunk (which swings by
hours) and a resumed download reporting that two gigabytes arrived in forty
milliseconds.
"""

import unittest

from ai_shell.progress import Smoother


class Smoothing(unittest.TestCase):
    def test_nothing_is_reported_before_the_minimum_window(self):
        smoother = Smoother()
        smoother.sample(0, 100.0)
        smoother.sample(1_000_000, 100.5)
        self.assertIsNone(smoother.rate)
        self.assertIsNone(smoother.eta_for(10_000_000))

    def test_a_steady_transfer_reports_its_rate(self):
        smoother = Smoother()
        for step in range(11):
            smoother.sample(step * 1_000_000, 100.0 + step * 0.5)
        # 1MB every half second is 2MB/s, within the tolerance the weighting
        # leaves on a series this short.
        self.assertAlmostEqual(smoother.rate, 2_000_000, delta=200_000)

    def test_eta_is_whats_left_over_the_rate(self):
        smoother = Smoother()
        for step in range(11):
            smoother.sample(step * 1_000_000, 100.0 + step * 0.5)
        # 10MB done of 30MB at 2MB/s is 10 seconds.
        self.assertAlmostEqual(smoother.eta_for(30_000_000), 10, delta=2)

    def test_a_resumed_transfer_does_not_report_an_absurd_rate(self):
        # Two gigabytes were already on disk when this started. They did not
        # arrive in the first sample.
        smoother = Smoother(started_at=2_000_000_000)
        smoother.sample(2_000_000_000, 100.0)
        for step in range(1, 11):
            smoother.sample(2_000_000_000 + step * 1_000_000, 100.0 + step * 0.5)
        self.assertAlmostEqual(smoother.rate, 2_000_000, delta=200_000)

    def test_a_stalled_transfer_reports_no_eta(self):
        smoother = Smoother()
        for step in range(11):
            smoother.sample(1_000_000, 100.0 + step * 0.5)
        self.assertIsNone(smoother.eta_for(10_000_000))

    def test_repeated_timestamps_do_not_divide_by_zero(self):
        smoother = Smoother()
        for _ in range(11):
            smoother.sample(1_000_000, 100.0)
        self.assertIsNone(smoother.rate)

    def test_an_empty_total_has_no_eta(self):
        smoother = Smoother()
        for step in range(11):
            smoother.sample(step * 1_000_000, 100.0 + step * 0.5)
        self.assertIsNone(smoother.eta_for(0))


if __name__ == "__main__":
    unittest.main()
