"""Shared conversation/command state used by both the CLI and the GUI.

Both interfaces need the same flow: translate the user's request, then either
run it right away (safe) or wait for the interface to confirm (risky) before
running it. Session holds the history and the last translated-but-not-yet-run
command so neither interface has to re-implement that bookkeeping.

It also carries the session's context, which is what makes "now zip that" work.
Three parts, because the model is only responsible for one of them:

  * a note in the history after every command, so the model can see what it
    actually did - otherwise each turn starts blind and it re-guesses paths
    the shell had already resolved;
  * a working folder, so relative paths in a command mean the folder the user
    is looking at rather than wherever the app was launched from;
  * the last listing's rows, so a name the model writes bare can be swapped
    for its real path without the model's cooperation (see
    listing.resolve_listed_paths).
"""

import json
import os
import re
import threading

from openai import OpenAI

from ai_shell import corrections, web
from ai_shell import config, describe, fit, policy, rules, server
from ai_shell.config import API_KEY, BASE_URL
from ai_shell.executor import execute_command, list_apps, run_command
from ai_shell.listing import format_table, listing_parent, resolve_listed_paths
from ai_shell.llm import answer_from_search, ask_model, explain_failure, pick_installed_apps
from ai_shell.platforms import current

_LAUNCHY = re.compile(r"\b(open|launch|start|run|play|use)\b", re.IGNORECASE)

_BOOLEANS = ("true", "false")

# Notes take history slots too, so the window is wider than the 10 exchanges
# the raw conversation needed - and each note is kept short to earn its place.
_HISTORY_LIMIT = 30
_MAX_NOTE_OUTPUT = 300
_MAX_NOTE_NAMES = 25

# A search engine ignores everything past a few words anyway, and a model that
# has decided to paste its whole reasoning in here shouldn't get to send it.
_MAX_QUERY = 200


def _listing_summary(items, kind, parent):
    if not items:
        return "Nothing there." if kind == "item" else f"No {kind}s there."
    names = ", ".join(item["name"] for item in items[:_MAX_NOTE_NAMES])
    if len(items) > _MAX_NOTE_NAMES:
        names += f", and {len(items) - _MAX_NOTE_NAMES} more"
    where = f" in {parent}" if parent else ""
    plural = "" if len(items) == 1 else "s"
    return f"Listed {len(items)} {kind}{plural}{where}: {names}."


# What the user is told, and what the history is told, when a command that was
# supposed to answer something printed nothing at all.
#
# Both are needed, and the second is the one that was actually doing damage.
# "Worked." in the history reads like the check came back positive, so the next
# turn answers "Bluetooth is on." from a note that contains no such thing - and
# the turn after that insists it already said so. Saying plainly that nothing
# came back leaves nothing to read that way.
NO_ANSWER = "That ran, but it printed nothing at all - so it hasn't answered the question."
_NO_ANSWER_NOTE = "Ran, but printed nothing. No answer came back, and none was shown to the user."


def _output_summary(answer):
    if not answer:
        return "Worked."
    text = " ".join(answer.split())
    if len(text) > _MAX_NOTE_OUTPUT:
        text = text[:_MAX_NOTE_OUTPUT] + "…"
    return f"Worked. Output: {text}"


def _clean_search(value):
    """A usable search query out of whatever landed in the field, or None.

    The grammar guarantees a string or null, and nothing more: an empty
    string, a stray "null", or the model's whole explanation can all arrive
    here as valid JSON, and each of them would otherwise become a search the
    user never asked for."""
    if not isinstance(value, str):
        return None
    query = " ".join(value.split())
    if len(query) < 2 or query.lower() in ("null", "none", "n/a"):
        return None
    return query[:_MAX_QUERY]


