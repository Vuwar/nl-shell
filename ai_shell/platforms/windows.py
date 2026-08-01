"""Windows: PowerShell, Start Menu applications, drive-letter paths."""

import ctypes
import os
import re
import subprocess

from ai_shell.platforms.base import Platform

# Only these can lead a listing pipeline: they emit the file objects the
# projection reads properties off, AND they're read-only.
_HEAD = re.compile(r"^\s*(get-childitem|gci|ls|dir|get-item|gi)\b", re.IGNORECASE)
# ...and only these may follow, because they pass those objects through
# unchanged. Anything else (Measure-Object, Format-Table, Select-Object with a
# property list) leaves the pipeline emitting something the projection can't
# read, so the whole rewrite is abandoned and the raw output is used instead.
_SAFE_STAGE = re.compile(r"^\s*(sort-object|sort|where-object|where|\?)\b", re.IGNORECASE)

_PROJECTION = (
    ' | ForEach-Object { "$($_.PSIsContainer)`t$($_.Length)`t'
    "$($_.LastWriteTime.ToString('o'))`t$($_.FullName)\" }"
)

# -Directory/-File and their aliases, which narrow a listing to one or the other.
_ONLY_DIRS = re.compile(r"\s-(?:directory|ad)\b", re.IGNORECASE)
_ONLY_FILES = re.compile(r"\s-(?:file|af)\b", re.IGNORECASE)

# Start-Process 'Opera GX' | Start-Process -FilePath "msedge" | Start-Process notepad
_LAUNCH_TARGET = re.compile(
    r"Start-Process\s+(?:-FilePath\s+)?(?:['\"]([^'\"]+)['\"]|([^\s'\"-]\S*))"
)

# Commands that create or move something and then echo the result back.
_CREATES_ITEM = re.compile(
    r"^\s*(new-item|ni|mkdir|md|copy-item|cpi|copy|move-item|mi|move|rename-item|rni|ren)\b",
    re.IGNORECASE,
)
# The header of PowerShell's file-object table.
_OBJECT_DUMP = re.compile(r"^Mode\s+LastWriteTime\s+.*\bName\s*$", re.MULTILINE)


# See SPAWN_KWARGS.
_CREATE_NO_WINDOW = 0x08000000

# Job-object plumbing for start_background. A job with KILL_ON_JOB_CLOSE set
# terminates every process in it the moment the last handle to the job goes
# away — including when that happens because the owning process died without
# cleaning up, which is exactly the case an atexit hook can't cover.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobBasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_ulong),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_ulong),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_ulong),
        ("SchedulingClass", ctypes.c_ulong),
    ]


class _JobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobHandle:
    """Owns a job handle, and closes it — killing the job's processes — when
    it's dropped. Being an object rather than a bare handle is the point: the
    caller holding a reference is what keeps the server alive, so the link
    can't be lost by forgetting to store an integer somewhere."""

    def __init__(self, handle):
        self._handle = handle

    def close(self):
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None

    __del__ = close


class _MemoryStatusEx(ctypes.Structure):
    """MEMORYSTATUSEX, for GlobalMemoryStatusEx. Every field has to be declared
    even though only ullTotalPhys is read — the call writes the whole struct
    and validates dwLength against its own idea of the size."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class Windows(Platform):
    OS_NAME = "Windows"
    SHELL_NAME = "PowerShell"
    APP_SOURCE = "Start Menu"
    JARGON = "PowerShell, commands, cmdlets, exit codes, or syntax"

    # Local models routinely paste Windows paths straight into the JSON
    # ($env:USERPROFILE\Desktop, C:\temp), where \D is an invalid escape that
    # kills the whole parse and \t silently turns into a tab inside the
    # command. Repairing those is worth more here than the escapes it risks.
    REPAIR_JSON_BACKSLASHES = True

    NAME_PARAM = re.compile(r"-(?:name|newname)\s*$", re.IGNORECASE)
    ABS_PATH = re.compile(r"['\"]([a-zA-Z]:\\[^'\"]*)['\"]")

    LISTING_RULE = (
        "Answer yes/no questions about files or folders by listing the things "
        "that match\n   — Get-ChildItem with -Directory, -File or -Filter — so "
        "an empty result\n   means \"no\" and a non-empty one shows what was "
        "found. Never test each item\n   in a loop into a column of booleans."
    )

    EXAMPLES = """Example — risky request:
User: delete the file called old_notes.txt
{"command": "Remove-Item -Path 'old_notes.txt'", "risk": "risky", "explanation": "Permanently deletes old_notes.txt."}

Example — opening/launching a specific, named application:
User: open opera gx
{"command": "Start-Process 'Opera GX'", "risk": "safe", "explanation": "Launches Opera GX."}

