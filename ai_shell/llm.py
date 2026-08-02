"""Talks to the local model: turns plain English into a command + risk classification.

The reasoning rules below are the same everywhere; the shell they're written
for isn't. Anything OS-shaped - the shell's name, how a listing is written,
the worked examples, how an app is launched - comes from ai_shell.platforms,
so the same rules produce PowerShell on Windows and bash elsewhere.
"""

import json
import re
import time

from openai import APIStatusError

from ai_shell import config, fit
from ai_shell.platforms import current

_RULES = f"""You are a command translator for a {current.OS_NAME} AI shell.
The user will describe what they want in plain English. Your job:

1. Translate their request into a single real {current.SHELL_NAME} command (or a short
   {current.SHELL_NAME} script if needed) that accomplishes it on {current.OS_NAME}.
2. Classify the command as "safe" or "risky".
   - "risky" = anything that deletes, overwrites, moves files irreversibly,
     changes system settings, installs/uninstalls software, formats drives,
     changes what starts up with the machine, kills processes, or does
     anything hard to undo.
   - "safe" = read-only or easily reversible actions (listing files, reading
     content, checking status, creating new files/folders, printing info).
3. Not every message is a request. A greeting, a thank-you, or a question
   about you ("hey", "thanks", "who are you") is small talk: reply to it the
   way a person would in "explanation", with "command", "search" and "options"
   all null. Never turn small talk into a task, and never offer choices for it -
   the user asked for nothing, so there is nothing to choose between. A real
   request that is unclear or doesn't map to a shell command likewise gets
   "command" null with your answer or clarification in "explanation".
4. The command's output is shown to the user as the answer, so it must be
   readable on its own. Never produce a bare true/false as the result.
   It must also always print something. A command that prints nothing when the
   answer is "no", or when what it looked for isn't there, leaves the user
   staring at a blank result for a question they asked - which is worse than
   an error, because it looks like it worked. Write the command so every
   outcome prints a sentence: test the thing, then print what you found either
   way. Query a state the plain way rather than digging a value out of a
   registry path that may not exist.
   A bare status word is not an answer either. Asked "is bluetooth on", a
   command that prints "Running" has handed the user a piece of a status
   table and left them to work out what it means. Print "Bluetooth is on."
   The user asked a question in words and the answer has to come back in
   words.
   {current.LISTING_RULE}
5. Messages beginning "(context from the shell, not the user)" are results
   from commands that already ran - never answer them as if the user wrote
   them. They carry the real folder and the real names, so use them: a
   follow-up like "now zip that", "open the second one" or "delete it" refers
   to what those notes describe. Reuse the exact full paths they give instead
   of writing a bare name or guessing a new location. They are background,
   never a pending question: a new message that doesn't refer back to them is
   answered on its own, and an earlier result is never a reason to ask the
   user to pick something from it.
6. Only act when you are sure what the user means. If the user asks for
   something and the request names a category or leaves the target open
   ("open a browser", "play some music", "delete the file") instead of a
   specific app, file, or folder, do NOT pick one yourself - set "command" to
   null, ask which one they mean in "explanation", and list the 2-4 most
   likely specific choices in "options". Ask only about what the user is
   actually asking for right now. The interface adds its own "Other" choice
   automatically, so never include one. Never silently substitute something
   you weren't asked for.
   If the user already named the thing, it is not open and you must not ask.
   "toggle bluetooth", "open notepad", "restart the print spooler" each name
   exactly one thing; asking which one they meant reads as not having
   listened, and it makes the user pick before you do the work anyway.
   And never invent choices that describe this computer. You cannot see what
   is installed or plugged into it - see item 10 - so offering "Bluetooth
   Adapter 1" and "Bluetooth Adapter 2" is offering two things you made up,
   and a user who picks one has told you nothing you can act on. Choices may
   name well-known applications and websites. They may never name hardware,
   devices, drives, network connections, accounts or files, because those are
   facts about this machine and you have not been shown any of them. If you
   genuinely need to know which of something there is, that is a command that
   lists them, not a question.
7. You cannot see the internet, and what you were taught is out of date. When
   the answer has to be looked up out there - news, prices, versions, sports
   results, what something is, who someone is, what a product costs - put a
   short search query in "search", leave "command" null, and say in
   "explanation" that you're looking it up. The shell runs that search and
   reads the results back to the user, so this is a real thing you can do:
   never say you are unable to search, and never answer a looking-up question
   from memory. "search" is for the world beyond this computer - questions
   about THIS machine's own files, settings or hardware are shell commands,
   not searches.
8. "search" answers a question. It never carries out an action. Opening a
   website, or something on a website, is an action and so it is a command:
   "open youtube", "play X on youtube", "look up Y on wikipedia" all mean open
   a web address in the browser. Write the address yourself - the site's own
   search address with the user's words in it - and open it exactly the way
   you would open a file. Never answer one of these by telling the user how
   they could search for it themselves; not having to is the point of this
   shell.
9. Write "explanation" as the one doing it, never as a description of the
   command from outside. "Launches Firefox." and "This will delete the file."
   are both wrong - nobody else is here, the user asked you, so say what you
   are doing.
   Which tense depends on what happens next, and the two are not the same:
   - "safe", and any search: it runs the moment this sentence is shown, so it
     is already running. Present tense, no "I": "Launching Firefox.",
     "Listing the folders on your desktop.", "Looking that up on the web."
   - "risky": the user is asked to confirm it first and may say no, so it is
     NOT happening yet. Future, with "I": "I'll permanently delete
     old_notes.txt.", "I'll overwrite notes.txt."
   Saying "Deleting old_notes.txt." above a confirmation prompt tells the user
   their file is already gone when nothing has happened at all.
10. You cannot see this computer. Nothing tells you what is open, what is
   running, what is installed, what is plugged in, or what a setting is
   currently set to, and the notes described in item 5 say only what a command
   did, not what is true now. So never answer as though you had looked:
   "Bluetooth is already on", "that's already open", "there's no such folder",
   "it's already closed" are guesses, and they are wrong as often as not.
   When the user asks for something, carry the request out anyway. Opening
   something that is already open costs nothing, while refusing on a guess
   means the user asked for something and got nothing at all. If what is true
   right now is genuinely the question, write a command that checks and let
   its output be the answer.
   The same goes for what you have and haven't done: never say you showed,
   told, or already gave the user something. You cannot see the screen either.
   A note saying a command printed nothing means the user was shown nothing -
   so run it again properly rather than insisting the answer was already
   there, and never apologise for confusion instead of answering. If a user
   says you didn't do something, they are looking at the screen and you are
   not. They are right.
"""

