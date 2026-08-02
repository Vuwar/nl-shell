"""ai_shell.llm - dates the model states that no result does.

Asked for Python's latest version the model answered "3.14.6, released on
October 7, 2026". Every piece of that date is in the results - another
release's day and month, a year from somewhere else - so nothing token-level
notices. Only the whole date is invented.
"""

import unittest

from ai_shell.llm import _dates, _invented_dates, _spell_date


class Parsing(unittest.TestCase):
    def test_the_ordinary_forms(self):
        for text, want in [
            ("October 7, 2026", {(10, 7, 2026)}),
            ("Oct. 7, 2025", {(10, 7, 2025)}),
            ("Oct 7 2025", {(10, 7, 2025)}),
            ("7 October 2025", {(10, 7, 2025)}),
            ("October 7th, 2025", {(10, 7, 2025)}),
            ("12 August 1990", {(8, 12, 1990)}),
            ("Sept. 5, 2020", {(9, 5, 2020)}),
            ("on 1 Sept 1939 war", {(9, 1, 1939)}),
            ("2026-10-01", {(10, 1, 2026)}),
            ("2026-06-05", {(6, 5, 2026)}),
            ("Jan 1, 2020 and 2 Feb 2021", {(1, 1, 2020), (2, 2, 2021)}),
        ]:
            with self.subTest(text=text):
                self.assertEqual(_dates(text), want)

    def test_run_together_table_cells(self):
        # Stripping tags out of a table runs its cells together. \b finds no
        # boundary between "6" and "J", so python.org's release table - the
        # page the original bug came from - parsed as having no dates at all,
        # which would have made every correct date look invented.
        self.assertEqual(_dates("Python 3.14.6June 10, 2026"), {(6, 10, 2026)})
        self.assertEqual(_dates("3.14.0Oct. 7, 2025 Download"), {(10, 7, 2025)})
        self.assertEqual(_dates("Download2026-10-01(planned)"), {(10, 1, 2026)})

    def test_a_month_glued_to_letters_is_not_a_month(self):
        self.assertEqual(_dates("Junction 10, 2026"), set())
        self.assertEqual(_dates("Marched 3, 2020"), set())

    def test_partial_and_bogus_dates_are_not_dates(self):
        for text in ("published in 1965", "May 2026", "2026-77-99", "version 2026.10.01",
                     "no dates here at all"):
            with self.subTest(text=text):
                self.assertEqual(_dates(text), set())

    def test_a_date_after_an_unrelated_number(self):
        self.assertEqual(_dates("phone 5551234 Oct 5, 2020"), {(10, 5, 2020)})


class Invented(unittest.TestCase):
    def setUp(self):
        self.sources = [
            "Python 3.14.6June 10, 2026 Download Python 3.14.0Oct. 7, 2025 Download",
            "Python 3.14.0 was released on Oct. 7, 2025.",
        ]

    def test_catches_a_date_assembled_from_parts(self):
        self.assertEqual(
            _invented_dates("Python 3.14.6 was released on October 7, 2026.", self.sources),
            [(10, 7, 2026)])

    def test_passes_a_date_the_sources_state(self):
        self.assertEqual(
            _invented_dates("Python 3.14.6 was released on June 10, 2026.", self.sources), [])

    def test_tolerates_a_different_format(self):
        self.assertEqual(_invented_dates("Released 10 June 2026.", self.sources), [])

    def test_known_limit_a_real_date_on_the_wrong_subject_is_not_caught(self):
        # October 7 2025 is real - it is 3.14.0's release date, not 3.14.6's.
        # Checking the pairing was built and measured: matching a date against
        # the subject beside it got six of eight test answers wrong, passing
        # this very case while rejecting four answers that were correct. A
        # check that suppresses good answers to catch one bad one is worse
        # than the bug, so this is deliberately still wrong.
        self.assertEqual(
            _invented_dates("Python 3.14.6 was released on October 7, 2025.", self.sources), [])

    def test_no_dates_to_check(self):
        self.assertEqual(_invented_dates("Python 3.14.6 is the latest.", self.sources), [])

    def test_no_source_text_means_no_check(self):
        # Nothing to compare against isn't evidence of invention.
        self.assertEqual(_invented_dates("On October 7, 2026.", ["", ""]), [])


class Spelling(unittest.TestCase):
    def test_reads_back_the_way_a_person_writes_it(self):
        self.assertEqual(_spell_date((10, 7, 2026)), "October 7, 2026")


if __name__ == "__main__":
    unittest.main()
