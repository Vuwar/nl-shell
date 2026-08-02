"""ai_shell.models - which model this machine is handed.

The table in RecommendedModel is the regression this file exists for: an 8GB
card was handed a 7.875GB model because the budget was the card's total rather
than what a desktop leaves of it.
"""

import unittest

from ai_shell import models


class RecommendedModel(unittest.TestCase):
    def test_an_eight_gigabyte_card_gets_a_model_that_fits(self):
        # 6.8GB usable after the reserve: 7B-Q6 (7.875) is out, 7B-Q4 (5.875) fits.
        self.assertEqual(models.recommend(32.0, 8.0).id, "qwen2.5-coder-7b-q4")

    def test_a_twelve_gigabyte_card_is_unchanged(self):
        self.assertEqual(models.recommend(32.0, 12.0).id, "qwen2.5-coder-7b-q6")

    def test_a_sixteen_gigabyte_card_is_unchanged(self):
        self.assertEqual(models.recommend(32.0, 16.0).id, "qwen2.5-coder-14b-q4")

    def test_no_card_falls_back_to_ram_under_the_cpu_ceiling(self):
        self.assertEqual(models.recommend(32.0, None).id, "qwen2.5-coder-7b-q4")

    def test_an_unreadable_machine_gets_the_fallback(self):
        self.assertEqual(models.recommend(None, None).id, models.FALLBACK.id)

    def test_a_card_too_small_for_the_floor_is_ignored_for_ram(self):
        # A 32GB machine with a 2GB display adapter must not be handed the
        # weakest model on the list.
        self.assertEqual(models.recommend(32.0, 2.0).id, "qwen2.5-coder-7b-q4")

    def test_shared_memory_is_not_reserved_twice(self):
        # An M-series Mac: vram_gb is already 70% of RAM. Reserving again would
        # cost it a model size for nothing.
        self.assertEqual(models.recommend(32.0, 22.4, shared=True).id, "qwen2.5-coder-14b-q4")


class Catalog(unittest.TestCase):
    def test_rows_say_what_fits_this_card(self):
        rows = {row["id"]: row for row in models.catalog(8.0, 32.0)}
        self.assertTrue(rows["qwen2.5-coder-7b-q4"]["fits"])
        self.assertFalse(rows["qwen2.5-coder-7b-q6"]["fits"])
        self.assertFalse(rows["qwen2.5-coder-32b-q4"]["fits"])

    def test_a_machine_with_no_card_is_judged_on_ram_under_the_ceiling(self):
        rows = {row["id"]: row for row in models.catalog(None, 32.0)}
        self.assertTrue(rows["qwen2.5-coder-7b-q4"]["fits"])
        # Nothing above the CPU ceiling is offered: it would answer in minutes.
        self.assertFalse(rows["qwen2.5-coder-14b-q4"]["fits"])

    def test_installed_and_current_are_marked(self):
        rows = {
            row["id"]: row
            for row in models.catalog(
                8.0, 32.0, installed=("qwen2.5-coder-7b-q6",), current_id="qwen2.5-coder-7b-q6"
            )
        }
        self.assertTrue(rows["qwen2.5-coder-7b-q6"]["installed"])
        self.assertTrue(rows["qwen2.5-coder-7b-q6"]["current"])
        self.assertFalse(rows["qwen2.5-coder-3b-q4"]["installed"])

    def test_every_model_gets_a_row(self):
        self.assertEqual(len(models.catalog(8.0, 32.0)), len(models.MODELS))

    def test_a_little_over_budget_and_far_over_are_told_apart(self):
        # On an 8GB card the 7B-Q6 measured 20 tokens a second with part of it
        # on the card. A 32B three times over budget would be well under one.
        # Describing both as "slower" tells the user nothing.
        rows = {row["id"]: row for row in models.catalog(8.0, 32.0)}
        self.assertEqual(rows["qwen2.5-coder-7b-q4"]["speed"], "full")
        self.assertEqual(rows["qwen2.5-coder-7b-q6"]["speed"], "partial")
        self.assertEqual(rows["qwen2.5-coder-32b-q4"]["speed"], "poor")
