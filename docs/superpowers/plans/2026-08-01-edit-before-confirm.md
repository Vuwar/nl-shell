# Edit Before Confirm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the translated command for risky requests and let the user fix it before it runs, recording each fix as a labelled example.

**Architecture:** `Session.run_last()` gains an optional `command` override that replaces the pending command and, when it differs from what the model produced, appends a redacted record to a local JSONL file. Both front ends grow an edit affordance; the CLI seeds the OS's own console line editor through a new `Platform.prefill_input()` with a type-over fallback where that isn't possible.

**Tech Stack:** Python 3.10+, standard library only (`ctypes`, `readline`, `re`, `json`), React 18 for the panel. No new dependencies — the project ships exactly two (`openai`, `pywebview`) and this adds none.

**Spec:** `docs/superpowers/specs/2026-08-01-edit-before-confirm-design.md`

## Global Constraints

- **Tests are `unittest`, never pytest.** Run with `python -m unittest discover -t . -s tests` from the repository root.
- **No new dependencies.** Standard library only.
- Existing tests must keep passing unchanged at every commit.
- `run_last()` called with no argument must behave byte-for-byte as it does today — `_run_borrowed` (`ai_shell/session.py:401`) depends on it.
- Risk is never re-classified. An edited command inherits `risky`.
- An empty or whitespace-only edit cancels, on every path.
- Write failures never propagate: a read-only config folder must not stop a command running.
- Module docstrings and comments in this repository explain *why*, not *what*. Match that register — see `ai_shell/listing.py` for the house style.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: The corrections store

**Files:**
- Create: `ai_shell/corrections.py`
- Modify: `ai_shell/config.py` (add the off switch after the `AUTO_UPDATE` block, around line 146)
- Test: `tests/test_corrections.py`

**Interfaces:**
- Consumes: `ai_shell.config.CONFIG_DIR`, `ai_shell.config.MODEL`, `ai_shell.config.CORRECTIONS`
- Produces:
  - `ai_shell.corrections.redact(text: str) -> str`
  - `ai_shell.corrections.record(request: str, suggested: str, corrected: str) -> None`
  - `ai_shell.corrections.PATH: str` — module constant, patched by tests
  - `ai_shell.config.CORRECTIONS: bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_corrections.py`:

```python
"""ai_shell.corrections — what gets written when the user fixes a command,
and what gets scrubbed out of it on the way."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ai_shell import corrections


class Redaction(unittest.TestCase):
    def test_flag_value_is_removed(self):
        self.assertEqual(
            corrections.redact("mysql --password hunter2 -e 'select 1'"),
            "mysql --password [redacted] -e 'select 1'",
        )

    def test_powershell_style_flag_is_removed(self):
        self.assertEqual(
            corrections.redact("Invoke-Rest -Token abc123def456 -Uri x"),
            "Invoke-Rest -Token [redacted] -Uri x",
        )

    def test_equals_form_is_removed(self):
        self.assertEqual(
            corrections.redact("curl --api-key=sk-live-9f8e7d6c5b4a3210"),
            "curl --api-key=[redacted]",
        )

    def test_connection_string_password_is_removed(self):
        self.assertEqual(
            corrections.redact("psql 'host=db user=me password=s3cr3t sslmode=require'"),
            "psql 'host=db user=me password=[redacted] sslmode=require'",
        )

    def test_bearer_token_is_removed(self):
        self.assertEqual(
            corrections.redact("curl -H 'Authorization: Bearer eyJhbGci0iJIUzI1N'"),
            "curl -H 'Authorization: Bearer [redacted]'",
        )

    def test_long_hex_is_removed(self):
        self.assertEqual(
            corrections.redact("git checkout 9f8e7d6c5b4a32109f8e7d6c5b4a32109f8e7d6c"),
            "git checkout [redacted]",
        )

    def test_token_shaped_run_is_removed(self):
        self.assertEqual(
            corrections.redact("gh auth login --with-token ghp1A2b3C4d5E6f7G8h9I0j1K2l3M4n5O6p7"),
            "gh auth login --with-token [redacted]",
        )

    # The one that matters most: the dataset is worthless if ordinary paths
    # get scrubbed, and a Windows path is a long run of exactly the characters
    # a naive token pattern looks for.
    def test_windows_path_survives(self):
        command = r"Remove-Item 'C:\Users\vuqar\Downloads\quarterly_report_2026.pdf'"
        self.assertEqual(corrections.redact(command), command)

    def test_posix_path_survives(self):
        command = "rm -rf /home/vuqar/projects/nl-shell/build/artifacts"
        self.assertEqual(corrections.redact(command), command)

    def test_ordinary_command_survives(self):
        command = "Get-ChildItem ~/Desktop -Recurse | Sort-Object Length"
        self.assertEqual(corrections.redact(command), command)


class Recording(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "corrections.jsonl")
        self.addCleanup(self._dir.cleanup)

    def _read(self):
        with open(self.path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_a_correction_is_written(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", True):
            corrections.record("delete the logs", "Remove-Item a.log", "Remove-Item b.log")
        rows = self._read()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request"], "delete the logs")
        self.assertEqual(rows[0]["suggested"], "Remove-Item a.log")
        self.assertEqual(rows[0]["corrected"], "Remove-Item b.log")
        self.assertIn("at", rows[0])
        self.assertIn("model", rows[0])
        self.assertIn("os", rows[0])

    def test_an_unchanged_command_is_not_a_correction(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", True):
            corrections.record("x", "Remove-Item a.log", "Remove-Item a.log")
        self.assertFalse(os.path.exists(self.path))

    def test_records_append(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", True):
            corrections.record("one", "a", "b")
            corrections.record("two", "c", "d")
        self.assertEqual([row["request"] for row in self._read()], ["one", "two"])

    def test_secrets_are_scrubbed_before_writing(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", True):
            corrections.record(
                "log in",
                "mysql --password hunter2",
                "mysql --password hunter3 -h db",
            )
        row = self._read()[0]
        self.assertNotIn("hunter2", row["suggested"])
        self.assertNotIn("hunter3", row["corrected"])
        self.assertIn("[redacted]", row["corrected"])

    def test_disabled_writes_nothing(self):
        with patch.object(corrections, "PATH", self.path), \
             patch.object(corrections, "ENABLED", False):
            corrections.record("x", "a", "b")
        self.assertFalse(os.path.exists(self.path))

    def test_an_unwritable_location_is_not_an_error(self):
        # A directory where the file should be: opening it for append raises,
        # and running a command must not fail because of it.
        blocked = os.path.join(self._dir.name, "blocked")
        os.makedirs(blocked)
        with patch.object(corrections, "PATH", blocked), \
             patch.object(corrections, "ENABLED", True):
            corrections.record("x", "a", "b")  # must not raise


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_corrections -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ai_shell.corrections'`