# Not an f-string: the shape below is full of braces that mean themselves.
_SHAPE = """
Respond with ONLY a single JSON object and nothing else: no markdown fences,
no preamble, no alternative options, no notes after the JSON, in this exact
shape:

{
  "command": "the shell command, or null",
  "search": "a short web search query - ONLY when the answer has to be looked up on the internet, otherwise null",
  "risk": "safe" or "risky" or null,
  "explanation": "one short sentence describing what this does, or your answer if command is null",
  "options": ["2-4 likely specific choices - ONLY when asking which one the user means, otherwise null"]
}

Never fill in more than one of "command", "search" and "options" at a time.

"""

SYSTEM_PROMPT = _RULES + _SHAPE + current.EXAMPLES + "\n" + current.LAUNCH_NOTE + "\n"


# --- constrained output ----------------------------------------------------
# llama.cpp turns a JSON schema into a grammar and applies it while sampling:
# any token that would break the shape is masked out before the model can pick
# it. Asking for JSON in the prompt is a request a 3B model can decline; this
# is not. Fences, preambles, trailing commentary and truncated objects all stop
# being possible rather than becoming rarer.
#
# The shape is still described in the prompt above. The grammar constrains the
# form, and says nothing about which field means what - a model that doesn't
# know what "risk" is for will emit a valid object full of nonsense.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        # anyOf rather than "type": ["string", "null"] - both are legal JSON
        # Schema, but the union form isn't handled by every converter that
        # accepts the rest of this, and it buys nothing here.
        "command": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        # The shell does the looking-up; this is only the model saying what to
        # look up. A separate field rather than a made-up cmdlet because it is
        # not a shell command and must never reach the shell - the grammar
        # keeps the two apart where a naming convention would only ask nicely.
        "search": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "risk": {"enum": ["safe", "risky", None]},
        "explanation": {"type": "string"},
        "options": {
            "anyOf": [
                {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
                {"type": "null"},
            ]
        },
    },
    # Every key required, so a field is never simply missing: "no options" has
    # to be written as null, which is a thing the parsing side can tell apart
    # from the model having lost track of the shape. The 2-4 bound on options
    # is the prompt's rule made structural - a lone choice isn't a question.
    "required": ["command", "search", "risk", "explanation", "options"],
    "additionalProperties": False,
}

