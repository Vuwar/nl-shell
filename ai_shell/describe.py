"""What a command does, written out for someone who can't read commands.

The confirmation exists so a person can decide, and it was handing them this:

    if ((Get-Service -Name 'bthserv' -ErrorAction SilentlyContinue).Status
    -eq 'Running') { Stop-Service -Name 'bthserv' } else { Start-Service
    -Name 'bthserv' }

    Run this? It can't easily be undone.

Anyone who can read that doesn't need this app. Anyone who can't is being
asked to approve something they cannot evaluate, under a warning that it
can't be undone - which doesn't inform them, it frightens them into picking a
button at random. Both outcomes are bad: a scared user cancels things that
were fine, and a worn-down user clicks Run on everything.

So the command is taken apart the same way ai_shell.policy takes it apart -
same clause splitting, same quote handling, same verb normalising - and each
verb it recognises becomes a line of plain English naming what that step does
and what it does it to.

No model. This sits underneath a command the model has already written, and
asking it to describe its own work costs another round trip and can produce a
description that doesn't match the command printed above it. A table cannot
drift from what is on the screen.

Deliberately partial. A verb with no phrase written for it contributes no
line, and a command nobody can describe produces nothing at all - the
confirmation then reads exactly as it did before this existed. That is the
right failure: no description is a worse confirmation, a wrong one is a
dangerous confirmation.
"""

from ai_shell import policy

# How many lines a confirmation is allowed to grow to. A wall of text is the
# thing this is trying to fix, not a milder version of it.
MAX_LINES = 5

# verb -> how to say it, as "<phrase> <what it was pointed at>". Written to
# follow "This ", so they read as a list of what happens: "Deletes notes.txt".
#
# Only verbs whose meaning is the same every time. Anything whose effect
# depends on flags nobody here reads is left out rather than described
# approximately.
_PHRASES = {
    # removing things
    "remove-item": "Deletes", "ri": "Deletes", "del": "Deletes",
    "erase": "Deletes", "rd": "Deletes", "rm": "Deletes", "rmdir": "Deletes",
    "unlink": "Deletes", "shred": "Permanently shreds",
    "clear-content": "Empties", "clc": "Empties",
    "remove-itemproperty": "Deletes a setting from",
    # moving and copying
    "move-item": "Moves", "mi": "Moves", "move": "Moves", "mv": "Moves",
    "rename-item": "Renames", "rni": "Renames", "ren": "Renames",
    "copy-item": "Copies", "cpi": "Copies", "copy": "Copies", "cp": "Copies",
    "robocopy": "Copies", "xcopy": "Copies", "rsync": "Copies",
    # making things
    "new-item": "Creates", "ni": "Creates", "mkdir": "Creates a folder",
    "md": "Creates a folder", "touch": "Creates",
    "compress-archive": "Zips", "zip": "Zips",
    "expand-archive": "Unzips", "unzip": "Unzips", "tar": "Unpacks",
    # writing
    "set-content": "Overwrites", "out-file": "Writes to",
    "add-content": "Adds to", "ac": "Adds to",
    "set-itemproperty": "Changes a setting on",
    "new-itemproperty": "Adds a setting to",
    # looking
    "get-childitem": "Lists what's in", "gci": "Lists what's in",
    "ls": "Lists what's in", "dir": "Lists what's in",
    "get-item": "Looks up", "gi": "Looks up",
    "get-content": "Reads", "cat": "Reads", "type": "Reads", "gc": "Reads",
    "get-service": "Looks up the service", "get-process": "Looks up the program",
    "get-command": "Looks for the program", "where.exe": "Looks for the program",
    "get-date": "Shows the date and time",
    "test-path": "Checks whether it exists:",
    "select-string": "Searches for text in", "findstr": "Searches for text in",
    "grep": "Searches for text in",
    # services and programs
    "stop-service": "Stops the service", "start-service": "Starts the service",
    "restart-service": "Restarts the service",
    "set-service": "Changes the service",
    "stop-process": "Closes the program", "kill": "Closes the program",
    "taskkill": "Closes the program", "spps": "Closes the program",
    "pkill": "Closes the program", "killall": "Closes the program",
    "start-process": "Opens", "saps": "Opens", "open": "Opens",
    "xdg-open": "Opens", "explorer": "Opens",
    # the machine
    "shutdown": "Shuts the computer down", "restart-computer": "Restarts the computer",
    "stop-computer": "Shuts the computer down", "reboot": "Restarts the computer",
    # the wider world
    "curl": "Downloads", "wget": "Downloads", "irm": "Downloads",
    "iwr": "Downloads", "invoke-webrequest": "Downloads",
    "invoke-restmethod": "Downloads",
    "sh": "Runs it as a script", "bash": "Runs it as a script",
    "iex": "Runs it as a script", "invoke-expression": "Runs it as a script",
    "powershell": "Runs it as a script", "pwsh": "Runs it as a script",
    "cmd": "Runs it as a script",
    # permissions and setup
    "icacls": "Changes who can open", "chmod": "Changes who can open",
    "chown": "Changes who owns", "takeown": "Takes ownership of",
    "reg": "Changes the Windows registry", "regedit": "Opens the Windows registry",
    "set-executionpolicy": "Changes which scripts Windows will run",
    "netsh": "Changes network settings",
    "schtasks": "Changes what runs on a schedule",
}

