"""macOS: bash, `open -a` for applications, .app bundles under /Applications."""

import os
import platform
import re
import subprocess

from ai_shell.platforms.posix import Posix

# Where installed applications live. Each is scanned one level deep as well,
# for the grouping folders Apple and installers use (Utilities, Adobe, ...).
_APP_ROOTS = (
    "/Applications",
    "/System/Applications",
    "~/Applications",
)

# open -a 'Google Chrome' | open -a Safari | open -na "Visual Studio Code"
_LAUNCH_TARGET = re.compile(r"""\bopen\b[^|]*?\s-\w*a\s+(?:'([^']*)'|"([^"]*)"|(\S+))""")


class MacOS(Posix):
    OS_NAME = "macOS"
    APP_SOURCE = "Applications folder"
    JARGON = "bash, the shell, commands, flags, exit codes, or syntax"

    EXAMPLES = r"""Example — risky request:
User: delete the file called old_notes.txt
{"command": "rm 'old_notes.txt'", "risk": "risky", "explanation": "Permanently deletes old_notes.txt."}

Example — opening/launching a specific, named application:
User: open safari
{"command": "open -a 'Safari'", "risk": "safe", "explanation": "Launches Safari."}

Example — yes/no question about files (list the matches, don't test each item):
User: is there any folder on the desktop
{"command": "find \"$HOME/Desktop\" -maxdepth 1 -mindepth 1 -type d ! -name '.*'", "risk": "safe", "explanation": "Lists the folders on your desktop."}

Example — follow-up referring to an earlier result (reuse the path from the note):
Note: (context from the shell, not the user) Ran: find '/Users/me/Desktop/Photos' -maxdepth 1 -mindepth 1 — Listed 12 items... Folder in context: /Users/me/Desktop/Photos
User: now zip that
{"command": "zip -r '/Users/me/Desktop/Photos.zip' '/Users/me/Desktop/Photos'", "risk": "safe", "explanation": "Zips the Photos folder next to itself."}

Example — vague target (ask, don't guess):
User: open a browser
{"command": null, "risk": null, "explanation": "Which browser would you like me to open?", "options": ["Safari", "Google Chrome", "Firefox"]}

Example — something only the internet can answer (search, never refuse):
User: what's the latest version of python
{"command": null, "search": "latest Python version release", "risk": null, "explanation": "Looking that up on the web.", "options": null}

Example — about this computer, not the world (a command, not a search):
User: how much disk space have I got left
{"command": "df -h /", "search": null, "risk": "safe", "explanation": "Shows the free space on your main drive.", "options": null}

Example — small talk, even with earlier results in the conversation (just
answer; the user asked for nothing, so there is nothing to offer):
Note: (context from the shell, not the user) Ran: find '/Users/me/Desktop' -maxdepth 1 -mindepth 1 — Listed 8 items... Folder in context: /Users/me/Desktop
User: hey
{"command": null, "risk": null, "explanation": "Hey! Tell me what you'd like to do and I'll take care of it.", "options": null}
"""

    LAUNCH_NOTE = """Requests to open, launch, start, or run a specific, named application are
always valid, safe shell requests — never refuse those. Start one with
`open -a '<App Name>'`, using the name the user said; if it's installed
under a slightly different name the shell has its own fallback to find that
same app. But when the user hasn't named which app they mean, ask — the
fallback can only launch the app you name, so a wrong guess fails instead
of opening something else."""

    def open_command(self, path):
        # `open` hands the file to whatever app is registered for it and
        # returns straight away, so nothing waits on the app being closed.
        return f"open {self.quote(path)}"

    # --- describing this machine -------------------------------------------
    def total_ram_gb(self):
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            return int(result.stdout.strip()) / (1024 ** 3)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def vram_gb(self):
        """Apple Silicon has no separate VRAM — the GPU works out of the same
        pool as everything else, and Metal will hand a large share of it to
        one process. Reporting that share as VRAM is what lets an M-series Mac
        pick the model its memory can genuinely hold rather than the
        conservative CPU-sized one nvidia-smi's silence would imply.

        Intel Macs fall through to the base probe, which finds nothing and
        leaves the choice to RAM — correct, as their GPUs aren't worth
        offloading to."""
        if platform.machine() != "arm64":
            return super().vram_gb()
        ram = self.total_ram_gb()
        # macOS reserves the rest for the system; this is roughly what
        # iogpu.wired_limit_pct allows by default on consumer configurations.
        return ram * 0.7 if ram else None

    def vram_is_shared(self):
        # True only where vram_gb actually returned the unified-memory share;
        # an Intel Mac falls through to the base probe and a real card.
        return platform.machine() == "arm64"

    # --- installed applications -------------------------------------------
    def list_apps(self):
        apps = []
        for root in _APP_ROOTS:
            root = os.path.expanduser(root)
            for entry in self._scan(root):
                if entry.name.endswith(".app"):
                    apps.append((entry.name[: -len(".app")], entry.path))
                elif entry.is_dir():
                    apps.extend(
                        (sub.name[: -len(".app")], sub.path)
                        for sub in self._scan(entry.path)
                        if sub.name.endswith(".app")
                    )
        return apps

    @staticmethod
    def _scan(path):
        try:
            with os.scandir(path) as entries:
                return sorted(entries, key=lambda e: e.name)
        except OSError:
            return []

    def retry_command(self, command, result, apps):
        """`open -a` matches on the app's registered name, which isn't always
        the name people call it. The Applications folder has the real bundle,
        and pointing `open` straight at that path skips the name lookup."""
        if isinstance(result, Exception) or result.returncode == 0:
            return None
        if "unable to find application" not in (result.stderr or "").lower():
            return None
        match = _LAUNCH_TARGET.search(command)
        target = next((g for g in match.groups() if g), None) if match else None
        bundle = self.resolve_app(target, apps) if target else None
        return f"open -a {self.quote(bundle)}" if bundle else None
