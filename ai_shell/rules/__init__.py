"""Requests this shell can answer exactly, without asking the model.

Most of what a user types has to be translated, because most of it is about
their own machine and no two machines are alike. Some of it doesn't. The
address of a YouTube search is not something to reason about - it's a fact,
and a fact belongs in a table. Requests that match one run instantly, offline,
and identically every time, which is three things a 3B model cannot promise.

A rule is one function:

    resolve(text, machine) -> Answer or None

`text` is what the user typed, tidied by base.clean. `machine` is the narrow
view of this computer a rule is allowed to ask about. Returning None means "not
mine", and the next rule gets a turn; returning an Answer ends it, and the
model is never called.

Adding one means writing that function and putting it in RULES below. It
should not mean touching ai_shell.session, and it should not mean knowing what
the interfaces expect to be handed - see ai_shell.rules.base for why the
Answer sits in between.

Order matters only where two rules could both match, and the fix for that is
usually a narrower rule rather than a careful position in the list.
"""

from ai_shell.rules import apps, sites, toggles
from ai_shell.rules.base import (
    Answer, Machine, ask, asks_a_question, clean, is_question, look_up,
    open_url, run, say,
)

__all__ = [
    "Answer", "Machine", "resolve", "ask", "asks_a_question", "clean",
    "is_question", "look_up", "open_url", "run", "say",
]

RULES = (
    sites.resolve,
    apps.resolve,
    toggles.resolve,
)


def resolve(user_input, machine=None):
    """The first rule that recognises `user_input`, as an Answer, or None.

    None is the normal case and not a failure: it means this was a request for
    the model, which is what the app is for.
    """
    text = clean(user_input)
    if not text:
        return None
    machine = machine if machine is not None else Machine()
    for rule in RULES:
        answer = rule(text, machine)
        if answer is not None:
            return answer
    return None
