"""Session - telling the user why an answer took a minute.

A startup check cannot see a game launched ten minutes later; this one can.
Everything here is about not crying wolf: a card-less machine is slow by
nature, a six-token reply is too short to time, and an unexplained slow answer
gets no message rather than a guessed one.
"""

import json
import unittest
from unittest import mock

from ai_shell import config, llm, models, server
from ai_shell.platforms import current
from ai_shell.session import Session
from tests.stubs import StubClient

REPLY = json.dumps({
    "command": None, "search": None, "risk": None,
    "explanation": "Hello.", "options": None,
})

GPU_MACHINE = {"vram_gb": 8.0, "vram_shared": False}


def _session():
    with mock.patch.object(Session, "_scan_apps", return_value=[]):
        session = Session()
    session.client = StubClient(REPLY)
    return session


class SlowNotice(unittest.TestCase):
    def _translate(self, rate, machine=GPU_MACHINE, others=5.4, model="qwen2.5-coder-7b-q4",
                   session=None):
        """A turn at `rate` tokens a second, with `others` GB of the card held
        by programs that aren't us. `others` rather than a free reading,
        because the free reading includes our own weights and the code under
        test is what subtracts them."""
        session = session or _session()
        with mock.patch("ai_shell.session.ask_model", return_value=(json.loads(REPLY), rate)), \
             mock.patch.object(config, "HARDWARE", machine), \
             mock.patch.object(config, "current_model", return_value=models.by_id(model)), \
             mock.patch.object(type(current), "free_vram_gb", return_value=1.0), \
             mock.patch.object(server, "others_vram_gb", return_value=others):
            return session, session.translate("hey")

    def test_a_slow_answer_on_a_busy_card_is_explained(self):
        _, data = self._translate(0.82)
        self.assertIn("graphics card", data["notice"])

    def test_the_number_counts_other_programs_and_not_our_own_model(self):
        # The reported bug: our own resident weights were being read back to
        # the user as other programs hogging the card.
        _, data = self._translate(0.82, others=2.2)
        self.assertIn("2.2GB", data["notice"])

    def test_a_normal_answer_says_nothing(self):
        _, data = self._translate(45.0)
        self.assertIsNone(data["notice"])

    def test_it_is_said_once_per_session_not_every_turn(self):
        session, data = self._translate(0.82)
        self.assertIsNotNone(data["notice"])
        _, again = self._translate(0.82, session=session)
        self.assertIsNone(again["notice"])

    def test_the_startup_explanation_and_this_one_cannot_both_land(self):
        # Same sentence about the same card from two different modules. Heard
        # twice, with two different numbers in it, it reads as a broken app.
        session = _session()
        self.assertIsNotNone(session.claim_notice("the card is full"))
        _, data = self._translate(0.82, session=session)
        self.assertIsNone(data["notice"])

    def test_a_machine_with_no_card_is_never_told_this(self):
        # 3 tokens a second is a card-less laptop being itself. There is
        # nothing to close, so the message would be a lie.
        _, data = self._translate(3.0, machine={"vram_gb": None}, others=None)
        self.assertIsNone(data["notice"])

    def test_an_unmeasured_answer_says_nothing(self):
        _, data = self._translate(None)
        self.assertIsNone(data["notice"])

    def test_a_slow_answer_with_no_explanation_says_nothing(self):
        # Once our own weights are discounted the card has room, so something
        # else made this slow. A wrong explanation is worse than none.
        _, data = self._translate(0.82, others=0.6)
        self.assertIsNone(data["notice"])

    def test_an_unreadable_card_says_nothing(self):
        _, data = self._translate(0.82, others=None)
        self.assertIsNone(data["notice"])


class Rate(unittest.TestCase):
    def test_a_short_reply_is_not_timed(self):
        client = StubClient(REPLY)
        client.usage_tokens = 6          # below fit.MIN_TIMED_TOKENS
        _, rate = llm.ask_model(client, "hey", [])
        self.assertIsNone(rate)

    def test_a_reply_with_no_usage_is_not_timed(self):
        client = StubClient(REPLY)
        client.usage_tokens = None       # a backend that doesn't report it
        _, rate = llm.ask_model(client, "hey", [])
        self.assertIsNone(rate)

    def test_a_long_reply_is_timed(self):
        client = StubClient(REPLY)
        client.usage_tokens = 63
        _, rate = llm.ask_model(client, "hey", [])
        self.assertIsNotNone(rate)
        self.assertGreater(rate, 0)
