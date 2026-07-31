"""Runs commands in this machine's shell, with a fallback for launching apps by name.

Which shell that is, and what "launch an app" even looks like, comes from
ai_shell.platforms — this module only owns the running of it.
"""

import subprocess

from ai_shell.platforms import current


def run_command(command, cwd=None):
    """Runs `command` in `cwd` — the folder the user is currently working in,
    so a relative path in the command means what they'd expect. Without it
    every bare name resolves against wherever the app happened to be launched
    from, which is never the folder they're looking at.

    Decoding is stated rather than left to text=True, which follows the
    machine's locale — so the same command on the same files could produce
    different text on two computers, and on a UTF-8-mode interpreter could
    produce none at all. errors="replace" because a shell's output is not
    ours to guarantee: one odd byte in one filename must cost that filename
    its accent, not cost the user the whole command. It would otherwise raise
    on subprocess's reader thread, where this try can't see it, and arrive
    here as stdout being None for something further along to trip over.
    """
    try:
        result = subprocess.run(
            current.shell_argv(command),
            capture_output=True, timeout=60, cwd=cwd,
            encoding="utf-8", errors="replace",
        )
        return result
    except Exception as e:
        return e


def list_apps():
    """Every installed application as a (name, launch_id) pair — the OS's own
    index of what's on this machine — or [] if the scan fails."""
    return current.list_apps()


def execute_command(command, apps=None, cwd=None):
    """Runs `command`, giving the platform two chances to fix a launch the
    model couldn't get right: once before running (prepare_command) and once
    after it fails (retry_command). Either way the lookup is only ever for the
    app the command itself named, so the result is that exact app or an honest
    failure — never a different app.

    Returns a list of (command_ran, result) pairs — one entry, unless a retry
    happened, in which case two. `apps` is an optional pre-scanned (name,
    launch_id) list to spare a rescan, and `cwd` the folder to run in."""
    command, problem = current.prepare_command(command, apps)
    if problem:
        # Nothing was run, and the caller reads an Exception as "it failed
        # with this reason" — which is exactly what this is.
        return [(command, RuntimeError(problem))]

    attempts = []
    result = run_command(command, cwd)
    attempts.append((command, result))

    retry = current.retry_command(command, result, apps)
    if retry:
        attempts.append((retry, run_command(retry, cwd)))

    return attempts