# Wrapped in an object rather than a bare array: a top-level array is valid
# JSON Schema and llama.cpp handles it, but the OpenAI-shaped json_schema
# field is specified around an object root, and an unmanaged server is exactly
# the case where the strictest reading is the safe one.
APPS_SCHEMA = {
    "type": "object",
    "properties": {
        "apps": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["apps"],
    "additionalProperties": False,
}

# Set to False the first time a server rejects response_format, so the cost of
# discovering that is one wasted request per process rather than one per call.
# Not a config setting: the answer belongs to whatever is actually listening,
# which the user shouldn't have to know or declare. Ollama before 0.5 and
# older llama.cpp builds are the realistic cases.
_schema_supported = True


def _complete(client, messages, max_tokens, schema=None, schema_name="response"):
    """A chat completion, constrained to `schema` where the server can do it.

    Falls back to an unconstrained call when the server rejects the request
    outright, which is the difference between an old backend degrading to the
    salvage parsing below and the app simply not working on it. A transport
    failure is not a rejection and is left to propagate - retrying a dead
    connection without the schema would only fail twice and blame the wrong
    thing."""
    global _schema_supported

    request = {
        # Read at call time, not bound at import: the model can change under a
        # running process now that the interfaces can switch it.
        "model": config.MODEL,
        "max_tokens": max_tokens,
        "temperature": 0,
        "messages": messages,
    }
    if not (schema and _schema_supported):
        return client.chat.completions.create(**request)

    try:
        return client.chat.completions.create(
            **request,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        )
    except APIStatusError:
        response = client.chat.completions.create(**request)
        _schema_supported = False  # only after the plain call proves that was the problem
        return response


PICK_APPS_PROMPT = f"""You helped a {current.OS_NAME} AI shell ask the user a clarifying question
about which application they meant. You are now given the list of
applications actually installed on this computer (its {current.APP_SOURCE}).
Pick the installed applications that fit what the user asked about - up to 4,
most likely first. Respond with ONLY a JSON object holding the names copied
EXACTLY from the installed list, e.g. {{"apps": ["Opera GX", "Firefox"]}}. If
nothing on the list fits, respond with {{"apps": []}}."""


def pick_installed_apps(client, user_input, question, installed_names):
    """Grounds clarifying-question choices in what's really installed: the
    model picks up to 4 apps from the list of installed applications, and only
    verbatim matches are kept, so a choice can never name an app that isn't
    there. Returns None if the call fails (caller keeps the generic
    suggestions)."""
    installed_names = installed_names[:150]
    try:
        response = _complete(
            client,
            [
                {"role": "system", "content": PICK_APPS_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"User asked: {user_input}\n"
                        f"Clarifying question: {question}\n"
                        "Installed applications:\n" + "\n".join(installed_names)
                    ),
                },
            ],
            max_tokens=150,
            schema=APPS_SCHEMA,
            schema_name="installed_apps",
        )
        data = _first_json(response.choices[0].message.content.strip())
    except Exception:
        return None
    # Both shapes are accepted because both can arrive: the object is what the
    # schema asks for, and the bare array is what an unconstrained server does
    # with a prompt that shows one.
    if isinstance(data, dict):
        data = data.get("apps")
    if not isinstance(data, list):
        return None
    by_lower = {n.lower(): n for n in installed_names}
    picks = []
    for item in data:
        if isinstance(item, str):
            name = by_lower.get(item.strip().lower())
            if name and name not in picks:
                picks.append(name)
    return picks[:4]


EXPLAIN_FAILURE_PROMPT = f"""You are the voice of an AI shell used by non-technical people.
The user asked for something and the action failed. Tell the user in ONE short
plain sentence why you couldn't do it. Write it in the first person - you are
the one who tried. Talk about the real-world cause, not the mechanics: never
mention {current.JARGON}.
Use ONLY what the error actually says. If the error does not say why it
failed, say that plainly - "I couldn't do that, and the error doesn't say
why." - rather than offering the most likely reason. A reason you supplied
yourself is a guess, the user cannot tell it apart from a real one, and it
will sometimes contradict what this shell showed them a moment ago. Never
state anything about what is or isn't installed, running, open or present
unless the error text says so in as many words.
Good examples:
- "I couldn't open that browser - it doesn't seem to be installed on this computer."
- "I couldn't create the folder - one with that name already exists."
- "I couldn't delete the file - it's currently in use by another program."
Respond with only that one sentence, nothing else."""

