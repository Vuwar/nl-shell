"""Rules that can call a command risky when the model didn't.

The model classifies its own output, and the model is a 3B-14B running on the
user's laptop. When it says "risky" the interfaces stop and ask; when it says
"safe" the command runs with no question at all. So a single misjudgement is
not a worse answer, it's a deleted folder - and asking the thing that wrote the
command whether the command is dangerous is asking it to catch its own mistake.

This layer runs underneath that judgement and can only ever escalate. Safe
becomes risky; risky never becomes safe. That asymmetry is the whole design:
a rule that can only add a confirmation cannot break anything by being wrong,
which is what lets the list be aggressive without having to be right.

What it is not:

  * Not a sandbox, and not a security boundary. The threat model is a small
    model misjudging its own output, not somebody trying to get past this.
    Base64, a name built out of variables, an interpreter invoked on a file
    written a moment earlier - all of it sails straight through, by design,
    because defending that would mean running the shell's parser and this is
    two hundred lines of regex.
  * Not exhaustive. Shells can do more harm than any list enumerates. Anything
    not caught here is still classified by the model, which is where it was
    before this file existed.

The cost of a false positive is one keypress; the cost of a false negative is
somebody's files. Where the two conflict this leans hard on the first - but
not without limit, because a layer that asks about everything teaches people
to confirm without reading, and that is worse than not having it. Every rule
here is meant to survive the question "would a reasonable person be annoyed to
be asked about this?".
"""

import os
import re

# --- what the rules look for ------------------------------------------------

# A verb that needs no context. The value is the phrase the confirmation
# shows, and it's written to follow "This ": "This deletes files. Run it?"
_DESTRUCTIVE = {}


def _verbs(reason, *names):
    for name in names:
        _DESTRUCTIVE[name] = reason


_verbs(
    "deletes files",
    "rm", "rmdir", "unlink", "shred", "srm", "truncate",
    # PowerShell, plus the aliases people and small models actually type.
    "remove-item", "ri", "del", "erase", "rd", "clear-content", "clc",
    "clear-item", "cli", "remove-itemproperty",
)
_verbs(
    "erases or reformats a disk",
    "mkfs", "fdisk", "parted", "diskpart", "diskutil", "dd", "format",
    "format-volume", "clear-disk", "initialize-disk", "remove-partition",
)
_verbs(
    "shuts down or restarts the machine",
    "shutdown", "reboot", "halt", "poweroff", "restart-computer",
    "stop-computer",
)
_verbs(
    "stops running programs",
    "kill", "killall", "pkill", "taskkill", "stop-process", "spps",
)
_verbs(
    "changes who can open a file",
    "chmod", "chown", "chgrp", "icacls", "cacls", "takeown", "attrib",
    "set-acl",
)
_verbs(
    "changes how the system is set up",
    "reg", "regedit", "systemctl", "launchctl", "service", "set-service",
    "new-service", "remove-service", "set-executionpolicy", "set-mppreference",
    "netsh", "iptables", "nft", "ufw", "crontab", "schtasks", "mount",
    "umount", "bcdedit", "sfc", "dism",
)
_verbs(
    "asks for administrator rights",
    "sudo", "su", "doas", "runas", "gsudo",
)
_verbs(
    "runs a command it assembled itself",
    "eval", "iex", "invoke-expression", "exec",
)

# Verbs that write, but aren't destructive on their own. They earn a
# confirmation only in company: a -Force, or a path worth protecting.
_WRITERS = {
    "mv", "move-item", "mi", "move", "ren", "rename", "rename-item", "rni",
    "cp", "copy", "copy-item", "cpi", "xcopy", "robocopy", "rsync",
    "set-content", "add-content", "out-file", "tee", "tee-object",
    "new-item", "ni", "mkdir", "md", "ln", "mklink", "touch",
}

# Overwriting is what these do when the file is already there, so the rule is
# about the target rather than a flag.
_OVERWRITERS = {"set-content", "out-file", "tee", "tee-object"}

# Fetches something off the network. Dangerous only in the company of an
# interpreter, which is the next list.
_FETCHERS = {
    "curl", "wget", "irm", "iwr", "invoke-webrequest", "invoke-restmethod",
    "base64", "certutil",
}

_INTERPRETERS = {
    "sh", "bash", "zsh", "dash", "ksh", "fish", "csh",
    "iex", "invoke-expression", "powershell", "pwsh", "cmd",
    "python", "python3", "perl", "ruby", "node", "php", "osascript",
}

