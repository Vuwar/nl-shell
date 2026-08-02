"""Why something failed has to come from the error, not from imagination.

The conversation this exists to prevent:

    > is bluetooth open
    Checking whether Bluetooth is open.
    Running
    > can you close it?
    I'll close Bluetooth.
    x I couldn't stop the Bluetooth service - it doesn't seem to be running.

The shell had just printed "Running". One turn later it said the opposite,
about the same service, in the same conversation. What actually happened was:

    Stop-Service : Service 'Bluetooth Support Service (bthserv)' cannot be
    stopped due to the following error: Cannot open bthserv service on
    computer '.'.

which is what Windows says when you are not an administrator. Nothing in it
mentions the service being stopped. Asked to give "the real-world cause" for
an error whose text is opaque, the model reached for the most ordinary reason
a stop might fail and stated it as fact - three times out of three.

So the errors that have one unambiguous meaning are read here, in code,
before the model is asked anything. The model keeps the long tail, with a
prompt that tells it to say plainly when the error doesn't give a reason
rather than supplying one.
"""

import unittest

from ai_shell import llm
from tests.stubs import DeadClient

# The real thing, captured from a non-elevated PowerShell.
NOT_ADMIN = (
    "Stop-Service : Service 'Bluetooth Support Service (bthserv)' cannot be "
    "stopped due to the following error: Cannot open bthserv service on "
    "computer '.'.\n"
    "    + FullyQualifiedErrorId : CouldNotStopService,"
    "Microsoft.PowerShell.Commands.StopServiceCommand"
)


class ErrorsWithOneMeaning(unittest.TestCase):
    """Read in code, so the answer can't drift and can't be invented."""

    def _reason(self, error_text):
        # A dead client proves the model was never consulted.
        return llm.explain_failure(DeadClient(), "close bluetooth", "Stop-Service x", error_text)

    def test_a_service_that_needs_elevation(self):
        reason = self._reason(NOT_ADMIN)
        self.assertIn("administrator", reason.lower())

    def test_it_does_not_invent_a_state(self):
        # The specific lie: the shell had just shown the service as Running.
        self.assertNotIn("not running", self._reason(NOT_ADMIN).lower())

    def test_plain_access_denied(self):
        self.assertIn("administrator", self._reason("Access is denied.").lower())

    def test_an_explicit_elevation_message(self):
        for text in ("The requested operation requires elevation.",
                     "You must run this command as Administrator."):
            with self.subTest(text):
                self.assertIn("administrator", self._reason(text).lower())

    def test_a_unix_permission_error(self):
        # Not the same thing as needing an administrator - a file this user
        # isn't allowed to touch stays that way whoever they log in as.
        reason = self._reason("rm: cannot remove 'x': Permission denied")
        self.assertIn("permission", reason.lower())

    def test_the_sentence_is_in_the_apps_own_voice(self):
        self.assertTrue(self._reason(NOT_ADMIN).startswith("I "))


class ErrorsWithoutOneMeaning(unittest.TestCase):
    """Everything else still goes to the model."""

    def test_an_unremarkable_error_is_left_to_the_model(self):
        client = DeadClient()
        # DeadClient raises, so explain_failure falls back - which is proof
        # enough that it tried to ask rather than answering from a table.
        reason = llm.explain_failure(client, "do a thing", "Some-Command", "Something odd happened.")
        self.assertIn("Something odd happened", reason)

    def test_the_prompt_forbids_supplying_a_reason(self):
        prompt = llm.EXPLAIN_FAILURE_PROMPT.lower()
        self.assertIn("only what the error", prompt)
        self.assertIn("does not say why", prompt)


class TheFallbackSentence(unittest.TestCase):
    """When there is no model and no rule that matches."""

    def test_it_quotes_the_error_rather_than_explaining_it(self):
        reason = llm._fallback_reason("Some-Command : it went wrong")
        self.assertIn("it went wrong", reason)

    def test_it_admits_when_there_is_nothing_to_go_on(self):
        self.assertIn("without giving a reason", llm._fallback_reason(""))


class ABareStatusWord(unittest.TestCase):
    """"Running" is command output, not an answer to "is bluetooth open"."""

    def test_the_prompt_says_so(self):
        self.assertIn("bare status word", llm.SYSTEM_PROMPT.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