# Errors that mean exactly one thing, read here rather than described to the
# model. Asked to explain "Cannot open bthserv service on computer '.'" - which
# is what Windows says when you are not an administrator - the model answered
# "the service is not running" three times out of three, one turn after this
# same shell had printed "Running" for that service. The text gives it nothing
# to work from, so it reaches for the most ordinary reason a stop might fail
# and states it as fact.
#
# Only errors with a single unambiguous meaning belong here. Everything else
# is still the model's, which is the right split: this is a short list of
# certainties, not a second attempt at the long tail.
_KNOWN_ERRORS = (
    (re.compile(r"requires elevation|run (?:this|it) as administrator|"
                r"administrator privileges|access is denied|"
                r"cannot open \S+ service on computer", re.I),
     "I couldn't do that - it needs administrator rights."),
    (re.compile(r"permission denied|operation not permitted", re.I),
     "I couldn't do that - I don't have permission to touch that."),
)


def _known_reason(error_text):
    """The plain-English cause for an error that has only one, or None."""
    for pattern, sentence in _KNOWN_ERRORS:
        if pattern.search(error_text or ""):
            return sentence
    return None


def explain_failure(client, user_input, command, error_text):
    """One plain-English sentence for why the user's request failed. Falls
    back to a cleaned-up first error line if the model call itself fails.

    Errors that mean one thing are answered from _KNOWN_ERRORS without asking
    the model at all - see the note there. It's the same bargain the rest of
    this app makes: where the answer is a fact, a table beats a 3B every time,
    and here it also beats it at not contradicting the previous turn.
    """
    known = _known_reason(error_text)
    if known:
        return known
    try:
        # No schema: the answer is one plain sentence, and there is no shape to
        # hold it to that "respond with only that sentence" doesn't already say.
        response = _complete(
            client,
            [
                {"role": "system", "content": EXPLAIN_FAILURE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"User asked: {user_input}\n"
                        f"What was tried: {command}\n"
                        f"Error output:\n{(error_text or '').strip()[:2000] or '(no error text)'}"
                    ),
                },
            ],
            max_tokens=100,
        )
        sentence = response.choices[0].message.content.strip()
        if sentence:
            return sentence
    except Exception:
        pass
    return _fallback_reason(error_text)


# The answer and its sources as two fields rather than prose with [1] markers
# buried in it, and the array bounded rather than merely discouraged.
#
# Asking in words did not work. With the citation rules written out as
# instructions - including an explicit "listing every result is the same as
# citing none" - this model answered "Reykjavík is the capital of Iceland
# [1][2][3][4][5]", and cited nothing at all on another question. Temperature
# is 0, so those were not unlucky samples; the wording simply had no purchase.
#
# maxItems is a different kind of thing from a rule: the server compiles this
# schema to a grammar and decoding cannot leave it, so "at most two" holds
# without the model's cooperation. minItems does the same for the answer that
# cited nothing. Same trick as options in RESPONSE_SCHEMA - the prompt's rule
# made structural.
WEB_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2},
    },
    "required": ["answer", "sources"],
    "additionalProperties": False,
}

ANSWER_FROM_SEARCH_PROMPT = """You are the voice of an AI shell used by non-technical people.
The user asked something you couldn't know, so the shell searched the web,
opened the pages it found, and put them below. Each numbered result is a title,
its web address, and then its text: usually the beginning of the page itself,
sometimes only the one-line summary the search engine gave.

Reply with JSON: {"answer": ..., "sources": ...}

"answer": the question answered in one to three short plain sentences, using
ONLY what the results say.
- Don't put [1] markers in here. The sources field carries that.
- The page text is the top of a page, so it can stop mid-sentence and can carry
  leftover menu words. Read past those and use what's actually there.
- Don't join facts that weren't joined. If one result gives a version number and
  another gives a date, don't attach that date to that version unless a result
  actually says so.
- Not everything in a page is about the question. Take the part that answers it
  and leave the rest - don't summarise the page.
- If the results don't actually answer the question, say so plainly instead of
  guessing. "The results don't say" is a good answer; an invented one is not.
- If the results disagree, say what each one claims rather than picking.
- No preamble like "Based on the search results", and don't repeat the titles.

"sources": the numbers of the results you actually took the answer from, best
first. One is normal. Give a second only when the answer genuinely needed it.
Not every result that happens to mention the subject - the number you would
give someone who asked "where did you get that?"."""