# Package managers. Installing is exactly the kind of thing people ask for in
# plain English and exactly the kind of thing to see before it happens: the
# failure mode is a package that isn't the one you meant, from a publisher you
# didn't look at. A bare `winget list` is not a change, so the subcommand
# decides.
_PACKAGERS = {
    "winget", "choco", "scoop", "apt", "apt-get", "dnf", "yum", "zypper",
    "pacman", "brew", "snap", "flatpak", "npm", "pnpm", "yarn", "pip",
    "pip3", "gem", "cargo", "go",
}
_PACKAGE_CHANGES = {
    "install", "uninstall", "remove", "upgrade", "update", "add", "erase",
    "purge", "reinstall",
}

# git subcommands that throw work away. The value is the flag that makes it
# destructive, or None when the subcommand always is.
_GIT = {
    "reset": ("--hard",),
    "clean": None,
    "push": ("--force", "-f", "--force-with-lease"),
    "branch": ("-d", "-D", "--delete"),
    "checkout": ("--force", "-f", "."),
    "restore": None,
    "rebase": None,
    "filter-branch": None,
    "gc": ("--prune",),
    "stash": ("drop", "clear"),
}

# Paths where a mistake is not recoverable by the person who made it. "/" and
# a bare drive root match only themselves, because as prefixes they match
# every absolute path there is.
_PROTECTED_EXACT = {"/", "/*", "~", "$home", "$env:userprofile", "%userprofile%"}
_PROTECTED_PREFIX = (
    "/etc", "/usr", "/bin", "/sbin", "/lib", "/var", "/boot", "/dev", "/proc",
    "/sys", "/system", "/library", "/applications",
    "c:\\windows", "c:\\users", "c:\\program files", "c:\\programdata",
    "%systemroot%", "%windir%", "$env:systemroot", "$env:windir",
)
_DRIVE_ROOT = re.compile(r"^[a-z]:[\\/]?$")

# -Force, and the abbreviations PowerShell accepts for it. -Recurse is
# deliberately absent: copying a tree recursively is not destructive, and
# escalating it would put a confirmation in front of a great many ordinary
# commands for nothing.
_FORCE = re.compile(r"^(?:-{1,2}(?:f|fo|for|forc|force|y)|/f|/y)$", re.IGNORECASE)

_ENV_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Anything that ends one command and begins another, including the two forms
# that hide a command inside another one. Nothing here is a shell parser: the
# point is only that a rule looking at the first word of a command must not be
# fooled by "ls; rm -rf ~".
_SEPARATOR = re.compile(r"&&|\|\||[;|\n\r`]|\$\(|\)")

_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|\S+")

# > redirects and truncates; >> appends and doesn't. A leading digit is a file
# descriptor (2> log.txt), which still truncates, so it's allowed through - but
# a target starting with & is another descriptor (2>&1), not a file.
_REDIRECT = re.compile(r"(?<![>&])>{1,2}(?!>)\s*(&?[^\s|;&<>]+|\"[^\"]*\"|'[^']*')")


def escalate(command, exists=os.path.exists):
    """Why `command` should be confirmed even if the model called it safe, as
    a phrase that follows "This " - or None to leave the model's answer alone.

    `exists` is how the overwrite rules ask whether a file is already there.
    It's a parameter so the tests can answer without touching the disk.
    """
    if not command or not command.strip():
        return None

    quoted = _quoted_spans(command)
    clauses = _clauses(command, quoted)
    heads = [_head(clause) for clause in clauses]

    for clause, head in zip(clauses, heads):
        reason = _clause_reason(clause, head, exists)
        if reason:
            return reason

    # Across clauses: something fetched in one and interpreted in a later one.
    # This is the shape an instruction takes when it arrives inside a web page
    # or a filename rather than from the person at the keyboard, so it's worth
    # catching even though each half is innocent.
    for i, head in enumerate(heads):
        if head in _FETCHERS and any(later in _INTERPRETERS for later in heads[i + 1:]):
            return "runs code downloaded from the internet"

    return _redirect_reason(command, quoted, exists)


