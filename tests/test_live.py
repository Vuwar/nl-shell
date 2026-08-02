"""The parts that need the actual internet, and in one case an actual model.

Skipped unless asked for, because they are slow, they depend on pages that
belong to other people, and a search engine will start refusing a machine that
runs them in a loop:

    AI_SHELL_LIVE_TESTS=1 python -m unittest tests.test_live -v

A failure here is not automatically a bug in this code. A site can redesign,
go down, or decide today is the day it wants a CAPTCHA. Read what failed
before believing it.
"""

import os
import re
import unittest

from ai_shell import web
from ai_shell.llm import _dates, answer_from_search

LIVE = os.environ.get("AI_SHELL_LIVE_TESTS")
requires_network = unittest.skipUnless(LIVE, "set AI_SHELL_LIVE_TESTS=1 to run")


@requires_network
class Reading(unittest.TestCase):
    # Prose, tables, docs and a plain-text RFC - between them they cover the
    # shapes the extractor has to survive.
    READABLE = [
        "https://en.wikipedia.org/wiki/Iceland",
        "https://www.python.org/downloads/",
        "https://endoflife.date/python",
        "https://docs.python.org/3/library/urllib.request.html",
        "https://news.ycombinator.com/",
    ]

    def test_real_pages_come_back_as_text(self):
        for url in self.READABLE:
            with self.subTest(url=url):
                text = web.read(url)
                self.assertIsNotNone(text, f"{url} did not read")
                self.assertGreaterEqual(len(text), web._MIN_TEXT)
                self.assertTrue(web._is_text(text))

    def test_wikipedia_is_readable(self):
        # It answers robots.txt with 403 to urllib's default User-Agent, and
        # RobotFileParser.read() records that as "disallow everything" without
        # raising. The best source on the web was the one page the reader
        # would never open.
        self.assertIsNotNone(web.read("https://en.wikipedia.org/wiki/Reykjav%C3%ADk"))

    def test_a_compressed_page_is_not_mojibake(self):
        # python.org sends gzip whether or not it was asked to.
        text = web.read("https://www.python.org/downloads/")
        self.assertIsNotNone(text)
        self.assertIn("Python", text)

    def test_javascript_shells_are_rejected(self):
        # These return every label the page renders with the numbers left out
        # for a script to fill in later - 322 and 359 characters of "Now------
        # Feels Like HHigh LLow", which cleared the old 250 floor and went to
        # the model as though it were a forecast.
        for url in ("https://weather.com/en-FM/az/city/baku/today",
                    "https://weather.com/weather/today/l/Baku+Azerbaijan"):
            with self.subTest(url=url):
                self.assertIsNone(web.read(url))

    def test_reading_several_pages_skips_the_ones_that_fail(self):
        pages = web.read_all(self.READABLE[:3] + ["https://not-a-real-host.invalid/x"])
        self.assertGreaterEqual(len(pages), 2)
        self.assertNotIn("https://not-a-real-host.invalid/x", pages)


@requires_network
class Searching(unittest.TestCase):
    def test_a_search_returns_usable_results(self):
        try:
            results = web.search("capital of iceland")
        except web.SearchError as error:
            self.skipTest(f"search unavailable: {error}")
        self.assertTrue(results)
        for result in results:
            self.assertTrue(result["title"])
            self.assertTrue(result["url"].startswith("http"))

    def test_an_empty_query_is_refused_without_asking_anyone(self):
        with self.assertRaises(web.SearchError):
            web.search("   ")


@requires_network
@unittest.skipUnless(os.environ.get("AI_SHELL_LIVE_TESTS"), "")
class EndToEnd(unittest.TestCase):
    """Search, read, answer - with the real model. Needs a server running at
    config.BASE_URL; skipped rather than failed when there isn't one."""

    QUESTIONS = [
        ("what is the capital of iceland", "capital of iceland"),
        ("how tall is mount everest", "height of mount everest"),
        ("when did apollo 11 land on the moon", "apollo 11 moon landing date"),
    ]

    @classmethod
    def setUpClass(cls):
        from ai_shell.session import Session
        from ai_shell import server
        try:
            server.ensure_running()
        except Exception as error:            # noqa: BLE001 - reported, not handled
            raise unittest.SkipTest(f"no model server: {error}")
        cls.client = Session().client

    def test_answers_cite_results_that_exist_and_state_only_real_dates(self):
        for question, query in self.QUESTIONS:
            with self.subTest(question=question):
                try:
                    results = web.search(query)
                except web.SearchError as error:
                    self.skipTest(f"search unavailable: {error}")
                enriched = web.read_results(results)
                texts = [r.get("text") or r.get("snippet") or "" for r in enriched]
                answer = answer_from_search(
                    self.client, question, web.as_context(enriched), texts)
                if answer is None:
                    continue      # a refused summary is a valid outcome

                cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
                self.assertTrue(cited, f"no citation: {answer}")
                self.assertLess(len(cited), len(enriched),
                                f"cited everything, which cites nothing: {answer}")
                for number in cited:
                    self.assertTrue(1 <= number <= len(enriched))

                known = set()
                for text in texts:
                    known |= _dates(text)
                self.assertFalse(_dates(answer) - known,
                                 f"stated a date no result contains: {answer}")


if __name__ == "__main__":
    unittest.main()