def _search_summary(answer, results):
    """What a web search leaves in the history: what the user was told, and
    nothing else.

    The sources are deliberately left out, which is not the obvious choice -
    they're the most factual thing the search produced, and putting them in
    would be what makes "open the second one" resolvable. Both readings were
    tried against the model, and the numbered list loses badly on each:

      * The next question stops being routed. With a "[1] ... [2] ..." block
        in the history, "what is the capital of Iceland" comes back as a
        PowerShell command inspecting the system locale instead of a search.
        Without it, the same question searches. Titles alone do it too, so
        it's the list, not the URLs - a numbered list of things reads as data
        to operate on, and the next turn goes looking for a command to
        operate on it with.
      * "Open the second one" is answered by inventing a URL that matches the
        title's brand. A URL the model half-remembers is a URL that opens the
        wrong page, which is worse than not opening one.

    So the sources stay where they're already correct - on screen, clickable
    in the window and printed in the console - and the history carries only
    the sentence, which is enough for the follow-ups that matter: "when was he
    born" resolves the pronoun against it and searches again.
    """
    if answer:
        return "Told the user: " + " ".join(answer.split())[:_MAX_NOTE_OUTPUT]
    count = len(results)
    return f"Showed the user {count} result{'' if count == 1 else 's'} without a summary."


def _boolean_answer(output):
    """Plain "Yes."/"No." for output that is nothing but booleans, or None if
    it's normal output.

    Test-Path prints one bare True/False, and a model asked "is there any
    folder on the desktop?" sometimes reaches for a per-item test instead of a
    filtered listing, printing a whole column of them. Neither is readable -
    but the explanation shown above the output already says what was checked,
    so the answer collapses to yes/no: any True means it was found."""
    lines = [line.strip().lower() for line in output.splitlines() if line.strip()]
    if not lines or not all(line in _BOOLEANS for line in lines):
        return None
    return "Yes." if "true" in lines else "No."