# What counts as a fact worth checking a source against: a run of digits, or a
# capitalised word. Between them they cover the two things a factual answer is
# actually made of - the numbers (8,848.86 metres, 1889, 28) and the names
# (Reykjavík, Frank Herbert) - while ignoring the connective prose that every
# page shares with every other and which therefore proves nothing.
_NUMBER = re.compile(r"\d[\d,.]*")
_NAME = re.compile(r"\b[^\W\d_][\w'’-]{3,}", re.UNICODE)


# Dates get checked separately from every other figure, because they are the
# one kind of fact this model assembles out of parts. Asked for Python's latest
# version it answered "3.14.6, released on October 7, 2026" - a date that is
# nowhere in the results, built from another release's day and month and a year
# taken from somewhere else again. Every piece of it appears in the sources, so
# nothing token-level notices; only the whole date is invented.
_MONTHS = ("january february march april may june july august september "
           "october november december").split()
_ABBR = [month[:3] for month in _MONTHS]
# Longest first so "june" is preferred over "jun" and the (?![a-z]) guard
# below then rejects the rest of a word rather than the regex settling for a
# three-letter prefix. "sept" is the one abbreviation that isn't three letters.
_MONTH = "|".join(sorted(_MONTHS + _ABBR + ["sept"], key=len, reverse=True))

# The boundaries are deliberately not \b, and this is the whole reason dates
# from a release table were invisible. Stripping the tags out of a table runs
# its cells together, so python.org's page reads "Python 3.14.6June 10, 2026"
# - and \b finds no boundary between "6" and "J", both being word characters.
# The date the answer was supposed to be checked against therefore never
# parsed, which would have made every correct answer look invented. Asking
# instead that a month not be glued to *letters* keeps "Junction 10, 2026" out
# while letting the table in.
_NOT_LETTER_BEFORE = r"(?<![A-Za-z])"
_MONTH_TOKEN = "(" + _MONTH + r")(?![a-z])\.?"
_YEAR = r"(\d{4})(?!\d)"
_DATE_MDY = re.compile(_NOT_LETTER_BEFORE + _MONTH_TOKEN + r"\s*(\d{1,2})(?:st|nd|rd|th)?,?\s*" + _YEAR, re.I)
_DATE_DMY = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH_TOKEN + r",?\s*" + _YEAR, re.I)
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")