- [ ] **Step 3: Add the off switch to `ai_shell/config.py`**

Insert directly after the `LAST_UPDATE_CHECK` assignment (currently `config.py:146`):

```python
# Whether an edited command is recorded to CONFIG_DIR/corrections.jsonl. On by
# default, and unlike anything that reads existing shell history this only sees
# commands typed into this app, in this session, on their way to running — it
# never leaves the machine. Off by default would collect nothing, which is the
# same as not having the feature. See ai_shell/corrections.py for what a record
# holds and what is scrubbed out of it first.
CORRECTIONS = (os.environ.get("AI_SHELL_CORRECTIONS") or "").strip() != "0" and bool(
    _SETTINGS.get("corrections", True)
)
```

- [ ] **Step 4: Write `ai_shell/corrections.py`**

```python
"""What the user typed when the model got it wrong.

A command the user edits before confirming is the one labelled example this
app can produce about itself: this request, on this machine, should have
produced this command. Nothing reads this file yet — it exists so that the
examples are accumulating by the time something wants them.

Append-only, local, and never sent anywhere. Records are written only when the
user actually changed something: a risky command confirmed as-written is not a
correction, and keeping those would dilute the set with rows that teach
nothing.
"""

import json
import os
import re
import time

from ai_shell.config import CONFIG_DIR, CORRECTIONS, MODEL
from ai_shell.platforms import current

PATH = os.path.join(CONFIG_DIR, "corrections.jsonl")

ENABLED = CORRECTIONS

_MASK = "[redacted]"

# --- scrubbing --------------------------------------------------------------
# Best-effort, and deliberately so. The file never leaves the machine, so the
# risk being managed is a user opening it and finding a password they pasted
# into a curl six weeks ago — not an exfiltration path. Over-redacting costs
# one row of a dataset; under-redacting costs the thing people remember about
# the app, so where the two conflict this leans on the first.

# --password hunter2 | -Token abc | --api-key=sk-live-...
_FLAG_VALUE = re.compile(
    r"(?i)(-{1,2}(?:password|passwd|pwd|token|secret|api[-_]?key|apikey|access[-_]?key)"
    r"[=:\s]\s*)(\S+)"
)

# host=db user=me password=s3cr3t — inside a connection string, where the key
# has no leading dash to recognise it by.
_CONNECTION = re.compile(r"(?i)\b(password|pwd)(\s*=\s*)([^;\s'\"]+)")

_BEARER = re.compile(r"(?i)\b(bearer\s+)([^\s'\"]+)")

# A commit hash, an API key, a session id. 32 rather than 20 because a shorter
# floor starts catching ordinary hexadecimal arguments.
_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")

# A long opaque token: letters and digits mixed, at least 20 characters, and
# not touching a path separator or a dot on either side. Those exclusions are
# what keeps `C:\Users\vuqar\Downloads\quarterly_report_2026.pdf` intact —
# every segment of a path is short, and the separators break the run.
_TOKENISH = re.compile(
    r"(?<![\w./\\:-])"
    r"(?=[A-Za-z0-9+_=-]*[A-Za-z])"
    r"(?=[A-Za-z0-9+_=-]*\d)"
    r"[A-Za-z0-9+_=-]{20,}"
    r"(?![\w./\\:-])"
)


def redact(text):
    """`text` with anything that looks like a credential replaced by
    "[redacted]". Best-effort — see the note above."""
    if not text:
        return text
    text = _FLAG_VALUE.sub(lambda m: m.group(1) + _MASK, text)
    text = _CONNECTION.sub(lambda m: m.group(1) + m.group(2) + _MASK, text)
    text = _BEARER.sub(lambda m: m.group(1) + _MASK, text)
    text = _HEX.sub(_MASK, text)
    text = _TOKENISH.sub(_MASK, text)
    return text


def record(request, suggested, corrected):
    """Append one correction, or do nothing at all.

    Both commands are stored as they were written, before
    listing.resolve_listed_paths touches either — the model's output goes
    through that helper too, so raw against raw is the honest comparison.

    Every failure here is swallowed. This runs on the way to executing a
    command the user has already confirmed, and a config folder that can't be
    written to is not a reason to refuse to run it.
    """
    if not ENABLED or not corrected or corrected == suggested:
        return
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request": redact(request or ""),
        "suggested": redact(suggested or ""),
        "corrected": redact(corrected),
        # Which model produced the command that had to be fixed: an eval set
        # built from this file is worthless without knowing what it is scoring.
        "model": MODEL,
        "os": current.OS_NAME,
    }
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except (OSError, ValueError):
        pass
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest tests.test_corrections -v`
Expected: PASS, 17 tests

