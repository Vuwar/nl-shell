"""The app talks about its own actions, in the tense they're actually in.

"Opens YouTube in your browser." reads like a caption on someone else's work.
Nobody else is here: the thing that says the sentence is the thing carrying it
out. But which tense it says it in depends on what happens next, and the two
cases are genuinely different:

  * a safe command runs the moment the sentence is printed, so it is happening
    now - "Opening YouTube in your browser."
  * a risky command stops and waits to be confirmed, and may be skipped, so it
    is not happening at all yet - "I'll permanently delete old_notes.txt."

Getting that backwards matters most on the confirmation screen, which is the
one place a non-technical user needs to be sure nothing has happened to their
files yet. "Deleting old_notes.txt." above a "Run it?" prompt says it already
has.

There is one hole, and it is known rather than fixed: ai_shell.policy can call
a command risky after the model has already written a present-tense sentence
for it. That leaves "Deleting old_notes.txt." above a confirmation, which is
the case this is all trying to avoid - but it only happens when the model
mislabelled the command in the first place, and the confirmation prompt is
right there saying what the command does. Rewriting the sentence would mean
conjugating an arbitrary verb, which is a worse bug generator than the case it
would fix.

The voice is spread across places that don't know about each other - the
worked examples that teach the model, the prompt that turns an error into a
sentence, the rules that answer without the model, and the failures the app
writes itself. Left alone they drift apart. These tests are what stops that: a
new worked example in the wrong voice or the wrong tense fails here rather
than shipping.

Statements about the world are deliberately exempt. "That's a file, not a
folder" has no actor in it and doesn't want one.
"""

import re
import unittest
from unittest import mock

from ai_shell import llm, rules
from ai_shell.platforms.linux import Linux
from ai_shell.platforms.macos import MacOS
from ai_shell.platforms.windows import Windows

PLATFORMS = (Windows, MacOS, Linux)

# One worked example's JSON object, on its own line.
_OBJECT = re.compile(r"^\{.*\}$", re.M)

# "explanation": "...", with escaped quotes inside it surviving.
_EXPLANATION = re.compile(r'"explanation":\s*"((?:[^"\\]|\\.)*)"')
_RISK = re.compile(r'"risk":\s*(?:"(\w+)"|null)')
_SEARCH = re.compile(r'"search":\s*(?:"((?:[^"\\]|\\.)*)"|null)')

# The bullet list of good examples in EXPLAIN_FAILURE_PROMPT.
_BULLET = re.compile(r'^- "(.+)"$', re.M)

# "I", "I'll", "me" - the app referring to itself. Case-sensitive on I,
# because a lowercase "i" inside a word is not a pronoun.
_FIRST_PERSON = re.compile(r"\b(?:I|I'll|I'm|I've|me|my)\b")

# "Opening ...", "Listing ...", "Zipping ..." - happening as you read it.
_PROGRESSIVE = re.compile(r"^[A-Z][a-z]+ing\b")


def _first_person(sentence):
    return bool(_FIRST_PERSON.search(sentence))


def _examples(text):
    """Every worked example in `text` as (risk, searching, explanation).

    Parsed with regexes rather than json.loads because these objects are
    written to be copied by the model, not decoded here: the Windows ones
    carry Windows paths, whose backslashes are not valid JSON escapes.
    """
    found = []
    for line in _OBJECT.findall(text):
        explanation = _EXPLANATION.search(line)
        if not explanation:
            continue
        risk = _RISK.search(line)
        search = _SEARCH.search(line)
        found.append((
            risk.group(1) if risk else None,
            bool(search and search.group(1)),
            explanation.group(1),
        ))
    return found


class TheWorkedExamples(unittest.TestCase):
    """What the model is shown, and therefore what it copies.

    The examples do more than the rule does. Telling a 3B model to match its
    tense to its own risk label is a request it can decline; showing it every
    safe example in the present tense and every risky one in the future is
    what actually decides the output.
    """

    def test_the_examples_parse_at_all(self):
        # If this breaks, every other test in this class passes vacuously.
        for platform in PLATFORMS:
            with self.subTest(platform.__name__):
                self.assertGreaterEqual(len(_examples(platform.EXAMPLES)), 8)

    def test_a_command_that_runs_at_once_is_in_the_present(self):
        for platform in PLATFORMS:
            for risk, _, sentence in _examples(platform.EXAMPLES):
                if risk != "safe":
                    continue
                with self.subTest(platform=platform.__name__, sentence=sentence):
                    self.assertRegex(
                        sentence, _PROGRESSIVE,
                        f"a safe command runs immediately, so this should say it is "
                        f"happening now: {sentence!r}")

    def test_a_command_that_waits_to_be_confirmed_is_in_the_future(self):
        for platform in PLATFORMS:
            for risk, _, sentence in _examples(platform.EXAMPLES):
                if risk != "risky":
                    continue
                with self.subTest(platform=platform.__name__, sentence=sentence):
                    self.assertTrue(
                        sentence.startswith("I'll "),
                        f"a risky command may never run, so this must not claim to be "
                        f"under way: {sentence!r}")

    def test_a_web_lookup_is_in_the_present(self):
        # Searches don't stop to be confirmed either.
        for platform in PLATFORMS:
            for _, searching, sentence in _examples(platform.EXAMPLES):
                if not searching:
                    continue
                with self.subTest(platform=platform.__name__, sentence=sentence):
                    self.assertRegex(sentence, _PROGRESSIVE)

    def test_nothing_is_written_in_the_third_person(self):
        # The original complaint: "Opens YouTube in your browser." Neither
        # tense above can be third person, so this is the backstop that keeps
        # a future example from reintroducing it.
        for platform in PLATFORMS:
            for risk, _, sentence in _examples(platform.EXAMPLES):
                if risk is None:
                    continue  # small talk and clarifying questions
                with self.subTest(platform=platform.__name__, sentence=sentence):
                    self.assertTrue(
                        _first_person(sentence) or _PROGRESSIVE.match(sentence),
                        f"reads as someone else's caption: {sentence!r}")

    def test_the_prompt_states_both_tenses(self):
        # Belt and braces: the examples carry the weight, but a request the
        # examples don't cover should still come out right. Asserting on the
        # two things the rule has to say, rather than on any one wording of
        # it - the examples above are what this is really enforced by.
        prompt = llm.SYSTEM_PROMPT.lower()
        self.assertIn("already running", prompt)
        self.assertIn("not happening yet", prompt)


