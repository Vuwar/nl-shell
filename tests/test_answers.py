"""ai_shell.llm.answer_from_search - reading the model's reply, and the one
retry it gets when it makes a date up."""

import json
import unittest

from ai_shell.llm import answer_from_search
from tests.stubs import DeadClient, StubClient

# Five results whose text shares nothing checkable with the stub answers, so
# the parsing tests aren't also exercising the support check.
NEUTRAL = ["alpha", "beta", "gamma", "delta", "epsilon"]

# A source that states one real date, for the retry tests.
DATED = ["Python 3.14.6June 10, 2026 Download Python 3.14.0Oct. 7, 2025", "x", "y"]
BAD = json.dumps({"answer": "Python 3.14.6 came out October 7, 2026.", "sources": [1]})
GOOD = json.dumps({"answer": "Python 3.14.6 came out June 10, 2026.", "sources": [1]})


class SchemaReply(unittest.TestCase):
    def test_answer_and_citation_are_rendered_together(self):
        client = StubClient(json.dumps({"answer": "Paris is the capital.", "sources": [2]}))
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL),
                         "Paris is the capital. [2]")

    def test_fenced_json(self):
        client = StubClient('```json\n{"answer": "Hi.", "sources": [1]}\n```')
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL), "Hi. [1]")

    def test_json_wrapped_in_chatter(self):
        # _first_json decodes from the start, so it forgives commentary after
        # the JSON but not before. A model asked for JSON opens with "Sure!"
        # and the whole raw object would be shown as the answer.
        client = StubClient('Sure!\n{"answer": "Hi.", "sources": [2]}\nHope that helps')
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL), "Hi. [2]")

    def test_whitespace_is_collapsed(self):
        client = StubClient(json.dumps({"answer": "One thing.\n\nAnother thing.", "sources": [1]}))
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL),
                         "One thing. Another thing. [1]")

    def test_unicode_survives(self):
        client = StubClient(json.dumps({"answer": "Reykjavík is the capital.", "sources": [1]},
                                       ensure_ascii=False))
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL),
                         "Reykjavík is the capital. [1]")

    def test_invented_result_number_is_dropped(self):
        client = StubClient(json.dumps({"answer": "Hi.", "sources": [9]}))
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL), "Hi.")

    def test_missing_sources_key(self):
        client = StubClient('{"answer": "Hi."}')
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL), "Hi.")

    def test_empty_answer_is_nothing_to_show(self):
        client = StubClient(json.dumps({"answer": "   ", "sources": [1]}))
        self.assertIsNone(answer_from_search(client, "q", "b", NEUTRAL))


class WithoutGrammarSupport(unittest.TestCase):
    """An older llama.cpp or an Ollama before 0.5, where _complete has already
    fallen back to an unconstrained call. The prompt still asked for an answer
    and the model still wrote one."""

    def test_prose_is_shown_as_it_came(self):
        client = StubClient("Just prose, no JSON at all.")
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL),
                         "Just prose, no JSON at all.")

    def test_prose_keeps_whatever_markers_it_chose(self):
        client = StubClient("Paris is the capital [3].")
        self.assertEqual(answer_from_search(client, "q", "b", NEUTRAL),
                         "Paris is the capital [3].")

    def test_malformed_json_degrades_rather_than_raising(self):
        # A raw control character inside a JSON string is not valid JSON.
        client = StubClient('{"answer": "a\nb", "sources": [1]}')
        self.assertIsNotNone(answer_from_search(client, "q", "b", NEUTRAL))

    def test_non_string_answer_degrades(self):
        client = StubClient('{"answer": 42, "sources": [1]}')
        self.assertIsNotNone(answer_from_search(client, "q", "b", NEUTRAL))


class InventedDateRetry(unittest.TestCase):
    def test_a_made_up_date_is_sent_back_once_and_fixed(self):
        client = StubClient(BAD, GOOD)
        self.assertEqual(answer_from_search(client, "q", "b", DATED),
                         "Python 3.14.6 came out June 10, 2026. [1]")
        self.assertEqual(client.calls, 2)

    def test_the_retry_names_the_offending_date(self):
        client = StubClient(BAD, GOOD)
        answer_from_search(client, "q", "b", DATED)
        correction = client.messages[1][-1]["content"]
        self.assertIn("October 7, 2026", correction)

    def test_a_clean_answer_costs_one_call(self):
        client = StubClient(GOOD)
        self.assertEqual(answer_from_search(client, "q", "b", DATED),
                         "Python 3.14.6 came out June 10, 2026. [1]")
        self.assertEqual(client.calls, 1)

    def test_still_inventing_after_the_retry_means_no_summary(self):
        # Rather than choose between two answers there's reason to distrust,
        # the sources go up without one.
        client = StubClient(BAD, BAD)
        self.assertIsNone(answer_from_search(client, "q", "b", DATED))
        self.assertEqual(client.calls, 2)


class Unreachable(unittest.TestCase):
    def test_a_model_that_cannot_be_reached_is_not_an_error(self):
        # The caller shows the results by themselves - a worse answer, never
        # a wrong one.
        self.assertIsNone(answer_from_search(DeadClient(), "q", "b", NEUTRAL))


if __name__ == "__main__":
    unittest.main()