- [ ] **Step 6: Run the whole suite**

Run: `python -m unittest discover -t . -s tests`
Expected: PASS, no failures

- [ ] **Step 7: Commit**

```bash
git add ai_shell/corrections.py ai_shell/config.py tests/test_corrections.py
git commit -m "$(cat <<'EOF'
feat: record commands the user corrects

An edited command is the one labelled example this app can produce about
itself. Nothing reads the file yet; it exists so the examples accumulate
before something wants them.

Credentials are scrubbed on the way in, and paths deliberately are not —
a dataset that redacts C:\Users\... teaches nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `Session.run_last()` accepts an edited command

**Files:**
- Modify: `ai_shell/session.py:232-284` (the `run_last` signature and the command branch)
- Test: `tests/test_editing.py` (new)

**Interfaces:**
- Consumes: `ai_shell.corrections.record` from Task 1
- Produces: `Session.run_last(command: str | None = None)` — `None` means "run what the model produced"; a string replaces it and is recorded when it differs

- [ ] **Step 1: Write the failing tests**

Create `tests/test_editing.py`:

```python
"""Session.run_last with a command the user edited — what runs, and what gets
recorded."""

import json
import unittest
from unittest.mock import patch

from ai_shell.session import Session
from tests.stubs import StubClient


def _reply(command, risk="risky"):
    return json.dumps({
        "command": command, "search": None, "risk": risk,
        "explanation": "does a thing", "options": None,
    })


class _Ran:
    """Stands in for subprocess.CompletedProcess."""

    def __init__(self):
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""


