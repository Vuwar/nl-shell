"""ai_shell.platforms - reading how much graphics memory is free right now.

The reading decides whether the user is told their card is full, so a probe
that guesses is worse than one that admits it doesn't know: every caller
treats None as "say nothing".
"""

import subprocess
import unittest
from unittest import mock

from ai_shell.platforms import current


def _nvidia_smi(stdout):
    return mock.Mock(stdout=stdout, returncode=0)


class FreeVram(unittest.TestCase):
    def test_reads_the_free_column(self):
        with mock.patch("subprocess.run", return_value=_nvidia_smi("8188, 2642\n")):
            self.assertAlmostEqual(current.free_vram_gb(), 2642 / 1024, places=3)

    def test_takes_the_free_memory_of_the_largest_card(self):
        # vram_gb() reports the largest single card because llama.cpp loads
        # onto one device. The free reading has to come from that same card,
        # not the first row and not a sum.
        stdout = "8188, 512\n24564, 20000\n"
        with mock.patch("subprocess.run", return_value=_nvidia_smi(stdout)):
            self.assertAlmostEqual(current.free_vram_gb(), 20000 / 1024, places=3)

    def test_no_nvidia_smi_is_not_an_error(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(current.free_vram_gb())

    def test_a_hanging_probe_is_not_an_error(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 10)):
            self.assertIsNone(current.free_vram_gb())

    def test_garbage_output_is_not_an_error(self):
        with mock.patch("subprocess.run", return_value=_nvidia_smi("no devices were found\n")):
            self.assertIsNone(current.free_vram_gb())


class Probe(unittest.TestCase):
    def test_probe_records_whether_the_memory_is_shared(self):
        from ai_shell import hardware

        with mock.patch.object(type(current), "total_ram_gb", return_value=32.0), \
             mock.patch.object(type(current), "vram_gb", return_value=8.0), \
             mock.patch.object(type(current), "vram_is_shared", return_value=False):
            probed = hardware.probe()
        self.assertEqual(probed["vram_gb"], 8.0)
        self.assertFalse(probed["vram_shared"])
