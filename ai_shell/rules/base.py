"""What a rule says, and the tidying every rule would otherwise redo.

A rule's job is to recognise what the user meant. Saying it in the shape the
rest of the app speaks is a different job, and it belongs here rather than in
each rule, for one reason: the shape changes and the rules don't. When "risk"
grows a third value, or a reason string, or stops being a dict at all, the
edit is Answer.as_data and nothing else. A rule that built that dict itself
would be a rule to find and fix every time.

So a rule returns an Answer - "run this", "ask this", "look this up" - and
never a field name.

The rest of this module is the work every rule needs before it can match
anything: politeness stripped off the front, whitespace and punctuation
normalised, and the standard reasons to hand a request back to the model
untouched. Written once so a new rule inherits them, rather than each one
re-deriving them slightly differently.
"""

import re

from ai_shell.platforms import current


class Answer:
    """A rule's decision, before it's turned into anything the shell speaks.

    Built through the helpers below rather than directly - `run`, `open_url`,
    `look_up`, `ask`, `say` - so that a rule names what it wants to happen and
    never the field that carries it.
    """

    def __init__(self, explanation, command=None, query=None, options=None, risk="safe"):
        self.explanation = explanation
        self.command = command
        self.query = query
        self.options = options
        self.risk = risk

    def as_data(self):
        """The Answer as the dict translate() hands to the interfaces.

        The one place in the rules that knows those field names. Note what
        isn't decided here: `risk` is what the rule believes, and
        ai_shell.policy still reads the finished command afterwards and can
        overrule it upwards. A rule cannot talk its way down from risky.
        """
        return {
            "command": self.command,
            "search": self.query,
            "risk": self.risk if self.command else None,
            "explanation": self.explanation,
            "options": self.options,
        }


def run(command, explanation, risk="safe"):
    """Run a shell command.

    The explanation's tense follows the risk, because the two describe
    different moments. A safe command runs as its sentence appears, so it is
    already happening: "Listing the folders on your desktop." A risky one
    stops to be confirmed and may be skipped, so it isn't happening yet:
    "I'll permanently delete old_notes.txt." Saying the second in the first's
    tense tells the user their file is gone while it is still there.
    """
    return Answer(explanation, command=command, risk=risk)


def open_url(url, explanation):
    """Open a web address in the user's browser.

    Goes through the platform's own open_command, which is the same thing a
    click on a search result uses - so a rule doesn't have to know that this
    is Start-Process on Windows and xdg-open on Linux.
    """
    return Answer(explanation, command=current.open_command(url))


def look_up(query, explanation):
    """Search the web and read the results back."""
    return Answer(explanation, query=query)


def ask(question, options):
    """Ask the user which of `options` they meant."""
    return Answer(question, options=list(options))


def say(explanation):
    """Answer in words, with nothing to run."""
    return Answer(explanation)


class Machine:
    """What a rule is allowed to ask about this computer.

    A rule needs to know things like whether Spotify is installed, and giving
    it the Session to find out would tie every rule to the whole app. This is
    the narrow version of that: one object, passed in, with the questions a
    rule may ask.

    `apps` is a callable rather than a list because scanning the Start Menu
    takes long enough to notice, and most requests never ask. Nothing is
    scanned until a rule actually wants to know.
    """

    def __init__(self, apps=tuple):
        self._apps = apps

    def has_app(self, name):
        """Whether an installed application is called exactly `name`.

        Exact, not "contains". Google Chrome would otherwise count as Google,
        and "open google" would launch a browser at whatever its home page is
        instead of the search page the user asked for.
        """
        wanted = name.lower()
        return any(installed.lower() == wanted for installed, _ in self._apps() or ())


# --- tidying up what the user typed -----------------------------------------

# Softeners in front of the verb, which change nothing about the request.
_POLITE = re.compile(
    r"^(?:please|can you|could you|would you|will you|hey|hi|i want to|"
    r"i wanna|i'd like to|id like to|let's|lets)[,\s]+", re.I)

# Wh-questions, and the auxiliaries a yes/no question opens with. Both kinds
# matter and for two different reasons: the rules use this to bow out of
# anything that wants an explanation rather than an action, and the session
# uses it to notice that a question came back with no answer in it.
_QUESTION = re.compile(
    r"^(?:how|what|why|which|who|whose|when|where"
    r"|is|are|was|were|am|do|does|did|can|could|should|would|will|has|have|had)\b",
    re.I)