# Parameters whose value is a name or a path - the thing the verb acts on.
# Checked before falling back to the first bare argument, because
# `Remove-Item -Force -Path 'x'` should say x rather than -Force.
_TARGET_FLAGS = (
    "-path", "-literalpath", "-filepath", "-name", "-fullname", "-target",
    "-destination", "-destinationpath", "-newname", "-inputobject",
)


def describe(command):
    """What `command` does, as plain-English lines. [] when it can't say.

    One line per thing that happens, in the order it happens, with duplicates
    dropped - the toggle in the module docstring genuinely both stops and
    starts a service, and says so, but a loop deleting twenty files says
    "deletes" once.

    Every verb is looked for, not just the one at the front of each clause.
    That is the difference between this and ai_shell.policy, which asks "what
    does this command run" and can stop at the first answer. A description has
    to account for all of it: the interesting verbs in the reported command
    were both inside braces, where a clause head never reaches.
    """
    if not command or not command.strip():
        return []

    steps = _steps(command)
    lines = []
    for index, (phrase, position) in enumerate(steps):
        target = _target(command, position, steps[index + 1][1] if index + 1 < len(steps) else None)
        line = f"{phrase} {target}".strip() if target else phrase
        if line not in lines:
            lines.append(line)
        if len(lines) >= MAX_LINES:
            break
    return lines


def _steps(command):
    """Every recognised verb in `command`, as (phrase, where it started).

    A token that was written in quotes is never a verb, however much it looks
    like one: `Write-Output 'Remove-Item x'` prints a string and deletes
    nothing. Same protection ai_shell.policy has, by the same reasoning.
    """
    found = []
    for match in policy._TOKEN.finditer(command):
        token = match.group(0)
        if token[:1] in "'\"":
            continue
        phrase = _PHRASES.get(_normalise(token))
        if phrase:
            found.append((phrase, match.end()))
    return found


def _normalise(token):
    """A token as a verb name: no wrapping punctuation, no directory, no
    .exe, lower case. `((Get-Service` and `C:\\Windows\\rm.exe` both arrive
    here and have to come out as something the table can be keyed on."""
    name = token.strip("(){}[];|&")
    name = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def _target(command, start, stop):
    """What the verb starting at `start` is pointed at, looking no further
    than the next verb.

    The value of a path-ish parameter first, then the first bare argument.
    None when there isn't one: plenty of verbs (Get-Date, shutdown) take no
    target, and inventing one is exactly the guess this module refuses to
    make.
    """
    tokens = [
        match.group(0) for match in policy._TOKEN.finditer(command[start:stop])
    ]
    for index, token in enumerate(tokens):
        if policy._unquote(token).lower() in _TARGET_FLAGS and index + 1 < len(tokens):
            return _readable(tokens[index + 1])
    for token in tokens:
        if not token.startswith("-") and not policy._ENV_PREFIX.match(token):
            readable = _readable(token)
            if readable:
                return readable
    return None


def _readable(token):
    """A token as something worth showing a person: unquoted, and without the
    braces and operators a script's structure leaves attached. None for what's
    left when that was all it was."""
    text = policy._unquote(token).strip("{}();|&").strip()
    return text or None
