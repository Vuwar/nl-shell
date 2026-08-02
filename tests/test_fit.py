"""ai_shell.fit - how much of a graphics card a model may actually have.

The numbers here are the ones that shipped a 7.875GB model onto an 8GB card
that already had 5.5GB of desktop on it, so the boundary cases are the point.
"""

import unittest

from ai_shell import fit, models


class UsableVram(unittest.TestCase):
    def test_a_small_card_reserves_the_floor(self):
        # 8 * 0.15 = 1.2, which is above the 1.0 floor, so the fraction wins.
        self.assertAlmostEqual(fit.usable_vram_gb(8.0), 6.8)

    def test_a_tiny_card_reserves_the_floor_not_the_fraction(self):
        # 4 * 0.15 = 0.6, below the floor.
        self.assertAlmostEqual(fit.usable_vram_gb(4.0), 3.0)

    def test_shared_memory_is_not_reserved_twice(self):
        # macOS already hands back a fraction of RAM; reserving again would
        # shrink Mac model choice for no reason.
        self.assertAlmostEqual(fit.usable_vram_gb(24.0, shared=True), 24.0)

    def test_nothing_is_usable_on_a_machine_with_no_card(self):
        self.assertEqual(fit.usable_vram_gb(None), 0.0)


class Verdict(unittest.TestCase):
    def setUp(self):
        self.q6 = models.by_id("qwen2.5-coder-7b-q6")   # 6.3GB weights, 7.875 footprint
        self.q4 = models.by_id("qwen2.5-coder-7b-q4")   # 4.7GB weights, 5.875 footprint

    def test_the_reported_machine_is_oversized(self):
        # An 8GB card: 6.8 usable, and the model claims 7.875.
        self.assertEqual(fit.verdict(self.q6, 8.0, 2.6), "oversized")

    def test_oversized_is_decided_without_a_free_reading(self):
        # AMD and Intel have no free probe; the permanent mismatch is still
        # knowable from the total alone.
        self.assertEqual(fit.verdict(self.q6, 8.0, None), "oversized")

    def test_a_fitting_model_on_a_busy_card_is_squeezed(self):
        self.assertEqual(fit.verdict(self.q4, 8.0, 2.6), "squeezed")

    def test_a_fitting_model_on_a_free_card_says_nothing(self):
        self.assertIsNone(fit.verdict(self.q4, 8.0, 7.4))

    def test_exactly_at_the_boundary_fits(self):
        # 6.8 usable, footprint 6.8 - a model that exactly fills the budget is
        # allowed. The bug was the >= against the *unreserved* total.
        exact = models.Model("exact", "ref", "exact", 6.8 / 1.25)
        self.assertIsNone(fit.verdict(exact, 8.0, 8.0))

    def test_an_unknown_card_says_nothing(self):
        self.assertIsNone(fit.verdict(self.q6, None, None))


class GpuLayers(unittest.TestCase):
    """The measured curve this exists for, on an 8GB card with 5.8GB free:

        0 layers 16.5 tok/s · 16 layers 26.4 · 24 layers 38.3 ·
        27 layers 45.3 · 28 layers (all) 7.0

    All-or-nothing had to pick either end of that. These tests pin the rule to
    landing short of the cliff.
    """

    def setUp(self):
        self.q4 = models.by_id("qwen2.5-coder-7b-q4")   # 4.7GB over 28 layers

    def test_the_reported_machine_lands_on_the_measured_best(self):
        # 27 of 28 measured 42.2 tokens/sec; 28 measured 6.9.
        self.assertEqual(fit.gpu_layers(self.q4, 5.8, 8192), 27)

    def test_the_partial_split_never_reaches_the_whole_model(self):
        # The cliff by another route: a budget that divides into 28 layers
        # must still stop at 27, because the full-offload check above is the
        # only place allowed to say "all of it".
        for free in (5.9, 6.0, 6.1, 6.2, 6.3, 6.4):
            layers = fit.gpu_layers(self.q4, free, 8192)
            self.assertNotEqual(layers, self.q4.layers,
                                f"{free}GB free asked for every layer the slow way")

    def test_a_roomy_card_gets_everything(self):
        # -1 rather than a count: where it all fits, llama.cpp's own handling
        # beats our approximation of layer sizes.
        self.assertEqual(fit.gpu_layers(self.q4, 16.0, 8192), -1)

    def test_everything_is_only_offered_with_room_to_spare(self):
        # Just enough for weights, cache and scratch is not enough: that is
        # the arrangement that measured 6.9 tokens a second.
        barely = self.q4.weights_gb + 0.44 + fit.COMPUTE_GB + 0.1
        self.assertNotEqual(fit.gpu_layers(self.q4, barely, 8192), -1)

    def test_a_card_with_nothing_free_gets_nothing(self):
        self.assertEqual(fit.gpu_layers(self.q4, 1.0, 8192), 0)

    def test_no_card_gets_nothing(self):
        self.assertEqual(fit.gpu_layers(self.q4, None, 8192), 0)

    def test_a_bigger_context_costs_layers(self):
        roomy = fit.gpu_layers(self.q4, 5.8, 4096)
        cramped = fit.gpu_layers(self.q4, 5.8, 32768)
        self.assertGreater(roomy, cramped,
                           "the key/value cache comes out of the same budget as the weights")

    def test_a_handful_of_layers_is_not_worth_splitting_for(self):
        # Just above the point where the budget buys one or two layers: the
        # transfers cost more than the layers save.
        layers = fit.gpu_layers(self.q4, 1.9, 8192)
        self.assertEqual(layers, 0)

    def test_shared_memory_keeps_no_safety_margin(self):
        # There is no separate card to overrun, and no bus to cross when it
        # fills - the reserve there is the operating system's business. The
        # same 5.8GB that buys a partial split on a discrete card takes the
        # whole model on unified memory.
        self.assertEqual(fit.gpu_layers(self.q4, 5.8, 8192, shared=True), -1)
        self.assertNotEqual(fit.gpu_layers(self.q4, 5.8, 8192), -1)


class Explain(unittest.TestCase):
    def test_squeezed_names_what_the_other_programs_hold(self):
        text = fit.explain("squeezed", total_vram_gb=8.0, free_vram_gb=2.6)
        self.assertIn("5.4GB", text)
        self.assertIn("graphics card", text)

    def test_oversized_does_not_name_a_command(self):
        # The window says "/settings" and the console says "model"; a shared
        # module that picks one is wrong in the other.
        text = fit.explain("oversized")
        self.assertNotIn("/", text)
        self.assertNotIn("model to switch", text)

    def test_the_startup_wording_does_not_claim_something_was_slow(self):
        # Nothing has run yet at that point. A warning that describes an
        # experience the user hasn't had is a warning they stop believing.
        text = fit.explain("oversized", measured=False)
        self.assertNotIn("was slow", text)
        text = fit.explain("squeezed", 8.0, 2.6, measured=False)
        self.assertNotIn("was slow", text)

    def test_an_oversized_model_is_described_as_a_trade_not_a_fault(self):
        # It measured 20 tokens a second once partial offload existed, against
        # 0.8 before. "Runs from ordinary memory, answer in seconds" was true
        # of the old behaviour and is a lie about this one.
        text = fit.explain("oversized")
        self.assertIn("part of it", text)
        self.assertIn("works", text)

    def test_no_jargon_reaches_the_user(self):
        for kind in ("squeezed", "oversized"):
            text = fit.explain(kind, total_vram_gb=8.0, free_vram_gb=2.6).lower()
            for word in ("vram", "offload", "gpu", "quantis", "token"):
                self.assertNotIn(word, text)