# Words that only mean something in the conversation - which the rules cannot
# see. "open it on youtube" refers back to something further up; the model has
# the history and a rule doesn't, so the model should be the one to answer.
_REFERS_BACK = frozenset((
    "it", "that", "this", "them", "those", "these", "one", "the one",
    "him", "her", "us", "me", "something", "some", "anything", "stuff",
))

# A path, not a phrase. Any of these says the user is talking about something
# on this machine.
_PATHISH = re.compile(r"[\\/:~*?\"<>|]")

# A filename, for the same reason. Spelled out rather than "a dot and up to
# four letters", which would reject "st. louis".
_FILE = re.compile(
    r"\.(?:pdf|txt|md|docx?|xlsx?|pptx?|csv|jpe?g|png|gif|webp|svg|mp[34]|mkv|"
    r"mov|wav|zip|rar|7z|tar|gz|exe|msi|dmg|iso|py|js|ts|json|ya?ml|html?|css|"
    r"log|bak|tmp)$", re.I)

# Long enough for a film title, short enough that a whole sentence about a
# file doesn't sail through as something to search for.
_MAX_WORDS = 12
_MAX_CHARS = 80


def clean(user_input):
    """`user_input` with the noise taken off, or "" if there's nothing left.

    Only the parts that are safe for every rule: collapsed whitespace, no
    politeness prefix, no trailing punctuation. Deliberately not the question
    check - a future rule about disk space wants "how much free space do I
    have", so that one is offered below for rules to apply themselves rather
    than imposed on all of them here.
    """
    return _strip_politeness(" ".join((user_input or "").split())).strip(" .!?,")


def _strip_politeness(text):
    """Every softener off the front, however many were stacked: "hey can you
    open youtube" is the same request as "open youtube"."""
    while True:
        stripped = _POLITE.sub("", text)
        if stripped == text:
            return text
        text = stripped


def is_question(text):
    """Whether `text` asks about something rather than asking for it.

    "how do i open eminem on youtube" wants an explanation, and explanations
    are the model's job. "is bluetooth on" wants a fact, and a command that
    answers it has to print one.

    A trailing question mark counts on its own, for the follow-ups that carry
    no opener at all: "so is it?" is a question by punctuation and nothing
    else.
    """
    text = (text or "").strip()
    return text.endswith("?") or bool(_QUESTION.match(text))


def asks_a_question(user_input):
    """Whether `user_input` wants a fact back, rather than something done.

    Not the same test as is_question, because of how people are polite. "Can
    you toggle bluetooth" opens with an interrogative and is an instruction;
    the question mark people put on the end of it is politeness too. Reading
    it as a question told a user that opening their Bluetooth settings "hasn't
    answered the question", when nothing had been asked.

    What separates them is whether the opener survives the softener coming
    off. "Can you toggle bluetooth" becomes "toggle bluetooth" and is plainly
    an order. "Can I write to that drive" keeps its "can", because "can I" is
    the user's own words rather than a way of saying please.
    """
    text = " ".join((user_input or "").split())
    softened = _strip_politeness(text)
    if softened != text:
        # A softener came off, so the question mark that may be sitting at the
        # end came off with it - it was punctuation on a request.
        return is_question(softened.strip(" .!?,"))
    return is_question(text.strip(" .!,"))


def refers_back(phrase):
    """Whether `phrase` points at something earlier in the conversation."""
    return phrase.lower() in _REFERS_BACK


def looks_like_a_path(phrase):
    """Whether `phrase` names a file or folder on this machine."""
    return bool(_PATHISH.search(phrase)) or bool(_FILE.search(phrase))


def too_long(phrase):
    """Whether `phrase` is long enough to be a sentence rather than a name."""
    return len(phrase) > _MAX_CHARS or len(phrase.split()) > _MAX_WORDS


def doubtful(phrase):
    """The three checks above together - the usual "hand it back" test.

    Every one of these has been seen in the shape of a real request: a folder
    named after a website, a file being opened in an app, a follow-up
    referring to an earlier result. Falling through to the model costs a
    couple of seconds. Guessing wrong does something the user didn't ask for
    and loses the thing they did.
    """
    return refers_back(phrase) or looks_like_a_path(phrase) or too_long(phrase)