class ThingsItCannotKnow(unittest.TestCase):
    """The app must not describe the state of a machine it cannot see.

    Seen in the wild, before anything had been run:

        > open bluetooth settings
        Bluetooth settings are already open.
        > no it's not
        Opening Bluetooth settings. Done
        > close bluetooth settings
        Bluetooth settings are already closed.

    Both claims were invented, and the second contradicted the note in its own
    history from one turn earlier. This is worse than a wrong label: the
    request is silently not carried out, and the user is told a fact about
    their own computer that isn't true.

    Only the prompt can be checked here - whether the model obeys is measured
    against a running model, not in a unit test.
    """

    def test_the_prompt_forbids_it(self):
        prompt = llm.SYSTEM_PROMPT.lower()
        self.assertIn("you cannot see", prompt)
        self.assertIn("already", prompt)

    def test_it_must_not_invent_choices_about_this_machine(self):
        # Asked to "toggle bluetooth", the model asked "Which Bluetooth device
        # would you like to toggle?" and offered "Bluetooth Adapter 1" and
        # "Bluetooth Adapter 2". Neither exists - this machine has one
        # adapter, and the model has never been told anything about it. The
        # user picked a made-up device, and what came back was a command that
        # didn't toggle anything.
        prompt = llm.SYSTEM_PROMPT.lower()
        self.assertIn("never invent choices", prompt)

    def test_it_must_not_ask_about_something_already_named(self):
        self.assertIn("already named", llm.SYSTEM_PROMPT.lower())

    def test_the_prompt_says_what_to_do_instead(self):
        # A prohibition on its own leaves the model to invent a way out, and
        # the way out it invents is refusing. The rule has to say "do it".
        self.assertIn("carry the request out anyway", llm.SYSTEM_PROMPT.lower())


class TheFailureSentences(unittest.TestCase):
    """Why something didn't work. Past tense, because it already didn't."""

    def test_the_examples_the_model_is_given(self):
        found = _BULLET.findall(llm.EXPLAIN_FAILURE_PROMPT)
        self.assertTrue(found, "no failure examples parsed out of the prompt")
        for sentence in found:
            with self.subTest(sentence):
                self.assertTrue(_first_person(sentence), f"not first person: {sentence!r}")

    def test_the_sentence_written_when_the_model_cannot_be_reached(self):
        # No model means no model-written sentence, and the fallback is the
        # one failure message a user is most likely to see twice.
        self.assertTrue(_first_person(llm._fallback_reason("Access is denied.")))

    def test_the_sentence_written_when_there_is_no_error_text_at_all(self):
        self.assertTrue(_first_person(llm._fallback_reason("")))


class TheRules(unittest.TestCase):
    """What the app says when it answers without the model at all.

    Both of these are safe commands that run the moment the sentence appears,
    so both are in the present. A rule that ever emits a risky command owes
    its sentence the future tense - see ai_shell.rules.base.run.
    """

    def _explanation(self, text):
        return rules.resolve(text, rules.Machine(tuple)).explanation

    def test_opening_a_site(self):
        self.assertEqual(self._explanation("open youtube"),
                         "Opening YouTube in your browser.")

    def test_searching_a_site(self):
        self.assertEqual(self._explanation("open eminem on youtube"),
                         "Opening a YouTube search for eminem in your browser.")


class TheSessionsOwnSentences(unittest.TestCase):
    """The few the app writes itself, with no model in the loop."""

    def _session(self):
        with mock.patch("ai_shell.session.list_apps", return_value=[]):
            from ai_shell.session import Session
            return Session()

    def test_a_search_that_finds_nothing(self):
        session = self._session()
        with mock.patch("ai_shell.web.search", return_value=[]):
            result = session._run_search("qwertyuiop", "look up qwertyuiop")
        self.assertTrue(_first_person(result["reason"]), result["reason"])

    def test_a_folder_that_will_not_open(self):
        session = self._session()
        with mock.patch.object(session, "_run_listing", return_value=None), \
             mock.patch("os.path.isdir", return_value=True):
            result = session.list_directory("C:\\somewhere")
        self.assertTrue(_first_person(result["reason"]), result["reason"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
