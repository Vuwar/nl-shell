"""The interface every platform implements, plus the parts that don't differ.

A Platform describes one operating system to the rest of ai_shell: how to run
a command in its shell, how to talk to the model about it, and how to find and
launch the applications installed on it. Anything with the same answer
everywhere lives here, so a platform module only has to state what is actually
different about its OS.
"""

import os
import re
import subprocess

# Matches nothing — the default for a pattern a platform hasn't got one for.
_NEVER = re.compile(r"(?!)")


class Platform:
    # --- describing this OS to the model ---------------------------------
    OS_NAME = ""        # "Windows", "macOS", "Linux"
    SHELL_NAME = ""     # "PowerShell", "bash"
    APP_SOURCE = ""     # where installed apps are listed: "Start Menu", ...
    JARGON = ""         # the mechanics a plain-English failure must not mention
    LISTING_RULE = ""   # how the model should write a directory listing
    EXAMPLES = ""       # worked examples, in this OS's shell and path style
    LAUNCH_NOTE = ""    # how the model should launch an application

    # Whether to prefer the backslash-repaired reading of the model's JSON.
    # Worth it only where paths are full of backslashes the model won't
    # escape; elsewhere it risks mangling an escape it did mean. See
    # llm._first_json.
    REPAIR_JSON_BACKSLASHES = False

    # Parameters that take a name rather than a path, so the argument after
    # one is never expanded to a full path (see listing.resolve_listed_paths).
    NAME_PARAM = _NEVER

    # A quoted absolute path inside a command — how the session works out
    # which folder it is now "in" (see session._remember_context).
    ABS_PATH = _NEVER

    # --- running commands -------------------------------------------------
    # Extra keyword arguments for every process this app starts — the shell
    # running a command, the app scan, the hardware probe, the model server.
    # Nothing to say on a Unix, where a child process is just a child
    # process; on Windows it is what keeps a console window off the user's
    # desktop (see windows.Platform.SPAWN_KWARGS). It lives here, on the
    # platform, because the alternative is remembering it at each call site
    # one at a time — which is how the app scan came to open a PowerShell
    # window in front of the panel while the background server, written with
    # the flag, had none.
    SPAWN_KWARGS = {}

    def shell_argv(self, command):
        """The argv that runs `command` in this OS's shell."""
        raise NotImplementedError

    def quote(self, text):
        """`text` as a single quoted literal this shell reads verbatim."""
        raise NotImplementedError

    def open_command(self, path):
        """A command that opens `path` in whatever app the OS uses for it."""
        raise NotImplementedError

    def strip_error_prefix(self, line):
        """A line of error output with the shell's own noise removed, used
        when the model isn't available to explain a failure in plain words."""
        return line

    def echoes_created_item(self, command, output):
        """True when the output is nothing but the thing the command just
        created, dumped in the shell's object-table format. The explanation
        shown above it already says what was made and where, so the interfaces
        show a plain "done" instead."""
        return False

    # --- background processes ----------------------------------------------
    def start_background(self, argv, log):
        """Start `argv` as a long-lived child, with its output going to the
        open file `log`. Returns (process, keepalive).

        The child must not outlive us. ai_shell.server stops it on the way
        out, but that only covers the exits we get to run code for — a crash,
        a kill from the task manager, or a hard power-cycle of the debugger
        all skip it, and what's left behind is a model server holding several
        gigabytes with no window to close it from. Every OS has its own way of
        saying "this process belongs to that one", so each platform tightens
        this as far as it can.

        `keepalive` is whatever must stay referenced for that link to hold;
        the caller keeps it alive and drops it only when the child is gone.
        This base version is the honest fallback: no link at all.
        """
        return subprocess.Popen(
            argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            **self.SPAWN_KWARGS,
        ), None

    # --- directory listings ----------------------------------------------
    def list_directory_command(self, path):
        """A command listing the contents of `path` — the interfaces' own
        folder navigation, where the user clicked a real folder."""
        raise NotImplementedError

    def project_listing(self, command):
        """`command` rewritten to emit output this platform's parse_listing
        can read, or None if it isn't a plain directory listing that can
        safely be re-run. Whatever comes back must be read-only: the session
        runs it and falls back to the original when it doesn't parse, so
        anything with a side effect could happen twice."""
        return None

    def parse_listing(self, stdout, cwd=None):
        """Rows for the output of a projected listing, or None when the
        output isn't one (the caller then shows the raw text). `cwd` is the
        folder the command ran in, for resolving relative paths."""
        return None

    def listing_kind(self, command):
        """What the listing was narrowed to — "folder", "file" or "item" — so
        a result can name it ("3 folders", or "No folders there", which is the
        readable answer to "is there any folder on the desktop?")."""
        return "item"

    # --- installed applications -------------------------------------------
    def list_apps(self):
        """Every installed application as a (name, launch_id) pair, or [] if
        the scan fails. `launch_id` is whatever this OS needs to start it."""
        return []

    def prepare_command(self, command, apps):
        """(command_to_run, problem) — a last chance to fix `command` before
        it runs. `problem` is a plain sentence when it can't work at all, and
        nothing is run."""
        return command, None

    def retry_command(self, command, result, apps):
        """A second command to try after `command` failed, or None. Used to
        launch an app the model named but couldn't locate."""
        return None

    # --- describing this machine -------------------------------------------
    # Not about the OS's conventions like the rest of this class, but about the
    # computer the app happens to be on: where its settings belong, and how
    # much model it can actually hold (see ai_shell.hardware).
    def config_dir(self):
        """The per-user folder this app keeps its settings in. The XDG default
        covers both POSIX platforms; Windows overrides it."""
        root = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(root, "ai-shell")

    def total_ram_gb(self):
        """Physical RAM in GB, or None when it can't be read. None is a real
        answer here — every caller treats "unknown" as "don't get clever" and
        falls back to a model known to run on an ordinary laptop."""
        return None

    def vram_gb(self):
        """Dedicated GPU memory in GB, or None when there's no discrete GPU
        this can see.

        Only NVIDIA is probed, because nvidia-smi is the one vendor tool that
        ships wherever the GPU does. Guessing wrong costs a smaller default
        model, not a broken one, so the missing AMD case degrades to the RAM
        answer rather than to an error.

        The largest single GPU, not the total: llama.cpp puts the model on one
        device unless it's told to split, so two 8GB cards are not 16GB.
        """
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, timeout=10, **self.SPAWN_KWARGS,
                # Numbers, so the encoding hardly matters — but text=True
                # decodes strictly under the locale, and a probe that decides
                # how much of the model goes on the GPU should not be able to
                # fail over a byte in a driver's product name.
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.SubprocessError):
            return None
        sizes = [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
        return max(sizes) / 1024 if sizes else None

    # --- shared helpers ----------------------------------------------------
    def context_paths(self, command):
        """Every absolute path `command` names, in the order they appear."""
        found = []
        for match in self.ABS_PATH.finditer(command):
            path = next((group for group in match.groups() if group), None)
            if path:
                found.append(path)
        return found

    def row(self, path, is_dir, size, modified):
        """One row of a directory listing, as the interfaces expect it."""
        return {
            "dir": is_dir,
            # Folders have no meaningful size of their own.
            "size": None if is_dir else size,
            "modified": modified,
            "name": os.path.basename(path.rstrip("\\/")) or path,
            "path": path,
        }

    def split_pipeline(self, command):
        """Splits on top-level `|` only — a pipe inside quotes or a nested
        block belongs to the stage, not between stages."""
        stages, buf, quote, depth = [], [], None, 0
        for ch in command:
            if quote:
                buf.append(ch)
                if ch == quote:
                    quote = None
                continue
            if ch in "'\"":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "|" and depth == 0:
                stages.append("".join(buf))
                buf = []
                continue
            buf.append(ch)
        stages.append("".join(buf))
        return stages

    def resolve_app(self, app_name, apps):
        """The launch id of the installed app called `app_name`, or None.

        The model can only guess where an app lives, and guesses go stale. The
        OS's own list of installed applications finds the real launch target
        regardless. Matching is against the app name the command tried to
        start — never the user's whole sentence — so this can only relocate
        that same app, not swap in a different one."""
        target = re.sub(r"[^a-z0-9]", "", re.sub(r"\.(exe|app)$", "", app_name.lower()))
        if not target:
            return None
        for name, launch_id in apps or []:
            normalized = re.sub(r"[^a-z0-9]", "", name.lower())
            if normalized and (target in normalized or normalized in target):
                return launch_id
        return None
