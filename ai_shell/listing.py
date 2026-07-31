"""Directory listings as data instead of the shell's terminal-shaped output.

Shells print for a console: attribute-flag columns, sizes in raw bytes, a
timestamp on every row whether or not anyone wanted one. The interfaces can
present that far better, but only if they get rows instead of pre-formatted
text — so a listing command is re-projected to emit something parseable, and
the result is read back into dicts.

Both of those halves depend on the OS and belong to ai_shell.platforms
(project_listing / parse_listing). What's here is everything done with the
rows afterwards, which is the same everywhere.
"""

import os
import re

from ai_shell.platforms import current

_SHORTCUT = re.compile(r"\.(lnk|url)$", re.IGNORECASE)

_UNITS = ("KB", "MB", "GB", "TB", "PB")


def listing_parent(items):
    """The folder being listed, or None when the rows span several (-Recurse
    on Windows, a deeper -maxdepth elsewhere)."""
    parents = {os.path.dirname(item["path"].rstrip("\\/")) for item in items}
    return parents.pop() if len(parents) == 1 else None


# A quoted string, or a bare whitespace-delimited token.
_ARGUMENT = re.compile(r"'([^']*)'|\"([^\"]*)\"|(\S+)")


def resolve_listed_paths(command, items):
    """`command` with bare filenames swapped for their full paths, using the
    rows of the last listing.

    A follow-up like "open 08_IFOPE_20x30.jpg" becomes a command naming just
    the file, which the shell resolves against its own working directory —
    wherever it happens to have been started, never the folder the user was
    just looking at. Only an argument that matches a listed name in full is
    replaced, so a name that merely appears inside a longer string (a URL, a
    search phrase) is left as-is."""
    if not items:
        return command

    by_name = {}
    for item in items:
        by_name[item["name"].lower()] = item["path"]
        # Shortcuts are displayed without their .lnk/.url suffix, so that's the
        # name the user sees and refers back to.
        by_name.setdefault(display_name(item).lower(), item["path"])

    def swap(match):
        quoted_single, quoted_double, bare = match.groups()
        text = quoted_single if quoted_single is not None else (
            quoted_double if quoted_double is not None else bare
        )
        path = by_name.get(text.lower())
        # Parameters that take a name rather than a path are left alone —
        # expanding one to a full path would change what the command does
        # (PowerShell's -NewName, find's -name pattern).
        if path is None or current.NAME_PARAM.search(command[: match.start()]):
            return match.group(0)
        return current.quote(path)

    return _ARGUMENT.sub(swap, command)


def display_name(item):
    """Shortcuts lose their .lnk/.url suffix — that extension is plumbing, not
    part of the name anyone uses for the thing."""
    return item["name"] if item["dir"] else _SHORTCUT.sub("", item["name"])


def human_size(size):
    """Bytes as KB/MB/GB — three significant-ish digits, never a wall of digits."""
    if size is None:
        return ""
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            return f"{value:.1f} {unit}" if value < 10 else f"{value:.0f} {unit}"
        value /= 1024


def format_listing(items, kind="item"):
    """Two aligned columns for the console: name, then size."""
    if not items:
        return "Nothing there." if kind == "item" else f"No {kind}s there."
    rows = [
        (display_name(item) + (os.sep if item["dir"] else ""),
         "—" if item["dir"] else human_size(item["size"]))
        for item in items
    ]
    width = max(len(name) for name, _ in rows)
    return "\n".join(f"{name:<{width}}  {size:>9}" for name, size in rows)
