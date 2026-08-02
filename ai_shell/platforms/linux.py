"""Linux: bash, .desktop entries for applications, xdg-open for files."""

import ctypes
import os
import re
import shutil
import signal
import subprocess

from ai_shell.platforms.posix import Posix

_PR_SET_PDEATHSIG = 1


def _die_with_parent():
    """Runs in the forked child, before exec. Best-effort: a libc without
    prctl leaves the child merely un-tethered, which is the same place every
    other platform starts from."""
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)
    except OSError:
        pass

# A backgrounded launch - the form the model is told to use, and the only
# shape of command treated as "start an application". A trailing `&&` is a
# chain, not a background job.
_BACKGROUNDED = re.compile(r"(?<!&)&\s*$")
# Wrappers that come before the program itself.
_WRAPPERS = re.compile(r"^\s*(?:nohup\s+|setsid\s+|env\s+\w+=\S+\s+)*")

# Field codes a .desktop Exec line passes to the program (%f is the file it
# was opened with, and so on). There is nothing to substitute when launching
# an app on its own, so they come out.
_FIELD_CODES = re.compile(r"\s*%[fFuUdDnNickvm]\b")

# Tools this shell puts in launch position itself. A missing one is a broken
# desktop environment, not an app the user asked for by name, so it must not
# be reported as "no such application".
_NOT_AN_APP = {"xdg-open", "gio", "gtk-launch"}