class EditedCommands(unittest.TestCase):
    def setUp(self):
        # The app scan runs on a thread and shells out; nothing here needs it.
        patcher = patch("ai_shell.session.list_apps", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _session(self, command):
        session = Session()
        session.client = StubClient(_reply(command))
        session.translate("delete the logs")
        return session

    def test_the_edited_command_is_what_runs(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record"):
            run.return_value = [("Remove-Item b.log", _Ran())]
            session.run_last("Remove-Item b.log")
        self.assertEqual(run.call_args[0][0], "Remove-Item b.log")

    def test_no_argument_runs_the_models_command(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run:
            run.return_value = [("Remove-Item a.log", _Ran())]
            session.run_last()
        self.assertEqual(run.call_args[0][0], "Remove-Item a.log")

    def test_an_edit_is_recorded(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record") as record:
            run.return_value = [("Remove-Item b.log", _Ran())]
            session.run_last("Remove-Item b.log")
        record.assert_called_once_with(
            "delete the logs", "Remove-Item a.log", "Remove-Item b.log"
        )

    def test_an_unchanged_command_records_nothing(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record") as record:
            run.return_value = [("Remove-Item a.log", _Ran())]
            session.run_last("Remove-Item a.log")
        record.assert_not_called()

    def test_no_argument_records_nothing(self):
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record") as record:
            run.return_value = [("Remove-Item a.log", _Ran())]
            session.run_last()
        record.assert_not_called()

    def test_the_edited_command_still_resolves_listed_paths(self):
        # The user types a name they can see in the listing; it has to reach
        # the folder they are looking at, not the process working directory.
        session = self._session("Remove-Item wrong.txt")
        session._last_listing = [
            {"name": "report.pdf", "path": r"C:\Users\x\Desktop\report.pdf",
             "dir": False, "size": 1, "modified": None},
        ]
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record"):
            run.return_value = [("x", _Ran())]
            session.run_last("Remove-Item report.pdf")
        self.assertIn("Desktop", run.call_args[0][0])

    def test_the_recorded_text_is_what_the_user_typed(self):
        # Raw against raw: the model's command is recorded before resolution
        # too, so the pair compares like with like.
        session = self._session("Remove-Item wrong.txt")
        session._last_listing = [
            {"name": "report.pdf", "path": r"C:\Users\x\Desktop\report.pdf",
             "dir": False, "size": 1, "modified": None},
        ]
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record") as record:
            run.return_value = [("x", _Ran())]
            session.run_last("Remove-Item report.pdf")
        self.assertEqual(record.call_args[0][2], "Remove-Item report.pdf")

    def test_borrowed_runs_are_unaffected(self):
        # A click elsewhere in the window must not consume the pending command.
        session = self._session("Remove-Item a.log")
        with patch("ai_shell.session.execute_command") as run, \
             patch("ai_shell.session.corrections.record"):
            run.return_value = [("open x", _Ran())]
            session._run_borrowed("open x", "open x")
        self.assertEqual(session._pending["command"], "Remove-Item a.log")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_editing -v`
Expected: FAIL — `TypeError: run_last() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Modify `ai_shell/session.py`**

Add the import alongside the others at the top (after `from ai_shell import web`, line 28):

```python
from ai_shell import corrections, web
```

Replace the `run_last` signature and docstring opening (`session.py:232`):

```python
    def run_last(self, command=None):
```

Add to that docstring, before the closing `"""`:

```
        `command` is the user's own edit of what the model produced, from the
        confirmation step. None means run the model's version unchanged, which
        is every caller that predates editing. An edit is never re-classified
        for risk: it only reached an edit box by having been called risky, and
        an edit must not be able to talk its way down from that.
```

Then replace the command branch (currently `session.py:252-253`):

```python
        command, hint = self._pending["command"], self._pending["hint"]
        command = resolve_listed_paths(command, self._last_listing)
```

with:

```python
        suggested, hint = self._pending["command"], self._pending["hint"]
        if command is None:
            command = suggested
        else:
            # Recorded before resolve_listed_paths touches it: the model's
            # command goes through that helper too, so storing the raw text on
            # both sides is what makes the pair comparable.
            corrections.record(hint, suggested, command)
        command = resolve_listed_paths(command, self._last_listing)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_editing -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Run the whole suite**

Run: `python -m unittest discover -t . -s tests`
Expected: PASS, no failures

- [ ] **Step 6: Commit**

```bash
git add ai_shell/session.py tests/test_editing.py
git commit -m "$(cat <<'EOF'
feat: run_last accepts the user's edit of the command

None keeps every existing caller on the old path, so _run_borrowed is
untouched. An edit runs through resolve_listed_paths exactly as the
model's own command does — a hand-typed name is a name the user can see
in the listing, and it has to reach that folder rather than the process
working directory.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `Platform.prefill_input()`

**Files:**
- Modify: `ai_shell/platforms/base.py` (new method, after `strip_error_prefix`, around line 69)
- Modify: `ai_shell/platforms/posix.py` (override)
- Modify: `ai_shell/platforms/windows.py` (override)
- Test: `tests/test_prefill.py` (new)

**Interfaces:**
- Produces: `Platform.prefill_input(prompt: str, text: str) -> str | None` — `None` means this platform cannot prefill and the caller must fall back to a type-over prompt. Any string, **including an empty one**, is what the user entered.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prefill.py`:

```python
"""Platform.prefill_input — asking for a line that already has something in it.

The prefilled paths can't be exercised here: a test run has redirected stdin
and no console to inject keystrokes into. What is tested is the contract the
CLI depends on — that "can't do that here" is reported as None and is
distinguishable from an empty answer.
"""

import unittest

from ai_shell.platforms.base import Platform


class BaseContract(unittest.TestCase):
    def test_the_base_platform_cannot_prefill(self):
        self.assertIsNone(Platform().prefill_input("> ", "Remove-Item a.log"))

    def test_none_is_not_an_empty_string(self):
        # The CLI tells "this platform can't" from "the user cleared the line"
        # by identity, so these must never collapse into each other.
        self.assertIsNot(Platform().prefill_input("> ", "x"), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_prefill -v`
Expected: FAIL — `AttributeError: 'Platform' object has no attribute 'prefill_input'`

- [ ] **Step 3: Add the base method**

In `ai_shell/platforms/base.py`, after `strip_error_prefix` (line 69):

```python
    def prefill_input(self, prompt, text):
        """Ask for a line of input with `text` already in the buffer, so the
        user edits it instead of retyping it. The line as they left it, or
        None where this platform can't do it.

        None and "" are different answers and the caller relies on it: None is
        "no console editing here, fall back to a type-over prompt", while "" is
        a user who cleared the line, which cancels. Returning "" for both would
        turn an unsupported platform into a silent cancellation.
        """
        return None
```

- [ ] **Step 4: Add the POSIX override**

In `ai_shell/platforms/posix.py`, inside `class Platform(...)`, after the existing methods:

```python
    def prefill_input(self, prompt, text):
        """readline does the whole job: a startup hook puts the text in the
        buffer, and the user gets the line editing they already have in their
        shell. Not present on every build of Python, hence the guard."""
        try:
            import readline
        except ImportError:
            return None

        def hook():
            readline.insert_text(text)
            readline.redisplay()

        readline.set_startup_hook(hook)
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            # Both mean "not this one" — an empty line, which the caller reads
            # as a cancellation.
            print()
            return ""
        finally:
            readline.set_startup_hook()
```

- [ ] **Step 5: Add the Windows override**

In `ai_shell/platforms/windows.py`, add these structures at module level, after the existing regex constants:

```python
# Console input records, for prefilling a line the user can then edit with the
# console's own editor (see Platform.prefill_input). Windows has no readline,
# and writing one is a great deal more code than handing the terminal the
# keystrokes and letting it do what it already does.
_STD_INPUT_HANDLE = -10
_KEY_EVENT = 0x0001


class _CharUnion(ctypes.Union):
    _fields_ = [("UnicodeChar", ctypes.c_wchar), ("AsciiChar", ctypes.c_char)]


class _KeyEventRecord(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", ctypes.c_int),
        ("wRepeatCount", ctypes.c_ushort),
        ("wVirtualKeyCode", ctypes.c_ushort),
        ("wVirtualScanCode", ctypes.c_ushort),
        ("uChar", _CharUnion),
        ("dwControlKeyState", ctypes.c_uint),
    ]


class _EventUnion(ctypes.Union):
    _fields_ = [("KeyEvent", _KeyEventRecord)]


class _InputRecord(ctypes.Structure):
    _fields_ = [("EventType", ctypes.c_ushort), ("Event", _EventUnion)]
```

Then, inside `class Platform(...)`:

```python
    def prefill_input(self, prompt, text):
        """The command typed into the console's input buffer before the user
        gets there, so `input()` comes up with it already on the line and the
        console's own editor handles arrows and backspace.

        None whenever there is no real console to write into — a redirected
        stdin, which is what a test run, a pipe and CI all have. The caller
        then prints a type-over prompt instead.
        """
        if not text:
            return None
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
            if handle in (0, -1):
                return None
            # GetConsoleMode fails on anything that isn't a console, which is
            # exactly the case where the injection below would go nowhere.
            mode = ctypes.c_uint()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return None

            records = (_InputRecord * (len(text) * 2))()
            for index, char in enumerate(text):
                for offset, down in ((0, 1), (1, 0)):
                    record = records[index * 2 + offset]
                    record.EventType = _KEY_EVENT
                    record.Event.KeyEvent.bKeyDown = down
                    record.Event.KeyEvent.wRepeatCount = 1
                    record.Event.KeyEvent.wVirtualKeyCode = 0
                    record.Event.KeyEvent.wVirtualScanCode = 0
                    record.Event.KeyEvent.uChar.UnicodeChar = char
                    record.Event.KeyEvent.dwControlKeyState = 0
            written = ctypes.c_uint()
            if not kernel32.WriteConsoleInputW(
                handle, records, len(records), ctypes.byref(written)
            ):
                return None
        except (OSError, AttributeError, ValueError):
            return None

        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return ""
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m unittest tests.test_prefill -v`
Expected: PASS, 2 tests

- [ ] **Step 7: Run the whole suite**

Run: `python -m unittest discover -t . -s tests`
Expected: PASS, no failures

- [ ] **Step 8: Verify the Windows prefill by hand**

This is the one piece no test can reach, and it is the piece most likely to be
wrong. In a **real console window** (Windows Terminal or conhost, not an IDE's
output pane, not a piped command):

```bash
python -c "from ai_shell.platforms import current; print(repr(current.prefill_input('edit> ', 'Remove-Item a.log')))"
```

Expected: the prompt appears with `Remove-Item a.log` already on the line.
Pressing Left/Backspace edits it. Enter returns what is on the line.

Then confirm the fallback triggers when there is no console:

```bash
echo "" | python -c "from ai_shell.platforms import current; print(repr(current.prefill_input('edit> ', 'x')))"
```

Expected: `None`

If the first check prints the prompt with an empty line, the injection
silently failed — check `WriteConsoleInputW`'s return and that
`wVirtualKeyCode` being 0 is accepted; some consoles want a real scan code.

- [ ] **Step 9: Commit**

```bash
git add ai_shell/platforms/base.py ai_shell/platforms/posix.py ai_shell/platforms/windows.py tests/test_prefill.py
git commit -m "$(cat <<'EOF'
feat: platform hook for a prefilled input line

readline on POSIX, WriteConsoleInputW on Windows, and an honest None from
the base class where neither applies. Letting each OS's console editor do
the work is a great deal less code than a line editor of our own, and it
gives the user the editing they already know.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The CLI shows and edits the command

**Files:**
- Modify: `ai_shell_cli/app.py` (imports; the risky branch at lines 105-113; new `_edit_command` helper)
- Test: `tests/test_cli_edit.py` (new)

**Interfaces:**
- Consumes: `Platform.prefill_input` (Task 3), `Session.run_last(command)` (Task 2)
- Produces: `ai_shell_cli.app._edit_command(command: str) -> str` — the command as the user wants it, or `""` to cancel

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_edit.py`:

```python
"""The console REPL's edit step.

Only the type-over path is exercised: a test run has redirected stdin, so
prefill_input returns None, which is the branch that actually runs in CI.
"""

import unittest
from unittest.mock import patch

from ai_shell_cli import app


class EditCommand(unittest.TestCase):
    def test_the_typed_command_replaces_the_original(self):
        with patch.object(app.current, "prefill_input", return_value=None), \
             patch("builtins.input", return_value="Remove-Item b.log"):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "Remove-Item b.log")

    def test_an_empty_line_cancels(self):
        with patch.object(app.current, "prefill_input", return_value=None), \
             patch("builtins.input", return_value=""):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "")

    def test_whitespace_only_cancels(self):
        with patch.object(app.current, "prefill_input", return_value=None), \
             patch("builtins.input", return_value="   "):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "")

    def test_a_prefilled_line_is_used_as_given(self):
        with patch.object(app.current, "prefill_input", return_value="Remove-Item c.log"):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "Remove-Item c.log")

    def test_a_cleared_prefilled_line_cancels(self):
        # "" from prefill_input is a user who deleted the whole line, which is
        # not the same answer as None.
        with patch.object(app.current, "prefill_input", return_value=""):
            self.assertEqual(app._edit_command("Remove-Item a.log"), "")

    def test_the_fallback_is_not_used_when_prefill_works(self):
        with patch.object(app.current, "prefill_input", return_value="edited"), \
             patch("builtins.input") as fallback:
            app._edit_command("original")
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_cli_edit -v`
Expected: FAIL — `AttributeError: module 'ai_shell_cli.app' has no attribute '_edit_command'`

- [ ] **Step 3: Add the import to `ai_shell_cli/app.py`**

Add after the existing `from ai_shell.listing import format_listing` (line 7):

```python
from ai_shell.platforms import current
```

- [ ] **Step 4: Add the `_edit_command` helper**

Place it above `_install_update` in `ai_shell_cli/app.py`:

```python
def _edit_command(command):
    """The command as the user wants it, or "" to cancel.

    Two ways in. Where the platform can seed the console's own line editor,
    the command is already on the line and the user fixes the part that's
    wrong. Where it can't — a redirected stdin, an unusual terminal — the
    command has just been printed above, and whatever is typed replaces it
    whole.

    An empty line cancels on both paths. The alternative, where empty means
    "keep it" when there is nothing in the buffer and "I deleted it" when
    there is, makes the same keystroke run a risky command on one platform and
    cancel it on another. Keeping the command unedited is what `y` is for.
    """
    edited = current.prefill_input("  ", command)
    if edited is None:
        print("  Type the corrected command, or leave it empty to cancel:")
        try:
            edited = input("  ")
        except (EOFError, KeyboardInterrupt):
            print()
            return ""
    return edited.strip()
```

- [ ] **Step 5: Replace the risky branch**

In `ai_shell_cli/app.py`, replace lines 105-113 — currently:

```python
        print(f"→ {explanation}")

        if risk == "risky":
            confirm = input("  This can't easily be undone. Run it? (y/N): ").strip().lower()
            if confirm != "y":
                print("  Skipped.")
                continue

        result = session.run_last()
```

with:

```python
        print(f"→ {explanation}")

        # None means "run what the model wrote"; a string is the user's own
        # version, which the session records as a correction.
        edited = None
        if risk == "risky":
            print(f"\n  {command}\n")
            choice = input("  This can't easily be undone. Run it? (y/N/e to edit): ").strip().lower()
            if choice == "e":
                edited = _edit_command(command)
                if not edited:
                    print("  Skipped.")
                    continue
            elif choice != "y":
                print("  Skipped.")
                continue

        result = session.run_last(edited)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m unittest tests.test_cli_edit -v`
Expected: PASS, 6 tests

- [ ] **Step 7: Run the whole suite**

Run: `python -m unittest discover -t . -s tests`
Expected: PASS, no failures

- [ ] **Step 8: Commit**

```bash
git add ai_shell_cli/app.py tests/test_cli_edit.py
git commit -m "$(cat <<'EOF'
feat(cli): show the risky command, and let it be edited

The command was never printed — the README said it was, and it wasn't.
Now it is shown above the confirmation, and `e` opens it for editing
rather than making the user retype the whole request and hope the next
translation lands differently.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The panel shows and edits the command

**Files:**
- Modify: `ai_shell_gui/app.py:205-207` (`Api.confirm`)
- Modify: `ai_shell_gui/frontend/src/App.jsx` (the `confirm` case around line 703, `askConfirmation` around 1097, `onConfirmClick` around 1104, the call site around 1226)
- Modify: `ai_shell_gui/frontend/src/App.css` (after `.confirm-row span`, around line 922)

**Interfaces:**
- Consumes: `Session.run_last(command)` (Task 2)
- Produces: `Api.confirm(command: str | None = None)`; `askConfirmation(command)` resolving to `{proceed: boolean, command: string | null}`

- [ ] **Step 1: Widen `Api.confirm`**

In `ai_shell_gui/app.py`, replace lines 205-207:

```python
    def confirm(self, command=None):
        """Runs the pending command; returns {"ok", "output"} or {"ok", "reason"}.

        `command` is the user's edit of what was shown, or None to run the
        model's version. An edit is not re-classified for risk — it only
        reached an edit box by having been called risky.
        """
        return self.session.run_last(command)
```

- [ ] **Step 2: Add the `ConfirmRow` component to `App.jsx`**

The confirm row needs local state for the textarea, so it becomes its own
component. Add it **below `keepGesture` (line 307)** and above the entry
rendering `switch` — it calls `keepGesture`, which is a module-level const, so
it has to come after that declaration.

`useState`, `useEffect` and `useRef` are already imported on `App.jsx:1`;
nothing needs adding to the React import.

```jsx
function ConfirmRow({ command, onDecide }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(command);
  const areaRef = useRef(null);

  useEffect(() => {
    if (editing && areaRef.current) {
      areaRef.current.focus();
      const end = areaRef.current.value.length;
      areaRef.current.setSelectionRange(end, end);
    }
  }, [editing]);

  function submitEdit() {
    const text = draft.trim();
    // An empty edit cancels rather than running an empty command — the same
    // rule the console REPL follows.
    onDecide(text ? { proceed: true, command: text } : { proceed: false, command: null });
  }

  function onKeyDown(e) {
    // Shift+Enter inserts a newline: a "command" may be a short script.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitEdit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onDecide({ proceed: false, command: null });
    }
  }

  return (
    <div className="entry confirm-block">
      {editing ? (
        <textarea
          ref={areaRef}
          className="confirm-edit"
          value={draft}
          spellCheck={false}
          rows={Math.min(6, draft.split("\n").length)}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onMouseDown={keepGesture}
        />
      ) : (
        <pre className="confirm-command" onMouseDown={keepGesture}>
          {command}
        </pre>
      )}
      <div className="confirm-row">
        <span>Run this? It can't easily be undone.</span>
        {editing ? (
          <button className="btn run" onClick={submitEdit}>
            Run it
          </button>
        ) : (
          <>
            <button
              className="btn run"
              onClick={() => onDecide({ proceed: true, command: null })}
            >
              Run it
            </button>
            <button className="btn" onClick={() => setEditing(true)}>
              Edit
            </button>
          </>
        )}
        <button
          className="btn cancel"
          onClick={() => onDecide({ proceed: false, command: null })}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
```

Confirm that `useState`, `useEffect` and `useRef` are already in the React
import at the top of `App.jsx`; add any that are missing.

- [ ] **Step 3: Render it from the entry switch**

Replace the `case "confirm":` block (currently lines 703-714):

```jsx
    case "confirm":
      return (
        <ConfirmRow
          command={entry.command}
          onDecide={(decision) => onConfirm(entry.id, decision)}
        />
      );
```

- [ ] **Step 4: Carry the command and the decision through**

Replace `askConfirmation` and `onConfirmClick` (currently lines 1097-1109):

```jsx
  function askConfirmation(command) {
    return new Promise((resolve) => {
      const id = addEntry({ kind: "confirm", command });
      confirmResolvers.current[id] = resolve;
    });
  }

  function onConfirmClick(id, decision) {
    setEntries((prev) => prev.filter((e) => e.id !== id));
    const resolve = confirmResolvers.current[id];
    delete confirmResolvers.current[id];
    if (resolve) resolve(decision);
  }
```

Then replace the call site (currently lines 1226-1238):

```jsx
      // None means run what the model wrote; a string is the user's own
      // version, which the session records as a correction.
      let edited = null;
      if (data.risk === "risky") {
        const decision = await askConfirmation(data.command);
        if (!decision.proceed) {
          addEntry({ kind: "skipped" });
          setStatus("ok");
          return;
        }
        edited = decision.command;
      }

      // Keep the dots up while the command (and, on failure, the model's
      // explanation of why) runs — both can take a few seconds.
      const runningId = addEntry({ kind: "thinking" });
      const result = await window.pywebview.api.confirm(edited);
```

- [ ] **Step 5: Add the styles**

In `ai_shell_gui/frontend/src/App.css`, after the `.confirm-row span` rule (line 922):

```css
.confirm-block {
  margin-top: 8px;
}

.confirm-block .confirm-row {
  margin-top: 0;
  border-top-left-radius: 0;
  border-top-right-radius: 0;
}

.confirm-command,
.confirm-edit {
  font-family: var(--mono);
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--text);
  margin: 0;
  padding: 10px 12px;
  background: rgba(255, 107, 107, 0.08);
  border: 1px solid rgba(255, 107, 107, 0.2);
  border-bottom: none;
  border-radius: 12px 12px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
}

.confirm-edit {
  display: block;
  width: 100%;
  resize: none;
  outline: none;
  box-sizing: border-box;
}

.confirm-edit:focus {
  border-color: rgba(255, 107, 107, 0.45);
}
```

`--mono` is declared in `index.css:41` and is what `pre.output-block`
(`App.css:966`) already uses, so the command reads as code exactly the way
command output does.

- [ ] **Step 6: Build the front end**

Run:
```bash
npm --prefix ai_shell_gui/frontend install
npm --prefix ai_shell_gui/frontend run build
```
Expected: build succeeds, `ai_shell_gui/frontend/dist/` written, no errors.

- [ ] **Step 7: Run the whole suite**

Run: `python -m unittest discover -t . -s tests`
Expected: PASS, no failures

- [ ] **Step 8: Verify the panel by hand**

Run: `python run_gui.py`

Check each of these:
1. Ask for something risky ("delete every .log file on my desktop"). The
   command appears above the confirm row.
2. **Run it** runs it unchanged.
3. **Edit** turns it into a textarea with the command in it, cursor at the end.
4. Enter runs the edited command; Shift+Enter adds a line; Escape cancels.
5. Clearing the box and pressing Enter cancels rather than running nothing.
6. `CONFIG_DIR/corrections.jsonl` has one row after an edit, and no row after
   an unedited **Run it**.

- [ ] **Step 9: Commit**

```bash
git add ai_shell_gui/app.py ai_shell_gui/frontend/src/App.jsx ai_shell_gui/frontend/src/App.css
git commit -m "$(cat <<'EOF'
feat(gui): show the risky command, and let it be edited

The panel asked "Run this?" without ever saying what "this" was. The
command now sits above the confirmation, and Edit opens it in place —
Enter runs, Shift+Enter for a script, Escape cancels.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md:326-328` (the safe/risky bullets), `README.md:539-545` (known limitations), and the project-layout block around line 333

**Interfaces:** none — documentation only.

- [ ] **Step 1: Correct the confirmation bullets**

In `README.md`, replace:

```markdown
- Safe commands run immediately
- Risky commands (delete, overwrite, install, system settings, etc.) show
  you the exact command and ask for confirmation before running
```

with:

```markdown
- Safe commands run immediately
- Risky commands (delete, overwrite, install, system settings, etc.) show
  you the exact command and ask for confirmation before running — and let
  you edit it first, because the model getting one path segment wrong
  shouldn't mean retyping the whole request
```

- [ ] **Step 2: Document the corrections file**

Add to `README.md` immediately after that list:

```markdown
When you edit a command before running it, the pair — what you asked for, what
the model wrote, what you replaced it with — is appended to
`corrections.jsonl` in the config folder. It stays on your machine; nothing
reads it yet, and nothing sends it anywhere. It exists so there is real data
about where the model goes wrong on *your* computer by the time something can
use it.

Anything that looks like a credential is replaced with `[redacted]` first —
values after `--password`, `-Token`, `--api-key` and friends, `password=` in a
connection string, `Bearer` tokens, and long opaque hex or base64 runs. That is
best-effort pattern matching, not a guarantee; file paths are deliberately left
alone, because a record that scrubbed them would teach nothing.

Turn it off with `AI_SHELL_CORRECTIONS=0`, or `"corrections": false` in
`settings.json`.
```

- [ ] **Step 3: Add the module to the project layout**

In the project-layout block (around `README.md:333`), after the
`ai_shell/config.py` line:

```
ai_shell/corrections.py  commands you edited before running, for later use as training/eval data
```

- [ ] **Step 4: Soften the limitation that no longer holds**

In "Known limitations", replace:

```markdown
- Command safety classification is done by the model's judgment, not a
  hardcoded rule list — good enough to start, not bulletproof. Don't point
  this at anything you can't afford to lose, and read the command before
  confirming risky actions.
```

with:

```markdown
- Command safety classification is done by the model's judgment, not a
  hardcoded rule list — good enough to start, not bulletproof. Don't point
  this at anything you can't afford to lose, and read the command before
  confirming risky actions. Editing one doesn't get it re-classified: it was
  called risky once and it stays risky, which is the safe direction to be
  wrong in.
```

- [ ] **Step 5: Verify the claims are now true**

Read `README.md:326-330` next to `ai_shell_cli/app.py`'s risky branch and
`App.jsx`'s `ConfirmRow`. Every behaviour the README describes must exist in
one of them. This step exists because the line being corrected here was
describing behaviour the code never had.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: describe editing, and stop claiming what wasn't true

The README already said risky commands showed you the exact command.
They didn't, in either front end. They do now, so the claim is honest —
and the corrections file, its redaction and its off switch are written
down alongside it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Verification

After every task, from the repository root:

```bash
python -m unittest discover -t . -s tests
```

Expected: OK, no failures, no errors.

The two things no test covers, both verified by hand in their own tasks:
Windows console prefill (Task 3, Step 8) and the panel's edit flow
(Task 5, Step 8).

## Out of scope

Reading `corrections.jsonl` (§1.3), an eval harness over it (§7.1), a
`/corrections` inspect-and-clear view, showing commands for safe requests, and
any re-classification machinery.
