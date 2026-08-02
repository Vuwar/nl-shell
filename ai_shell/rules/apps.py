"""The operating system's own tools, opened without asking the model.

Two things were wrong with letting the model answer these.

It was inconsistent. "Open registry editor" in a fresh session came back safe
and ran; the same words after a few turns of conversation came back risky and
stopped to ask. Same machine, same model, temperature zero - only the history
above it differed. A confirmation that appears sometimes teaches nothing
except that confirmations are noise.

And it was guessing. These tools are not in the Start Menu index under the
names people call them: nothing there connects "device manager" to
"devmgmt.msc" or "bluetooth settings" to "ms-settings:bluetooth". So the
app-launch fallback, which can only look up the name the command already
gave, has nothing to rescue. A wrong guess is simply a failure.

Both are fixed the same way as the website table: the answer is a fixed
string, so it goes in one - see ai_shell.platforms, where each OS keeps its
own. Ordinary applications stay with the model, which has the Start Menu
behind it and does the job well.
"""

import re

from ai_shell.platforms import current
from ai_shell.rules import base

# Verbs that mean "put it on my screen". Narrower than the website rule's
# list: there is no equivalent of "play X on youtube" here, only opening.
_VERB = r"(?:open|launch|start|run|show|show me|bring up|pull up|go to)"


def _pattern():
    """The match for this platform's tools, longest name first.

    Built on first use rather than at import: current.SYSTEM_APPS is a class
    attribute of whichever platform was selected, and building this at import
    time would freeze whatever the module happened to see first - which is
    exactly what makes a test that switches platform pass alone and fail in a
    suite.
    """
    names = sorted(current.SYSTEM_APPS, key=len, reverse=True)
    if not names:
        return None
    alternation = "|".join(re.escape(name) for name in names)
    return re.compile(rf"^{_VERB}\s+(?:the\s+)?(?P<app>{alternation})$", re.I)


def resolve(text, machine):
    """`text` as one of this OS's own tools, or None if it isn't one."""
    if base.is_question(text):
        return None
    pattern = _pattern()
    if pattern is None:
        return None
    match = pattern.match(text)
    if not match:
        return None
    name, target = current.SYSTEM_APPS[match.group("app").lower()]
    # Present tense: opening one of these changes nothing, so it is safe, so
    # it runs the moment the sentence appears. See ai_shell.rules.base.run.
    return base.run(current.system_app_command(target), f"Opening {name}.")