def _dates(text):
    """Every complete date in `text`, as (month, day, year).

    Both sides of the comparison go through this, which is the whole point.
    The obvious cheaper test - look for the day and the year somewhere near
    the month name - was measured and is useless here: a release table packs
    dozens of dates into a few hundred characters, so almost any combination
    finds a match, and it waved through the very date that prompted this. It
    accepted 21 of 64 deliberately corrupted dates. Parsing the source the
    same way the answer is parsed takes proximity out of the question, and got
    all 41 real dates right with nothing falsely accepted.
    """
    found = set()
    for match in _DATE_MDY.finditer(text or ""):
        found.add((_ABBR.index(match.group(1)[:3].lower()) + 1, int(match.group(2)), int(match.group(3))))
    for match in _DATE_DMY.finditer(text or ""):
        found.add((_ABBR.index(match.group(2)[:3].lower()) + 1, int(match.group(1)), int(match.group(3))))
    for match in _DATE_ISO.finditer(text or ""):
        month, day = int(match.group(2)), int(match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            found.add((month, day, int(match.group(1))))
    return found


def _invented_dates(answer, texts):
    """Dates the answer states that no result does, worst-first for reporting.

    Catches a date built out of nothing. It does NOT catch a real date bolted
    onto the wrong subject - "3.14.6, released on October 7, 2025", where that
    day genuinely is in the results as a different release's. Checking the
    pairing was tried and abandoned: matching a date against the subject next
    to it in the sentence got six of eight test answers wrong, and wrong in
    the direction that matters, passing the misattributed date while rejecting
    four answers that were correct. A check that suppresses good answers to
    catch one bad one is worse than the bug.
    """
    stated = _dates(answer)
    if not stated or not any(texts):
        return []
    known = set()
    for text in texts:
        known |= _dates(text)
    return sorted(stated - known)


def _spell_date(date):
    month, day, year = date
    return f"{_MONTHS[month - 1].capitalize()} {day}, {year}"


def _claims(text):
    """The checkable tokens in `text` as (numbers, names), normalised so the
    same fact written two ways still matches: 8,848.86 and 8848.86 both reduce
    to their digits, and names are compared without case.

    Kept apart because they are not equally good evidence, and conflating them
    is what made the first attempt at this useless. Every page returned for a
    question about Baku says "Baku"; only the page the figure came from says
    "28". A name shows a result is on the right subject. A number is the thing
    the user would be checking.
    """
    numbers, names = set(), set()
    for match in _NUMBER.findall(text or ""):
        digits = re.sub(r"\D", "", match)
        # Single digits are in every page ever written; they'd match anything.
        if len(digits) >= 2:
            numbers.add(digits)
    for match in _NAME.findall(text or ""):
        if match[:1].isupper():
            names.add(match.lower())
    return numbers, names


def _support(answer, texts):
    """How well each result backs up `answer`, as [(numbers, names)] in result
    order - how many of the answer's figures it contains, and how many of its
    names."""
    numbers, names = _claims(answer)
    scores = []
    for text in texts:
        text_numbers, text_names = _claims(text)
        scores.append((len(numbers & text_numbers), len(names & text_names)))
    return scores


def _citations(sources, answer, texts):
    """`sources` as the "[1][2]" a reader can act on - validated for shape, and
    then checked against what the results actually say.

    Two separate problems, because the grammar only solves the first. A schema
    guarantees "an integer", so a 7 among five results is entirely possible and
    would point at nothing; those are dropped rather than clamped, since a
    citation nudged onto a neighbouring result is a citation that lies.

    The second problem is that a well-formed citation can still be false. Asked
    about the weather this model answered "around 28°C ... winds up to 38km/h"
    and cited two pages whose text contains neither number - they were the
    top-ranked results and they were about Baku, which is evidently enough to
    look right. So a pick is kept only if the result it names shares something
    checkable with the answer, and the empty slots are filled from the results
    that do.

    Deliberately conservative in the one case that matters: when nothing
    supports the answer, the model's own choice is returned untouched. An
    answer with no support anywhere is a bad sign about the answer, not
    evidence about which source to blame, and silently repointing a citation
    on that basis would be inventing a provenance rather than checking one.
    """
    if not isinstance(sources, list):
        sources = []
    count = len(texts)
    picked = []
    for value in sources:
        # bool is an int in Python, and True would render as [1].
        if type(value) is int and 1 <= value <= count and value not in picked:
            picked.append(value)
    picked = picked[:2]

    scores = _support(answer, texts)
    if not any(any(score) for score in scores):
        # Nothing anywhere shares anything checkable with the answer. See the
        # docstring: that says something about the answer, not about which
        # result to name, so the model's own choice stands.
        return "".join(f"[{number}]" for number in picked)

    # When the answer states figures and some result actually contains them,
    # naming a result that doesn't is the failure this exists to catch - being
    # about the right subject is not the same as being where the number came
    # from. With no figures in play, sharing names is the only evidence there
    # is and is enough.
    best_figures = max(figures for figures, _ in scores)

    def backs_it_up(number):
        figures, names = scores[number - 1]
        return (figures > 0 or best_figures == 0) and (figures or names)

    kept = [number for number in picked if backs_it_up(number)]
    if not kept:
        # Every pick was unsupported, so rather than repeat one, name the
        # result that does support the answer. One, not two: the second slot
        # exists for a model that genuinely drew on two sources, and filling
        # it here would be manufacturing agreement.
        candidates = sorted(
            (n for n in range(1, count + 1) if backs_it_up(n)),
            key=lambda n: (-scores[n - 1][0], -scores[n - 1][1], n),
        )
        kept = candidates[:1]

    return "".join(f"[{number}]" for number in kept)


def answer_from_search(client, question, results_block, texts):
    """One plain-English answer to `question`, read out of `results_block`,
    with the numbers of the results it came from appended.

    `texts` is what each result actually said, in the order they're numbered -
    the same material the block was built from. It's what a citation is checked
    against, and its length is what makes a made-up result number obvious.

    Returns None when the model can't be reached or says nothing - the caller
    then shows the results by themselves, which is a worse answer but never a
    wrong one.

    The citations land at the end of the answer rather than after the sentence
    each one supports, which is a real loss of precision and a deliberate
    trade. Sentence-level citing is what the prose version was asked for, and
    what it did instead was cite all five results or none at all. Attribution
    that's coarse and correct beats attribution that's fine-grained and
    meaningless.

    An answer that states a date no result contains is sent back once with the
    date named, and that works: on four planted fabrications the model dropped
    the invented date or replaced it with the real one every time. If the
    second attempt is still making dates up, this gives up and returns None
    rather than choosing between two answers it has reason to distrust - the
    sources go up without a summary, which is the same bargain the rest of
    this function makes.
    """
    messages = [
        {"role": "system", "content": ANSWER_FROM_SEARCH_PROMPT},
        {"role": "user", "content": f"Question: {question}\n\nSearch results:\n{results_block}"},
    ]

    first = _one_answer(client, messages)
    if first is None:
        return None
    answer, sources, raw, structured = first
    if structured and not answer:
        return None

    if answer:
        invented = _invented_dates(answer, texts)
        if invented:
            named = " and ".join(_spell_date(date) for date in invented)
            second = _one_answer(client, messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    f"{named} does not appear anywhere in the results. Answer again "
                    f"using only a date the results actually give, or leave the date "
                    f"out entirely."
                )},
            ])
            if second is None or not second[0]:
                return None
            answer, sources = second[0], second[1]
            if _invented_dates(answer, texts):
                return None

    if not answer:
        # No JSON in the reply, so the schema wasn't applied - an older
        # llama.cpp or an Ollama before 0.5, where _complete has already
        # fallen back to an unconstrained call. The prompt still asked for an
        # answer and the model still wrote one, so it's shown as it came:
        # uncited, or cited however the model felt like. That's this feature's
        # previous behaviour, which is the right thing for a server that can't
        # do better, and it's why the checks above are allowed to depend on a
        # grammar at all.
        return raw or None

    return f"{answer} {_citations(sources, answer, texts)}".strip()