class Linux(Posix):
    OS_NAME = "Linux"
    APP_SOURCE = "installed applications"
    JARGON = "bash, the shell, commands, flags, exit codes, or syntax"

    EXAMPLES = r"""Example - risky request:
User: delete the file called old_notes.txt
{"command": "rm 'old_notes.txt'", "risk": "risky", "explanation": "Permanently deletes old_notes.txt."}

Example - opening/launching a specific, named application:
User: open firefox
{"command": "nohup firefox >/dev/null 2>&1 &", "risk": "safe", "explanation": "Launches Firefox."}

Example - yes/no question about files (list the matches, don't test each item):
User: is there any folder on the desktop
{"command": "find \"$HOME/Desktop\" -maxdepth 1 -mindepth 1 -type d ! -name '.*'", "risk": "safe", "explanation": "Lists the folders on your desktop."}

Example - follow-up referring to an earlier result (reuse the path from the note):
Note: (context from the shell, not the user) Ran: find '/home/me/Desktop/Photos' -maxdepth 1 -mindepth 1 - Listed 12 items... Folder in context: /home/me/Desktop/Photos
User: now zip that
{"command": "zip -r '/home/me/Desktop/Photos.zip' '/home/me/Desktop/Photos'", "risk": "safe", "explanation": "Zips the Photos folder next to itself."}

Example - vague target (ask, don't guess):
User: open a browser
{"command": null, "risk": null, "explanation": "Which browser would you like me to open?", "options": ["Firefox", "Google Chrome", "Chromium"]}

Example - something only the internet can answer (search, never refuse):
User: what's the latest version of python
{"command": null, "search": "latest Python version release", "risk": null, "explanation": "Looking that up on the web.", "options": null}

Example - about this computer, not the world (a command, not a search):
User: how much disk space have I got left
{"command": "df -h /", "search": null, "risk": "safe", "explanation": "Shows the free space on your main drive.", "options": null}

Example - small talk, even with earlier results in the conversation (just
answer; the user asked for nothing, so there is nothing to offer):
Note: (context from the shell, not the user) Ran: find '/home/me/Desktop' -maxdepth 1 -mindepth 1 - Listed 8 items... Folder in context: /home/me/Desktop
User: hey
{"command": null, "risk": null, "explanation": "Hey! Tell me what you'd like to do and I'll take care of it.", "options": null}
"""

    LAUNCH_NOTE = """Requests to open, launch, start, or run a specific, named application are
always valid, safe shell requests - never refuse those. Start one as
`nohup <program> >/dev/null 2>&1 &` - the `&` matters, because without it
the shell waits for the app to be closed again and the user gets nothing
back. Use the program's usual command name; if it isn't installed under
that name the shell has its own fallback to find that same app. But when
the user hasn't named which app they mean, ask - the fallback can only
launch the app you name, so a wrong guess fails instead of opening
something else."""

    def open_command(self, path):
        # Backgrounded because xdg-open blocks for the whole life of whatever
        # it starts, and the interfaces would sit waiting on it.
        return f"nohup xdg-open {self.quote(path)} >/dev/null 2>&1 &"

    # --- background processes ----------------------------------------------
    def start_background(self, argv, log):
        """PR_SET_PDEATHSIG in the child, which is Linux's version of the
        guarantee: the kernel signals it the moment its parent dies, however
        the parent died. macOS has no equivalent, which is why this is here
        and not in posix.py."""
        return subprocess.Popen(
            argv,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            preexec_fn=_die_with_parent,
        ), None

    # --- describing this machine -------------------------------------------
    def total_ram_gb(self):
        try:
            with open("/proc/meminfo", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        # MemTotal is in kB, whatever the kernel's page size.
                        return int(line.split()[1]) / (1024 ** 2)
        except (OSError, ValueError, IndexError):
            pass
        return None

    # --- installed applications -------------------------------------------
    def list_apps(self):
        """Names and launch commands from the .desktop files the desktop
        environment itself uses to populate its application menu."""
        apps, seen = [], set()
        for directory in self._app_dirs():
            try:
                names = sorted(os.listdir(directory))
            except OSError:
                continue
            for filename in names:
                if not filename.endswith(".desktop") or filename in seen:
                    continue
                seen.add(filename)  # earlier directories win, as XDG requires
                entry = self._read_desktop_entry(os.path.join(directory, filename))
                if entry:
                    apps.append(entry)
        return apps

    @staticmethod
    def _app_dirs():
        """The XDG application directories, most specific first."""
        home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        shared = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
        roots = [home] + [d for d in shared.split(":") if d]
        # Snap and Flatpak put their entries outside XDG_DATA_DIRS on some
        # distributions, and those are exactly the apps a user installed.
        extra = ["/var/lib/snapd/desktop", "/var/lib/flatpak/exports/share"]
        return [os.path.join(root, "applications") for root in roots + extra]

    @staticmethod
    def _read_desktop_entry(path):
        """(name, launch command) for a .desktop file, or None if it isn't a
        visible graphical application."""
        fields, in_entry = {}, False
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if line.startswith("["):
                        # Only the first section describes the app itself; the
                        # rest are extra right-click actions.
                        if in_entry:
                            break
                        in_entry = line == "[Desktop Entry]"
                    elif in_entry and "=" in line:
                        key, _, value = line.partition("=")
                        fields.setdefault(key.strip(), value.strip())
        except OSError:
            return None

        if fields.get("Type", "Application") != "Application":
            return None
        if fields.get("NoDisplay", "").lower() == "true" or fields.get("Hidden", "").lower() == "true":
            return None
        # A terminal program started with no terminal attached just vanishes.
        if fields.get("Terminal", "").lower() == "true":
            return None

        name = fields.get("Name", "").strip()
        exec_line = _FIELD_CODES.sub("", fields.get("Exec", "")).replace("%%", "%").strip()
        return (name, exec_line) if name and exec_line else None

    def prepare_command(self, command, apps):
        """Swaps a launch for one that will actually work.

        Unlike Windows and macOS there is no launcher to report back that an
        app is missing: the model writes the program name directly, and a
        backgrounded name that doesn't exist fails silently in a subshell that
        has already been disowned. So the check happens before anything runs -
        if the name isn't on PATH, the desktop entries say how that app is
        really started, and if they don't have it either, nothing is run and
        the user is told why."""
        target = self._launch_target(command)
        if not target or shutil.which(target):
            return command, None
        if target in _NOT_AN_APP:
            return command, None
        exec_line = self.resolve_app(target, apps)
        if exec_line:
            return f"nohup {exec_line} >/dev/null 2>&1 &", None
        return command, f"There is no application called '{target}' installed on this computer."

    @staticmethod
    def _launch_target(command):
        """The program a backgrounded command is trying to start, or None."""
        if not _BACKGROUNDED.search(command):
            return None
        rest = _WRAPPERS.sub("", command).lstrip()
        token = rest.split()[0] if rest.split() else ""
        token = token.strip("'\"")
        # A redirection or an assignment in first position isn't a program.
        return token if token and not re.match(r"[-<>&|]|\w+=", token) else None