Example — yes/no question about files (list the matches, don't test each item):
User: is there any folder on the desktop
{"command": "Get-ChildItem -Path $env:USERPROFILE\\Desktop -Directory", "risk": "safe", "explanation": "Lists the folders on your desktop."}

Example — follow-up referring to an earlier result (reuse the path from the note):
Note: (context from the shell, not the user) Ran: Get-ChildItem -Path C:\\Users\\Me\\Desktop\\Photos — Listed 12 items... Folder in context: C:\\Users\\Me\\Desktop\\Photos
User: now zip that
{"command": "Compress-Archive -Path 'C:\\Users\\Me\\Desktop\\Photos' -DestinationPath 'C:\\Users\\Me\\Desktop\\Photos.zip'", "risk": "safe", "explanation": "Zips the Photos folder next to itself."}

Example — vague target (ask, don't guess):
User: open a browser
{"command": null, "risk": null, "explanation": "Which browser would you like me to open?", "options": ["Opera GX", "Microsoft Edge", "Google Chrome"]}

Example — something only the internet can answer (search, never refuse):
User: what's the latest version of python
{"command": null, "search": "latest Python version release", "risk": null, "explanation": "Looking that up on the web.", "options": null}

Example — about this computer, not the world (a command, not a search):
User: how much disk space have I got left
{"command": "Get-PSDrive -PSProvider FileSystem | ForEach-Object { \\"$($_.Name): $([math]::Round($_.Free/1GB,1)) GB free\\" }", "search": null, "risk": "safe", "explanation": "Shows the free space on each drive.", "options": null}

Example — small talk, even with earlier results in the conversation (just
answer; the user asked for nothing, so there is nothing to offer):
Note: (context from the shell, not the user) Ran: Get-ChildItem -Path C:\\Users\\Me\\Desktop — Listed 8 items... Folder in context: C:\\Users\\Me\\Desktop
User: hey
{"command": null, "risk": null, "explanation": "Hey! Tell me what you'd like to do and I'll take care of it.", "options": null}
"""

    LAUNCH_NOTE = """Requests to open, launch, start, or run a specific, named application are
always valid, safe shell requests — never refuse those. Use the app's name
as the Start-Process target; if the exact path differs the shell has its
own fallback to find that same app. But when the user hasn't named which
app they mean, ask — the fallback can only launch the app you name, so a
wrong guess fails instead of opening something else."""

    # --- running commands -------------------------------------------------
    # CREATE_NO_WINDOW, on everything this app starts.
    #
    # The desktop app is a windowed binary with no console of its own, so
    # Windows gives every console child a brand new one — and on Windows 11
    # that console is hosted by Windows Terminal, which means a full terminal
    # window, tabs and all, appearing over the desktop. The installed-app
    # scan runs from Session.__init__, before the panel is drawn, so without
    # this flag the first thing a user sees after launching the app is a
    # PowerShell window they never asked for; every confirmed command then
    # flashes another.
    #
    # Costs nothing where there is a console already: the CLI's children
    # write to captured pipes, not to the console it took the flag from.
    SPAWN_KWARGS = {"creationflags": _CREATE_NO_WINDOW}

    def shell_argv(self, command):
        # The preamble is not cosmetic. Windows PowerShell writes redirected
        # output in the console's OEM codepage, so a filename or an app name
        # containing anything outside ASCII comes back as bytes whose meaning
        # depends on the machine's regional settings — and the caller, reading
        # them as text, has no way to know which codepage it got. Pinning the
        # output to UTF-8 makes what we read the same on every machine.
        #
        # Found via an app literally called "WPS<NBSP>Docs": the non-breaking
        # space arrives as 0xFF in codepage 437, which decodes under cp1252 as
        # "WPSÿDocs" and under UTF-8 not at all.
        #
        # Prepended here rather than folded into the command itself, so the
        # command string stays the one the model wrote and the user is shown.
        return [
            "powershell", "-NoProfile", "-Command",
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + command,
        ]

    def quote(self, text):
        """A single-quoted PowerShell string, where the only character needing
        an escape is the quote itself, doubled."""
        return "'" + text.replace("'", "''") + "'"

    def open_command(self, path):
        return f"Start-Process -FilePath {self.quote(path)}"

    def strip_error_prefix(self, line):
        # PowerShell errors lead with the cmdlet name ("Start-Process : ...");
        # drop that prefix so the user sees only the OS's actual reason.
        _, sep, rest = line.partition(" : ")
        return rest if sep else line

    def echoes_created_item(self, command, output):
        """Making a folder shouldn't answer with an attribute-flag table. Both
        halves have to match: read-only commands can legitimately produce that
        table as their actual answer, and that must never be swallowed."""
        return bool(_CREATES_ITEM.match(command) and _OBJECT_DUMP.search(output))

    # --- background processes ----------------------------------------------
    def start_background(self, argv, log):
        """SPAWN_KWARGS' CREATE_NO_WINDOW so a console doesn't flash over the
        desktop panel every launch, plus a kill-on-close job object so the
        child can't be orphaned.

        Failing to build the job is not fatal. It's the safety net, not the
        mechanism — and it legitimately fails where we're already inside
        someone else's job that forbids nesting, which some sandboxes and CI
        runners do. A server that might outlive a crash beats no server."""
        kernel32 = ctypes.windll.kernel32
        process = subprocess.Popen(
            argv,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            **self.SPAWN_KWARGS,
        )

        job = None
        handle = None
        try:
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                raise OSError("CreateJobObject failed")

            limits = _JobExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                job,
                _JobObjectExtendedLimitInformation,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise OSError("SetInformationJobObject failed")

            # OpenProcess rather than Popen's private _handle: same handle,
            # public API, and the quota right is the one AssignProcessToJob
            # actually requires.
            handle = kernel32.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, process.pid
            )
            if not handle:
                raise OSError("OpenProcess failed")
            if not kernel32.AssignProcessToJobObject(job, handle):
                raise OSError("AssignProcessToJobObject failed")
            return process, _JobHandle(job)
        except OSError:
            if job:
                kernel32.CloseHandle(job)
            return process, None
        finally:
            if handle:
                kernel32.CloseHandle(handle)

    # --- describing this machine -------------------------------------------
    def config_dir(self):
        return os.path.join(
            os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming"),
            "ai-shell",
        )

    def total_ram_gb(self):
        """GlobalMemoryStatusEx rather than shelling out to PowerShell: this
        runs before the first window is drawn, and a PowerShell start-up is
        most of a second the user would spend looking at nothing."""
        try:
            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.ullTotalPhys / (1024 ** 3)
        except (OSError, AttributeError):
            return None

    # --- directory listings ----------------------------------------------
    def list_directory_command(self, path):
        # -LiteralPath so a folder named with brackets isn't read as a wildcard.
        return f"Get-ChildItem -LiteralPath {self.quote(path)}"

    def project_listing(self, command):
        """Get-ChildItem prints for a console: a `Mode` attribute-flag column,
        sizes in raw bytes, and a timestamp on every row whether or not anyone
        wanted one. Re-projecting it to tab-separated fields lets the
        interfaces present rows instead of pre-formatted text."""
        # `;` would put the projection on the last statement only, which may
        # not be the listing the user is looking at.
        if ";" in command:
            return None
        stages = self.split_pipeline(command)
        if not _HEAD.match(stages[0]):
            return None
        if not all(_SAFE_STAGE.match(stage) for stage in stages[1:]):
            return None
        return command.strip() + _PROJECTION

    def parse_listing(self, stdout, cwd=None):
        items = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            if len(fields) != 4:
                return None
            is_dir, size, modified, path = (f.strip() for f in fields)
            # No FullName means this wasn't a file at all — Get-Item can just
            # as well be pointed at a registry key or an environment variable,
            # whose properties come back empty. Raw output is the honest
            # answer there.
            if not path:
                return None
            items.append(
                self.row(
                    path,
                    is_dir.lower() == "true",
                    int(size) if size.isdigit() else None,
                    modified or None,
                )
            )
        return items

    def listing_kind(self, command):
        if _ONLY_DIRS.search(command):
            return "folder"
        if _ONLY_FILES.search(command):
            return "file"
        return "item"

    # --- installed applications -------------------------------------------
    def list_apps(self):
        """The Start Menu's own index — the same one the Start Menu searches."""
        script = 'Get-StartApps | ForEach-Object { "$($_.Name)|$($_.AppID)" }'
        try:
            result = subprocess.run(
                self.shell_argv(script), capture_output=True, timeout=15,
                encoding="utf-8", errors="replace", **self.SPAWN_KWARGS,
            )
        except Exception:
            return []
        # `or ""`, because the try above cannot be relied on to have caught a
        # decoding failure: subprocess decodes on a reader thread, so the
        # exception is raised there and surfaces here only as stdout being
        # None. That is what made a stray byte in one app's name an
        # AttributeError deep in a background thread rather than a caught
        # error — the scan died and app launching stopped working, silently.
        apps = []
        for line in (result.stdout or "").splitlines():
            name, sep, app_id = line.partition("|")
            if sep and name.strip() and app_id.strip():
                apps.append((name.strip(), app_id.strip()))
        return apps

    def retry_command(self, command, result, apps):
        """Start-Process couldn't find what it was pointed at, so look the app
        up in the Start Menu index instead — the model can only guess at
        install paths, and per-user LOCALAPPDATA installs defeat those guesses."""
        if (
            isinstance(result, Exception)
            or result.returncode == 0
            or "Start-Process" not in command
            or "cannot find the file specified" not in (result.stderr or "").lower()
        ):
            return None
        match = _LAUNCH_TARGET.search(command)
        target = (match.group(1) or match.group(2)) if match else None
        app_id = self.resolve_app(target, apps) if target else None
        return f"Start-Process 'shell:AppsFolder\\{app_id}'" if app_id else None
