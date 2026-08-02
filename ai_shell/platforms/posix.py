"""What macOS and Linux share: bash, POSIX paths, `find` for listings.

The one thing they don't share is applications - where they're installed and
how you start one is completely different - so that stays in macos.py and
linux.py.
"""

import os
import re
import shlex
from datetime import datetime

from ai_shell.platforms.base import Platform

_FIND_HEAD = re.compile(r"^\s*find\b")
# Read-only stages that pass whole lines through, so the output is still one
# path per line after them. Anything else (wc, xargs, awk with a format) leaves
# the pipeline emitting something parse_listing can't read, and the rewrite is
# abandoned in favour of the raw output.
_SAFE_STAGE = re.compile(r"^\s*(sort|grep|egrep|fgrep|head|tail|uniq)\b")
# Anything that could run a second command, redirect, or chain - a projected
# listing is re-run, so it has to be nothing but a read.
_UNSAFE = re.compile(r"[;&<>`]|\$\(")

# find predicates that take a value, and those that stand alone. Whitelisted
# rather than blacklisted: -exec, -delete and -fprintf are not reads, and a
# list of what's allowed can't silently miss a new one.
_VALUE_FLAGS = {
    "-maxdepth", "-mindepth", "-name", "-iname", "-path", "-ipath", "-type",
    "-size", "-mtime", "-mmin", "-newer", "-user", "-group", "-perm",
    "-regex", "-iregex",
}
_BARE_FLAGS = {
    "-print", "-depth", "-empty", "-readable", "-follow",
    "-not", "-a", "-and", "-o", "-or", "!", "(", ")",
    "-L", "-H", "-P",
}

_ONLY_DIRS = re.compile(r"-type\s+d\b")
_ONLY_FILES = re.compile(r"-type\s+f\b")

# A shell prefix on an error line: "mv: ", and bash's own "bash: line 1: ".
_SHELL_LINE = re.compile(r"^(?:ba)?sh: line \d+: ")


class Posix(Platform):
    SHELL_NAME = "bash"

    NAME_PARAM = re.compile(r"-i?name\s*$")
    # A path starting at the root or the home directory, quoted or bare -
    # bash doesn't need the quotes, so the model often leaves them off.
    ABS_PATH = re.compile(
        r"""['"]((?:~|\$HOME)?/[^'"]*)['"]|(?:^|\s)((?:~|\$HOME)?/[^\s'"|;&<>]+)"""
    )

    LISTING_RULE = (
        "Answer yes/no questions about files or folders by listing the things "
        "that match,\n   and always list a folder's contents with `find "
        "<folder> -maxdepth 1 -mindepth 1`\n   - adding `-type d`, `-type f` "
        "or `-name '<pattern>'` to narrow it - so an\n   empty result means "
        "\"no\" and a non-empty one shows what was found. Add\n   `! -name "
        "'.*'` to leave out hidden files unless the user asks for them.\n   "
        "Never use `ls` for this, and never test each item in a loop into a\n"
        "   column of true/false."
    )

    # --- running commands -------------------------------------------------
    def shell_argv(self, command):
        # No -l: a login shell would run the user's profile on every single
        # command, which is slow and can print banners into the output.
        shell = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
        return [shell, "-c", command]

    def quote(self, text):
        return shlex.quote(text)

    def strip_error_prefix(self, line):
        """Drops the leading program name ("mv: cannot move ...") so the user
        sees only the reason."""
        line = _SHELL_LINE.sub("", line)
        head, sep, rest = line.partition(": ")
        if sep and rest and " " not in head.strip():
            return rest
        return line

    def context_paths(self, command):
        return [os.path.expanduser(os.path.expandvars(p)) for p in super().context_paths(command)]

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
            # Both mean "not this one" - an empty line, which the caller reads
            # as a cancellation.
            print()
            return ""
        finally:
            readline.set_startup_hook()

    # --- directory listings ----------------------------------------------
    def list_directory_command(self, path):
        # Dotfiles are hidden by default, the same as every file manager: a
        # home folder is otherwise mostly config nobody clicked in to see.
        return f"find {self.quote(path)} -maxdepth 1 -mindepth 1 ! -name '.*'"

    def project_listing(self, command):
        """`find` already prints one full path per line, so a listing needs no
        rewriting - it only needs checking, since the session re-runs whatever
        comes back."""
        if _UNSAFE.search(command):
            return None
        stages = self.split_pipeline(command)
        if not _FIND_HEAD.match(stages[0]):
            return None
        if not self._is_plain_find(stages[0]):
            return None
        if not all(_SAFE_STAGE.match(stage) for stage in stages[1:]):
            return None
        return command.strip()

    def _is_plain_find(self, stage):
        """True when the find does nothing but select and print paths."""
        try:
            tokens = shlex.split(stage)
        except ValueError:
            return False
        rest = iter(tokens[1:])
        for token in rest:
            if token in _VALUE_FLAGS:
                if next(rest, None) is None:
                    return False
            elif token in _BARE_FLAGS:
                continue
            elif token.startswith("-"):
                return False  # -exec, -delete, -printf, anything unrecognised
            # else: a path operand, which is what we want
        return True

    def parse_listing(self, stdout, cwd=None):
        items = []
        for line in stdout.splitlines():
            path = line.strip()
            if not path:
                continue
            # find prints paths as it was given them, so `find . -maxdepth 1`
            # yields relative ones - which would resolve against this process's
            # directory rather than the folder the command ran in.
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(cwd or os.getcwd(), path))
            try:
                info = os.stat(path)
                is_dir = os.path.isdir(path)
            except OSError:
                try:
                    info = os.lstat(path)  # a broken symlink still has a row
                except OSError:
                    return None  # not a path at all: this wasn't a listing
                is_dir = False
            items.append(
                self.row(path, is_dir, info.st_size, datetime.fromtimestamp(info.st_mtime).isoformat())
            )
        return items

    def listing_kind(self, command):
        if _ONLY_DIRS.search(command):
            return "folder"
        if _ONLY_FILES.search(command):
            return "file"
        return "item"
