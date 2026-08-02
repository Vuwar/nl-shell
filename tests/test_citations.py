"""ai_shell.llm - which result a citation names, and whether it earns it."""

import unittest

from ai_shell.llm import _citations, _claims, _support


class Claims(unittest.TestCase):
    def test_numbers_and_names_are_kept_apart(self):
        # Conflating them is what made the first version of this useless:
        # every result for a question about Baku says "Baku".
        numbers, names = _claims("Everest 8848")
        self.assertEqual(numbers, {"8848"})
        self.assertEqual(names, {"everest"})

    def test_numbers_normalised_past_formatting(self):
        self.assertIn("884886", _claims("8,848.86 metres")[0])
        self.assertIn("884886", _claims("8848.86 m")[0])

    def test_single_digits_ignored(self):
        # They appear in every page ever written and would match anything.
        self.assertEqual(_claims("a 5 b")[0], set())

    def test_names_compared_without_case(self):
        self.assertIn("reykjavík", _claims("Reykjavík is nice")[1])

    def test_short_words_ignored(self):
        self.assertNotIn("cat", _claims("The Cat")[1])


class Support(unittest.TestCase):
    def test_counts_figures_and_names_separately(self):
        scores = _support("Everest is 8848 m", ["Everest 8848", "Everest only", "nothing"])
        self.assertEqual(scores[0], (1, 1))
        self.assertEqual(scores[1], (0, 1))
        self.assertEqual(scores[2], (0, 0))


class Validation(unittest.TestCase):
    """A grammar guarantees "an integer", never that it names a result on
    screen."""

    def setUp(self):
        self.answer = "Reykjavík is the capital of Iceland."
        self.texts = ["Reykjavík is the capital and largest city of Iceland.",
                      "Iceland is a Nordic country; its capital is Reykjavík.",
                      "Unrelated page.", "Another page.", "Fifth page."]

    def test_keeps_well_formed_picks(self):
        self.assertEqual(_citations([1, 2], self.answer, self.texts), "[1][2]")

    def test_caps_at_two(self):
        self.assertEqual(_citations([1, 2, 3, 4, 5], self.answer, self.texts), "[1][2]")

    def test_collapses_duplicates(self):
        self.assertEqual(_citations([1, 1], self.answer, self.texts), "[1]")

    def test_rejects_values_that_are_not_result_numbers(self):
        # bool is an int in Python and True would otherwise render as [1].
        for junk in ([True], ["1"], [1.0], [[1]], None, "1,2"):
            with self.subTest(junk=junk):
                self.assertNotIn("[True]", _citations(junk, self.answer, self.texts))

    def test_out_of_range_is_dropped_not_clamped(self):
        # A citation nudged onto a neighbouring result is a citation that lies.
        # With support available, the best-supported result is named instead.
        self.assertEqual(_citations([9], self.answer, self.texts), "[1]")

    def test_no_texts_means_no_citation(self):
        self.assertEqual(_citations([1], self.answer, []), "")


class Attribution(unittest.TestCase):
    """Asked about the weather the model answered "around 28°C ... winds up to
    38km/h" and cited two pages containing neither number. They were top-ranked
    and about Baku, which was evidently enough to look right."""

    def setUp(self):
        self.answer = ("The weather in Baku is currently warm with temperatures around "
                       "28°C. There is a slight chance of rain with winds up to 38km/h.")
        self.texts = [
            "Hourly Weather Forecast for Baku. AccuWeather's hourly forecast for Baku "
            "provides hour-by-hour temperatures and precipitation probability.",
            "Baku, Azerbaijan Weather Forecast, with current conditions and wind.",
            "Baku weather page with nothing specific on it.",
            "Another generic Baku forecast page.",
            "Today in Baku: temperature 28°C, sunny, wind up to 38 km/h, "
            "slight chance of rain later.",
        ]

    def test_repoints_a_citation_that_does_not_contain_the_figures(self):
        self.assertEqual(_citations([1, 2], self.answer, self.texts), "[5]")

    def test_leaves_a_correct_citation_alone(self):
        self.assertEqual(_citations([5], self.answer, self.texts), "[5]")

    def test_drops_the_unsupported_half_of_a_pair(self):
        self.assertEqual(_citations([5, 1], self.answer, self.texts), "[5]")

    def test_does_not_pad_to_two(self):
        # The second slot is for a model that genuinely drew on two sources;
        # filling it here would be manufacturing agreement.
        answer = "Mount Everest is 8,848.86 metres tall."
        texts = ["Mount Everest, at 8848.86 m, is Earth's highest mountain.",
                 "Mount Everest height and facts.", "x", "y", "z"]
        self.assertEqual(_citations([1], answer, texts), "[1]")

    def test_leaves_the_model_alone_when_nothing_supports_the_answer(self):
        # No support anywhere says something about the answer, not about which
        # result to blame. Repointing on that basis would invent a provenance.
        self.assertEqual(_citations([2], "A claim about zebras.", ["a", "b", "c"]), "[2]")

    def test_names_only_shared_when_the_answer_has_no_figures(self):
        answer = "Reykjavík is the capital of Iceland."
        texts = ["Reykjavík is the capital of Iceland.", "Iceland, capital Reykjavík.",
                 "Volcanoes.", "x", "y"]
        self.assertEqual(_citations([1, 2], answer, texts), "[1][2]")


if __name__ == "__main__":
    unittest.main()
