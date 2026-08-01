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

from ai_shell import config
from ai_shell.config import CONFIG_DIR, CORRECTIONS
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
    listing.resolve_listed_paths touches either — the model's command goes
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
        # Read at call time: a record has to name the model that actually
        # wrote the command, which the user can now change mid-session.
        "model": config.MODEL,
        "os": current.OS_NAME,
    }
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except (OSError, ValueError):
        pass
