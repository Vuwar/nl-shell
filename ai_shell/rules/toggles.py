"""Switches the shell can't flip, answered by opening the page they're on.

"Turn off bluetooth" has no honest command behind it on Windows. The radio is
not a service, so stopping bthserv doesn't switch it off - and can't run
without administrator rights, and fails anyway because other services depend
on it. Disabling the device needs rights too. The actual switch is a WinRT
call, not something a shell runs.

Asked for one regardless, the model did what a model does with a question it
can't answer: it invented. "Which Bluetooth device would you like to toggle?",
offering "Bluetooth Adapter 1" and "Bluetooth Adapter 2" on a machine with one
adapter named neither. Whichever the user picked told it nothing, and what
came back was `Set-Service -Name 'bthserv' -StartupType 'Automatic'` - a
persistent change to a startup type that toggles nothing at all. Telling the
prompt not to invent choices fixed the phrasings around this one and did not
fix this one: "toggle wifi" still offered "Network 1", "Network 2", "Network
3".

So this stops asking the model. Opening the page the switch lives on is one
click from what the user wanted, works with no rights, and is the same answer
every time.

It is not what they asked for, and the explanation says so rather than
implying the switch was flipped. That is the line: substituting something
quietly would be worse than failing, but substituting something openly, when
the honest alternative is a command that cannot work, is the better answer.
"""

import re

from ai_shell.platforms import current
from ai_shell.rules import base

# "turn on bluetooth", "turn bluetooth off", "toggle wifi", "enable dark mode",
# "switch off the camera". The thing can come before or after the on/off,
# because both are ordinary English and neither is rarer than the other.
_STATE = r"(?:on|off|back on|back off)"
_SET_FIRST = r"(?:turn|switch|put|flip)"


def _patterns():
    """Built on first use, for the reason given in ai_shell.rules.apps."""
    names = sorted(current.SETTINGS_TOGGLES, key=len, reverse=True)
    if not names:
        return ()
    things = "|".join(re.escape(name) for name in names)
    return (
        # turn on bluetooth / switch off the camera
        re.compile(rf"^{_SET_FIRST}\s+{_STATE}\s+(?:the\s+)?(?P<thing>{things})$", re.I),
        # turn bluetooth on / put wifi back on
        re.compile(rf"^{_SET_FIRST}\s+(?:the\s+)?(?P<thing>{things})\s+{_STATE}$", re.I),
        # toggle bluetooth / enable dark mode / disable the microphone
        re.compile(rf"^(?:toggle|enable|disable)\s+(?:the\s+)?(?P<thing>{things})$", re.I),
    )


def resolve(text, machine):
    """`text` as a switch this shell can only show the user, or None."""
    if base.is_question(text):
        return None
    for pattern in _patterns():
        match = pattern.match(text)
        if not match:
            continue
        name, page = current.SETTINGS_TOGGLES[match.group("thing").lower()]
        return base.open_url(
            page,
            f"Opening {name} settings, where the switch is - I can't flip it from a command.",
        )
    return None