def _one_answer(client, messages):
    """One round-trip, as (answer, sources, raw_reply, structured).

    `structured` says whether the reply actually parsed as the object asked
    for. It's the difference between a server that ignored the schema - whose
    prose is still worth showing - and one that obeyed it and returned an
    empty answer, which is nothing to show at all. Returns None outright only
    when the model couldn't be reached.
    """
    try:
        response = _complete(
            client, messages, max_tokens=300,
            schema=WEB_ANSWER_SCHEMA, schema_name="web_answer",
        )
        raw = response.choices[0].message.content.strip()
    except Exception:
        return None

    cleaned = raw.replace("```json", "").replace("```", "").strip()
    data = _first_json(cleaned)
    if not isinstance(data, dict) and "{" in cleaned:
        # _first_json decodes from the start, so it forgives commentary after
        # the JSON but not before it. Unreachable when the grammar applied,
        # and quite likely when it didn't: a model asked for JSON and left to
        # its own devices opens with "Sure!". Without this the whole raw
        # object is shown to the user as though it were the answer.
        data = _first_json(cleaned[cleaned.index("{"):])
    if isinstance(data, dict) and isinstance(data.get("answer"), str):
        return " ".join(data["answer"].split()), data.get("sources"), raw, True
    return "", None, raw, False


def _fallback_reason(error_text):
    for line in (error_text or "").splitlines():
        line = line.strip()
        if line:
            return f"I couldn't do that: {current.strip_error_prefix(line)}"
    return "I couldn't do that - it failed without giving a reason."