def _clause_reason(clause, head, exists):
    if not head:
        return None

    tokens = _tokens(clause)
    args = [_unquote(token) for token in tokens[1:]]

    if head in _DESTRUCTIVE:
        return _DESTRUCTIVE[head]

    # mkfs.ext4, mkfs.xfs and the rest are the same command with the
    # filesystem stuck on the end.
    if head.startswith("mkfs"):
        return _DESTRUCTIVE["mkfs"]

    if head == "git":
        return _git_reason(args)

    if head in _PACKAGERS and any(arg.lower() in _PACKAGE_CHANGES for arg in args):
        return "installs or removes software"

    # An interpreter handed a command inline: read what it was handed, rather
    # than guessing. `powershell -Command "Remove-Item x"` is a delete wearing
    # a hat, and `powershell -Command Get-Date` is not worth asking about.
    if head in _INTERPRETERS:
        inline = _inline_command(tokens)
        if inline:
            return escalate(inline, exists)

    if head == "start-process" and _has_flag(args, "-verb") and "runas" in [a.lower() for a in args]:
        return "asks for administrator rights"

    if head in ("powershell", "pwsh") and _has_flag(args, "-encodedcommand", "-enc", "-e"):
        return "runs an encoded command, which can't be read before it runs"

    # find reads, right up until the end of the line says otherwise.
    if head == "find" and _has_flag(args, "-delete", "-exec", "-execdir", "-ok"):
        return "deletes or runs commands over everything it finds"

    if head in _WRITERS:
        if any(_FORCE.match(arg) for arg in args):
            return "overwrites whatever is already there"
        if head in _OVERWRITERS and _writes_over_existing(args, exists):
            return "overwrites an existing file"
        target = _protected(args)
        if target:
            return f"writes into {target}, which the system needs"

    return None


def _git_reason(args):
    words = [arg.lower() for arg in args if not arg.startswith("-")]
    flags = [arg.lower() for arg in args]
    subcommand = words[0] if words else None
    if subcommand not in _GIT:
        return None
    required = _GIT[subcommand]
    if required is None or any(flag in required for flag in flags + words[1:]):
        return "throws away work that git can't get back"
    return None


def _writes_over_existing(args, exists):
    """True when the first real argument names a file that's already there."""
    for arg in args:
        if arg.startswith("-"):
            continue
        return bool(exists(arg))
    return False


def _protected(args):
    for arg in args:
        low = arg.lower().rstrip("*").rstrip("\\/") or arg.lower()
        if low in _PROTECTED_EXACT or arg.lower() in _PROTECTED_EXACT:
            return arg
        if _DRIVE_ROOT.match(arg.lower()):
            return arg
        for prefix in _PROTECTED_PREFIX:
            if low == prefix or low.startswith(prefix + "\\") or low.startswith(prefix + "/"):
                return arg
    return None


def _redirect_reason(command, quoted, exists):
    for match in _REDIRECT.finditer(command):
        if _inside(match.start(), quoted):
            continue
        if match.group(0).lstrip("0123456789").startswith(">>"):
            continue
        target = _unquote(match.group(1))
        # 2>&1 and friends point at another stream, not at a file.
        if target.startswith("&"):
            continue
        if exists(target):
            return "overwrites an existing file"
    return None


# --- taking a command apart -------------------------------------------------
# None of this is a shell parser and none of it is trying to be. It exists so
# that a rule reading the first word of a command reads the first word of every
# command on the line, and doesn't read words that are only there as text.


def _quoted_spans(text):
    """(start, end) for every quoted run, so separators and redirects inside
    one can be ignored. An unclosed quote runs to the end of the line."""
    spans = []
    quote = None
    start = 0
    for i, char in enumerate(text):
        if quote is None and char in "'\"":
            quote, start = char, i
        elif quote == char:
            spans.append((start, i))
            quote = None
    if quote is not None:
        spans.append((start, len(text)))
    return spans


def _inside(position, spans):
    return any(start <= position <= end for start, end in spans)


def _clauses(command, quoted):
    pieces = []
    cut = 0
    for match in _SEPARATOR.finditer(command):
        if _inside(match.start(), quoted):
            continue
        pieces.append(command[cut:match.start()])
        cut = match.end()
    pieces.append(command[cut:])
    return [piece for piece in pieces if piece.strip()]


def _tokens(clause):
    return _TOKEN.findall(clause)


def _head(clause):
    """The verb a clause runs, normalised: no directory, no .exe, no quotes,
    no leading VAR=value assignments, lower case."""
    for token in _tokens(clause):
        if _ENV_PREFIX.match(token):
            continue
        name = _unquote(token).replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name.endswith(".exe"):
            name = name[:-4]
        return name
    return None


def _unquote(token):
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    return token


def _has_flag(args, *names):
    return any(arg.lower().split(":")[0] in names for arg in args)


def _inline_command(tokens):
    """What an interpreter was told to run inline, or None if it wasn't.

    Only quoted arguments count. An unquoted one is a script name, and reading
    a file to classify it is a different feature with different failure modes.
    """
    wants = {"-c", "-command", "-cmd"}
    for index, token in enumerate(tokens[1:], start=1):
        if token.lower().lstrip("-") in {name.lstrip("-") for name in wants}:
            following = tokens[index + 1:]
            if following and following[0][:1] in "'\"":
                return _unquote(following[0])
    return None