class Session:
    def __init__(self):
        self.client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
        self.history = []
        # {"command": str, "hint": str} once translate() finds a command, or
        # {"search": str, "hint": str} when what it found was a web lookup.
        self._pending = None
        self._last_listing = []  # rows of the most recent listing, for follow-ups about them
        self._context_path = None  # the folder the session is currently "in"
        self._caveat_shown = False  # the small-model warning, said once, not every search
        self._slow_notice_shown = False  # the graphics-card explanation, said once
        # Installed-app scan: kicked off now, in the background, so the result
        # is usually ready by the time the first vague request needs it.
        self._apps = None  # (name, launch_id) pairs
        self._scan_lock = threading.Lock()
        threading.Thread(target=self._scan_apps, daemon=True).start()

    def _scan_apps(self):
        """Returns the cached (name, launch_id) list of installed
        applications, scanning if needed. A failed scan isn't cached, so it
        retries next time."""
        with self._scan_lock:
            if not self._apps:
                self._apps = list_apps()
            return self._apps

    def check_connection(self):
        """Raises if the model server isn't reachable at BASE_URL."""
        self.client.models.list()

    def reset(self):
        """Forgets the conversation: history, the folder in context, the last
        listing's rows and any command still waiting to be confirmed.

        Clearing the screen has to clear this too. Everything above is what
        makes a bare "open it" resolve against an earlier result - so a
        session that outlives the visible output answers the next message
        against a conversation the user can no longer see, which reads as the
        shell inventing a request out of nothing.

        The installed-app scan is deliberately kept: it describes the machine,
        not the conversation, and re-scanning would stall the next request.

        The small-model warning is not kept, for the opposite reason: it's said
        once because repeating it every search would be nagging, not because
        the user only needs it once. Cleared from the screen, it was never
        read - so the next search says it again."""
        self.history = []
        self._pending = None
        self._last_listing = []
        self._context_path = None
        self._caveat_shown = False
        # Same reasoning as the caveat above: a warning cleared off the screen
        # before it was read may as well not have been said.
        self._slow_notice_shown = False

    def translate(self, user_input):
        """Sends user_input to the model, records it in history, and returns
        {"command", "search", "risk", "explanation", "options"}. If a command
        or a search comes back, it's stashed as pending so a later run_last()
        can carry it out."""
        # A request the rules can answer exactly skips the model entirely -
        # see ai_shell.rules. Everything after this point is the same either
        # way, so an answered request still gets classified, recorded in the
        # history and left pending like any other. The rate is None because
        # nothing was generated: there was no model call to time, and
        # reporting a speed for a table lookup would put the graphics-card
        # notice in front of a user whose request never touched the card.
        answered = rules.resolve(user_input, rules.Machine(self._scan_apps))
        try:
            data, rate = (
                (answered.as_data(), None) if answered
                else ask_model(self.client, user_input, self.history)
            )
        except server.ServerError as error:
            # The model server had to be started for this turn and wouldn't
            # start. Reported rather than raised: waking is an ordinary part of
            # a turn now (see ai_shell.idle), and both interfaces already draw
            # a sentence with no command in it. Nothing is left pending,
            # because nothing was translated.
            self._pending = None
            return {
                "command": None,
                "search": None,
                "risk": None,
                "risk_reason": None,
                "explanation": str(error),
                "does": [],
                "options": None,
                "notice": None,
                "error": True,
            }

        command = data.get("command")
        # One job per turn. The prompt says so, but a model that fills in two
        # of these leaves the interfaces deciding which one the user meant -
        # so the decision is made here, once, in the order the fields cost:
        # a command does something, a search only reads, options only ask.
        search = _clean_search(data.get("search")) if not command else None
        data["search"] = search
        if command or search:
            data["options"] = None
        elif data.get("options"):
            grounded = self._grounded_options(user_input, data)
            # None means "no opinion, keep what the model offered". A list is
            # an answer, including an empty one: choices the shell couldn't
            # ground are dropped rather than shown, because a choice that
            # names something which isn't there is worse than no choice at
            # all - the user picks it, and what they picked means nothing.
            if grounded is not None:
                data["options"] = grounded or None

        # The model classified its own output. The rules get the last word,
        # and they only ever say "ask first" - see ai_shell/policy.py for why
        # that asymmetry is the whole point.
        data["risk_reason"] = policy.escalate(command)
        if data["risk_reason"]:
            data["risk"] = "risky"

        # What the command actually does, in plain English, for the
        # confirmation to show above the buttons. Empty for a command nothing
        # can describe, which the interfaces render as they always did.
        data["does"] = describe.describe(command)

        # History is appended after grounding so the model's context matches
        # the choices the user actually saw (and may answer with).
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": json.dumps(data)})
        self.history = self.history[-_HISTORY_LIMIT:]

        if command:
            self._pending = {"command": command, "hint": user_input}
        elif search:
            self._pending = {"search": search, "hint": user_input}
        else:
            self._pending = None

        data["notice"] = self._slow_notice(rate)
        return data

    def claim_notice(self, text):
        """`text` if nothing has explained the graphics card yet this session,
        None if something already has.

        One flag for every route to the same sentence. The startup check and
        the slow-answer check are different code in different modules, and
        without a shared claim each was "said once" on its own terms - which
        the user experiences as being told twice, with two different numbers
        in it.
        """
        if not text or self._slow_notice_shown:
            return None
        self._slow_notice_shown = True
        return text

    def _slow_notice(self, rate):
        """Why that answer took so long, said once per session, or None.

        Free memory is re-read here rather than taken from the reading
        ai_shell.server made at startup - the whole reason this check exists
        alongside that one is that a game started since then changes the
        answer, and a stale number would describe the machine as it was before
        the thing that made it slow.

        What our own model is holding is then subtracted from that reading.
        By the time an answer has been slow the weights are resident, so most
        of what the card reports as "in use" is this app - and reporting that
        back as other programs hogging the card is both wrong and unactionable:
        the user closes things, nothing improves, and the app says it again.
        """
        if self._slow_notice_shown or rate is None or rate >= fit.SLOW_TOKENS_PER_SEC:
            return None
        total = config.HARDWARE.get("vram_gb")
        if not total:
            # No card: this machine is slow by nature, not by contention.
            # There would be nothing to close, so the message would be a lie.
            return None
        model = config.current_model()
        if not model:
            return None

        others = server.others_vram_gb(current.free_vram_gb())
        if others is None:
            return None
        # What the card would have free for us if nothing but those other
        # programs were on it - the honest version of "is there room here".
        free_of_others = total - others
        kind = fit.verdict(model, total, free_of_others, config.HARDWARE.get("vram_shared", False))
        if not kind:
            # Slow for a reason we can't see. A guess is worse than silence.
            return None
        return self.claim_notice(fit.explain(kind, total, free_of_others))

    def _grounded_options(self, user_input, data):
        """The offered choices, checked against what's really on this machine.

        Returns the choices to use, or None to keep the model's own. An empty
        list is a real answer and means "offer nothing".

        A choice is only trustworthy if the shell put it there. The model
        cannot see this computer, so anything it offers about one is
        invention, and invention here is worse than silence: asked to toggle
        Bluetooth it offered "Bluetooth Adapter 1" and "Bluetooth Adapter 2"
        on a machine with one adapter called neither, and whichever the user
        picked told it nothing. So the only choices that survive are app
        names matched against the installed list.

        Two cases still keep the model's suggestions, both because the shell
        failed rather than the model: an app scan that came back empty (on
        every supported OS that means the scan broke, not that nothing is
        installed) and a grounding call that errored. Neither is evidence
        that the choices are wrong, and degrading the question because our
        own lookup fell over would be the wrong way round.
        """
        if not _LAUNCHY.search(user_input):
            # Not about launching anything, so there is no list to check
            # against and nothing here can be verified.
            return []
        names = [name for name, _ in self._scan_apps()]
        if not names:
            return None
        return pick_installed_apps(self.client, user_input, data.get("explanation", ""), names)

    def run_last(self, command=None):
        """Executes the command from the most recent translate() call (with
        the app-launch fallback baked in) and boils it down to what the
        user should see: {"ok": True, "output": str} on success - or
        {"ok": True, "listing": [...], "path": str} when the command was a
        directory listing - and {"ok": False, "reason": <plain-English
        sentence>} on failure. The fallback retry stays invisible - only the
        final attempt decides the outcome, and failures are explained by the
        model instead of surfacing raw stderr.

        A pending web lookup is carried out here too, and comes back in its own
        shape - {"ok": True, "answer": str|None, "results": [...], "caveat":
        str|None}. Same entry point because it's the same moment in the flow:
        the model has said what to do and the interface has agreed to it.

        `command` is the user's own edit of what the model produced, from the
        confirmation step. None means run the model's version unchanged, which
        is every caller that predates editing. An edit is never re-classified
        for risk: it only reached an edit box by having been called risky, and
        an edit must not be able to talk its way down from that."""
        if not self._pending:
            return None
        if "search" in self._pending:
            query, hint = self._pending["search"], self._pending["hint"]
            self._pending = None
            return self._run_search(query, hint)
        suggested, hint = self._pending["command"], self._pending["hint"]
        if command is None:
            command = suggested
        elif command != suggested:
            # Recorded before resolve_listed_paths touches it: the model's
            # command goes through that helper too, so storing the raw text on
            # both sides is what makes the pair comparable.
            corrections.record(hint, suggested, command)
        command = resolve_listed_paths(command, self._last_listing)
        apps = self._scan_apps() or None

        listing = self._run_listing(command)
        if listing is not None:
            self._pending = None
            return listing

        table = self._run_table(command)
        if table is not None:
            self._pending = None
            return table

        attempts = execute_command(command, apps, self._working_dir())
        self._pending = None

        command_ran, result = attempts[-1]
        if isinstance(result, Exception):
            ok, output, error_text = False, "", str(result)
        else:
            ok = result.returncode == 0
            output = (result.stdout or "").strip()
            error_text = (result.stderr or "").strip()

        if ok:
            answer = _boolean_answer(output) or output
            if current.echoes_created_item(command_ran, answer):
                answer = ""  # the interfaces show their own "done" for empty output
            self._remember_context(command_ran)
            # Empty output means two different things and the interfaces can
            # only render one of them. After "make a folder" it means the
            # folder was made, and "Done" is the whole answer. After "is
            # bluetooth on" it means the command failed to say anything, and
            # "Done" tells the user their question was answered when it
            # wasn't. The request itself is what tells the two apart.
            if not answer and rules.asks_a_question(hint):
                self._note_result(f"Ran: {command_ran}", _NO_ANSWER_NOTE)
                return {"ok": True, "output": NO_ANSWER}
            self._note_result(f"Ran: {command_ran}", _output_summary(answer))
            return {"ok": True, "output": answer}

        reason = explain_failure(self.client, hint, command_ran, error_text or output)
        # A failure is worth remembering too: without it the model has no way
        # to tell "do it again" from "that didn't work, try something else".
        self._note_result(f"Ran: {command_ran}", f"Failed - {reason}")
        return {"ok": False, "reason": reason}

    def _run_search(self, query, hint):
        """Looks `query` up on the web, opens the pages it found, and has the
        model answer from them.

        Two steps, and the second is the one that decides the quality. A
        search engine returns a teaser per result - a sentence written to earn
        a click - and asking a 3B model to answer from five of those is asking
        it to do the hard version of the job. read_results goes and gets the
        actual pages, so most of the time the model is reading articles.

        The results are still the answer here, and the model's summary is a
        convenience on top of them - so a summary that couldn't be produced
        isn't a failure. Both interfaces show the sources either way, which is
        also why a small model is allowed to try at all: the user can see what
        it was reading from, and check it in one click.
        """
        try:
            results = web.search(query)
        except web.SearchError as error:
            self._note_result(f'Searched the web for "{query}"', f"Failed - {error}")
            return {"ok": False, "reason": str(error)}

        if not results:
            self._note_result(f'Searched the web for "{query}"', "Found nothing.")
            return {"ok": False, "reason": f"I couldn't find anything for “{query}”."}

        # Strictly an improvement on what's already here: a page that won't
        # read leaves its result carrying the snippet it came with, so this
        # line can make the answer better and can't make it worse. That's what
        # lets it sit in the path with no failure branch of its own.
        results = web.read_results(results)

        # The user's own words, not the model's query: the query is what was
        # typed into a search box, and answering it instead of the question
        # loses whatever the user actually wanted to know.
        # The same text per result that as_context put in front of the model,
        # so a citation is checked against what was actually read rather than
        # against the page as it exists now.
        texts = [result.get("text") or result.get("snippet") or "" for result in results]
        answer = answer_from_search(self.client, hint, web.as_context(results), texts)
        self._note_result(f'Searched the web for "{query}"', _search_summary(answer, results))
        return {
            "ok": True,
            "query": query,
            "answer": answer,
            "results": web.as_sources(results),
            # Nothing was summarised when there's no answer, so there's nothing
            # to warn about - and the warning is worth more later, on a search
            # where the model did have something to say.
            "caveat": self._caveat() if answer else None,
        }

    def _caveat(self):
        """The small-model warning, the first time this session shows a summary
        it applies to. None once it's been said, and on a model it doesn't
        apply to (see config.SUMMARY_CAVEAT)."""
        # Read at call time: switching to a smaller model is exactly when this
        # starts applying, and a copy taken at import would never notice.
        if not config.SUMMARY_CAVEAT or self._caveat_shown:
            return None
        self._caveat_shown = True
        return config.SUMMARY_CAVEAT

    def list_directory(self, path):
        """Lists `path` for the interfaces' own folder navigation - the user
        clicked a real folder, so there's nothing to translate and no model
        round-trip. It still goes through the normal listing machinery, which
        means clicking into a folder moves the session's context there too: a
        typed "now zip that" after a few clicks means the folder on screen."""
        if not path:
            return {"ok": False, "reason": "There's no folder to open."}
        # Checked before running, because Get-ChildItem on a file happily
        # returns that one file - which would render as a listing of the
        # wrong folder rather than saying anything went wrong.
        if not os.path.isdir(path):
            gone = not os.path.exists(path)
            return {
                "ok": False,
                "reason": "That folder isn't there anymore." if gone else "That's a file, not a folder.",
            }
        listing = self._run_listing(current.list_directory_command(path))
        if listing is None:
            return {"ok": False, "reason": "I couldn't open that folder."}
        # An empty folder has no rows to derive the path from, and losing it
        # would strip the breadcrumbs and strand the user inside with no way
        # back out.
        listing["path"] = listing["path"] or os.path.abspath(path)
        return listing

    def open_path(self, path):
        """Opens a file with whatever the OS uses for it - the click-through
        for a file in a listing. Routed through run_last so a click picks up
        the same plain-English failure and history note as a typed request."""
        if not path:
            return {"ok": False, "reason": "There's no file to open."}
        return self._run_borrowed(current.open_command(path), f"open {os.path.basename(path)}")

    def open_url(self, url):
        """Opens a web address in the user's own browser - the click-through
        for a source listed under a web answer.

        The scheme is checked because this URL came off somebody else's page,
        not off this machine: every platform's "open this" command hands
        whatever it's given to whatever the OS has registered for it, and that
        is a much larger set of things than web pages."""
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return {"ok": False, "reason": "That doesn't look like a web address."}
        return self._run_borrowed(current.open_command(url), f"open {url}")

    def _run_borrowed(self, command, hint):
        """Runs `command` now, without disturbing anything already pending.

        A risky command may be sitting in the slot waiting to be confirmed, and
        a click elsewhere in the window must not consume it - so the slot is
        borrowed and handed back. Going through run_last rather than straight
        to the executor is what gives a click the same plain-English failure
        and the same history note as a typed request."""
        waiting, self._pending = self._pending, {"command": command, "hint": hint}
        try:
            return self.run_last()
        finally:
            self._pending = waiting

    def _run_listing(self, command):
        """Directory listings are run through a projection that emits parseable
        rows (see ai_shell.listing) so the interfaces can render a real table
        rather than PowerShell's console one. Returns None whenever that isn't
        possible - the command isn't a listing, the projected run failed, or
        its output didn't parse - and the caller then runs the original command
        and shows its text as usual. Re-running is safe: nothing reaches this
        point unless it's a read-only listing."""
        projected = current.project_listing(command)
        if not projected:
            return None
        cwd = self._working_dir()
        result = run_command(projected, cwd)
        if isinstance(result, Exception) or result.returncode != 0:
            return None
        items = current.parse_listing(result.stdout or "", cwd)
        if items is None:
            return None
        parent = listing_parent(items)
        kind = current.listing_kind(command)
        self._last_listing = items
        # Listing a folder is what puts the user "in" it, so it sets the
        # context directly rather than going through the path sniffing.
        self._remember_context(command, parent)
        self._note_result(f"Ran: {command}", _listing_summary(items, kind, parent))
        return {"ok": True, "listing": items, "path": parent, "kind": kind}

    def _run_table(self, command):
        """Output that is really a table, returned as columns and rows.

        The same bargain as _run_listing, for the same reason. A shell prints
        a table sized for an eighty-column console, which cuts values off
        mid-word and wraps long rows onto a second line - and by the time the
        text reaches us the characters are gone, so no amount of rendering
        gets them back. Re-running the command projected is the only way to
        have them at all.

        Returns None whenever that isn't possible - the command isn't one of
        the read-only ones, the projected run failed, or its output didn't
        parse - and the caller then runs the original and shows its text as
        usual. Re-running is safe because project_table only accepts commands
        that read.
        """
        projected = current.project_table(command)
        if not projected:
            return None
        result = run_command(projected, self._working_dir())
        if isinstance(result, Exception) or result.returncode != 0:
            return None
        table = current.parse_table(result.stdout or "")
        if table is None:
            return None
        rows = len(table["rows"])
        self._remember_context(command)
        self._note_result(
            f"Ran: {command}",
            f"Showed the user a table of {rows} row{'' if rows == 1 else 's'}, "
            f"with the columns: {', '.join(table['columns'])}.",
        )
        # The text version rides along, and is not redundant. The two halves
        # of this app don't update together - a packaged copy can be running
        # an older window against a newer backend, and an open window is
        # running whatever bundle it loaded at startup. An interface built
        # before tables existed reads "output", finds nothing, and draws
        # nothing at all, so a command that worked looks like it did nothing.
        # A new result shape has to degrade into an old one on its own rather
        # than rely on both sides having been updated.
        return {"ok": True, "table": table, "output": format_table(table)}

    def _remember_context(self, command, parent=None):
        """Updates the folder the session is "in" - set by a listing to the
        folder listed, otherwise to wherever the last absolute path the command
        touched lives. A command with no absolute path leaves it alone, so a
        detour ("what time is it") doesn't lose the user's place."""
        if parent:
            self._context_path = parent
            return
        paths = current.context_paths(command)
        if paths:
            target = paths[-1]
            self._context_path = target if os.path.isdir(target) else os.path.dirname(target)

    def _working_dir(self):
        """The folder to run commands in, or None to inherit the app's own."""
        path = self._context_path
        return path if path and os.path.isdir(path) else None

    def _note_result(self, action, summary):
        """Records in the history what the shell actually did.

        The model sees only its own replies, never the results, so without this
        every turn starts blind: it can't resolve "now zip that", and it
        re-guesses paths the shell had already worked out. The note carries the
        command as it really ran - after resolve_listed_paths, so a path the
        model fumbled comes back corrected - plus the outcome and the folder
        still in play.

        `action` is the whole phrase, not just a command, because not every
        entry here is one: a web lookup ran no command and has no folder, and
        writing it as "Ran: ..." would teach the model that searching is
        something it can spell out in the shell."""
        note = f"(context from the shell, not the user) {action} - {summary}"
        if self._context_path:
            note += f" Folder in context: {self._context_path}"
        self.history.append({"role": "user", "content": note})
        self.history = self.history[-_HISTORY_LIMIT:]