def ask_model(client, user_input, history):
    """(data, rate) - the model's answer, and how fast it wrote it.

    The rate is tokens a second, measured here rather than read out of
    llama.cpp's log: a user who pointed AI_SHELL_BASE_URL at Ollama or at their
    own server has no log of ours to read, and llama.cpp's format is its own
    business and has changed. None whenever it can't be measured honestly - a
    backend that reports no usage, or a reply too short to time.

    Only this call is measured. The app's other model calls happen while the
    user is reading something; this is the one they sit and wait for.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": user_input}]
    started = time.monotonic()
    response = _complete(
        client, messages, max_tokens=500, schema=RESPONSE_SCHEMA, schema_name="shell_command"
    )
    elapsed = time.monotonic() - started
    rate = _rate(response, elapsed)
    text = response.choices[0].message.content.strip()
    # Fences and salvage parsing are dead weight against a server that applied
    # the schema, and the only thing standing up an answer from one that
    # didn't. Both paths reach this code, and it can't tell which it is on.
    text = text.replace("```json", "").replace("```", "").strip()
    data = _first_json(text)
    if not isinstance(data, dict):
        return {
            "command": None,
            "risk": None,
            "explanation": "Sorry - I got a garbled answer from the model. Try asking again, maybe with different wording.",
        }, rate
    if isinstance(data.get("command"), str):
        data["command"] = _restore_path_escapes(data["command"])
    return data, rate


def _rate(response, elapsed):
    """Tokens a second, or None when there's nothing honest to report.

    A short reply is dominated by the round-trip rather than the model, and a
    backend that reports no usage gives nothing to divide - both are reasons
    to say nothing rather than to publish a number that means something else.
    """
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "completion_tokens", None) if usage else None
    if not tokens or tokens < fit.MIN_TIMED_TOKENS or elapsed <= 0:
        return None
    return tokens / elapsed


# Control characters a swallowed backslash turns into, and the text they were
# written as.
#
# A grammar guarantees valid JSON, not the JSON that was meant, and this is
# where the two come apart. Asked for C:\temp, an unconstrained model writes
# "C:\temp" and the invalid escape breaks the parse loudly. A constrained one
# cannot write that - but \t IS a legal escape, so the sampler is free to emit
# it, and the parse then succeeds with a tab where the separator should be.
# The failure stops being a garbled answer and becomes a command quietly
# aimed at the wrong place, which is the worse of the two.
_SWALLOWED_ESCAPES = {"\t": r"\t", "\n": r"\n", "\r": r"\r", "\b": r"\b", "\f": r"\f"}


def _restore_path_escapes(command):
    """Backslashes the JSON layer ate, put back - inside quotes only.

    Which is the whole difficulty: "C:\\temp\\notes" and a two-line script
    arrive as the same characters, and undoing all of them breaks every script
    the prompt explicitly allows while undoing none of them corrupts every
    path with an unlucky next letter. Neither is rare enough to accept.

    Quoting separates them, because the two are never written in the same
    place. A path is an argument, and this shell's commands quote their
    arguments - the platform's own quote() does, the worked examples in the
    prompt do. A script's line breaks are structure, and structure lives
    outside the quotes by definition: between statements, after a brace,
    around a pipeline. So a control character inside a quoted span was a path
    separator, and one outside it was a line the model meant to break.

    The remaining error is a deliberate literal tab or newline inside a quoted
    string - Write-Output "a\\tb" - which comes back as the text \\t. Rare
    enough to trade for paths and scripts both working.
    """
    if not current.REPAIR_JSON_BACKSLASHES:
        return command

    out, quote = [], None
    for char in command:
        if quote:
            if char == quote:
                quote = None
            elif char in _SWALLOWED_ESCAPES:
                out.append(_SWALLOWED_ESCAPES[char])
                continue
        elif char in "'\"":
            quote = char
        out.append(char)
    return "".join(out)


# A valid two-char escape or \uXXXX, or (the alternative) a lone backslash.
_STRAY_BACKSLASH = re.compile(r'\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})|\\')


def _double_stray_backslashes(text):
    """Local models routinely paste Windows paths straight into the JSON
    ($env:USERPROFILE\\Desktop, C:\\temp), where \\D is an invalid escape that
    kills the whole parse. Doubling every backslash that isn't already a valid
    JSON escape makes those survive as the path characters they were meant to
    be.

    Every escape JSON defines counts as valid here, including \\n and \\t. That
    is deliberate, and it is the half of the problem this function does not
    try to solve: a model writing a real multi-line script and a model writing
    C:\\temp produce the same three characters, and nothing at this level can
    tell them apart. Guessing "path" mangles every script the prompt
    explicitly allows the model to write; guessing "escape" costs a tab, which
    _restore_path_escapes puts back afterwards. So the ambiguous ones are left
    to decode normally and repaired on the far side, and only escapes JSON
    doesn't have - \\D, \\U, \\P - are treated as the literal backslashes they
    can only have been."""
    return _STRAY_BACKSLASH.sub(lambda m: m.group(0) if len(m.group(0)) > 1 else "\\\\", text)


def _first_json(text):
    """Parses the first JSON value in text (models sometimes add commentary
    after it). Returns None if nothing parses.

    Both readings are tried; which one is preferred is the platform's call,
    because the repair above is only worth its risk where paths are written
    with backslashes. Where they aren't, a backslash in the JSON is far more
    likely to be an escape the model actually meant."""
    candidates = (_double_stray_backslashes(text), text)
    if not current.REPAIR_JSON_BACKSLASHES:
        candidates = tuple(reversed(candidates))
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            data, _ = decoder.raw_decode(candidate)
            return data
        except json.JSONDecodeError:
            continue
    return None
