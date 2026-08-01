"""Starts the local model server, waits for it, and stops it on the way out.

The app used to require a service the user had installed and started
themselves. Owning that process instead means one less thing to install, and
one less way for the app to be "broken" because something invisible wasn't
running — but it also means the failures are now ours to report, and the
process is now ours to clean up.

Four things this is careful about:

  * Not requiring the binary to be there. ai_shell.runtime fetches a
    llama.cpp build into the config folder when the machine hasn't got one,
    so a fresh clone starts rather than stopping at an install instruction.
  * Not starting a second server. A port that already answers belongs to
    somebody — a llama-server left running from a previous session, a
    developer's own instance with hand-picked flags — and taking it over is
    both cheaper and less surprising than racing it for the port.
  * Not hiding the wait. The first run downloads several gigabytes of model
    before the server binds anything at all, so "starting" can legitimately
    mean minutes. Callers get told what's happening rather than being handed
    a timeout.
  * Not leaving it behind. See Platform.start_background: the OS is asked to
    tie the child's life to ours, because the exits that skip our cleanup are
    exactly the ones that would strand a multi-gigabyte process.
"""

import atexit
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from ai_shell import config
from ai_shell import runtime
from ai_shell import weights
from ai_shell.platforms import current

# Where llama-server's own output goes. It's verbose, it's on its own timeline,
# and interleaving it with the shell's would make both unreadable — but it's
# also the only place the real reason for a failed start is written, so it goes
# to a file the error message can point at rather than to /dev/null.
LOG_PATH = os.path.join(config.CONFIG_DIR, "llama-server.log")

# How long to wait for a server that is running but hasn't answered yet. Only
# reached when the process is alive and silent: a crash is noticed as soon as
# it happens.
#
# The weights are on disk before the process starts (ai_shell.weights fetches
# them), so this covers loading them into memory and nothing else — a genuine
# hang, not a download. It was thirty minutes when the first run's
# multi-gigabyte fetch happened inside this wait.
READY_TIMEOUT = 300

_process = None
_keepalive = None  # whatever ties the child's life to ours; must stay referenced
_log = None
_lock = threading.Lock()


class ServerError(RuntimeError):
    """The model server could not be started, or never became ready."""


def _port_in_use():
    """True when something already accepts connections on our port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex((config.HOST, config.PORT)) == 0


def _is_ready():
    """True once the server will actually answer a completion.

    /health is 503 while the model loads and 200 after, which is the
    distinction that matters here — the port binds well before the weights
    are in memory, so a port check alone would hand back a server that
    rejects the first request."""
    try:
        with urllib.request.urlopen(
            f"http://{config.HOST}:{config.PORT}/health", timeout=2
        ) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _argv(binary, model_path):
    return [
        binary,
        # A path, not -hf: llama.cpp's own downloader gets three attempts over
        # six seconds and then discards what it fetched, which on a six-
        # gigabyte model is the whole evening. ai_shell.weights does that job
        # now and hands over a file that is already on disk and verified.
        "-m", model_path,
        "--host", config.HOST,
        "--port", str(config.PORT),
        "-c", str(config.CONTEXT_SIZE),
        "-ngl", str(config.GPU_LAYERS),
        # Use the chat template shipped inside the GGUF rather than a guess
        # from the file name. Qwen's template is what the prompt was tuned
        # against, and getting it wrong degrades quietly.
        "--jinja",
    ]


def _fail(message):
    return ServerError(f"{message}\nDetails in {LOG_PATH}")


def ensure_running(on_status=None):
    """Make sure a model server is answering at config.BASE_URL.

    Returns True if this call started one, False if it didn't have to. Raises
    ServerError if a server we started never became ready. `on_status` is
    called with short progress lines, because the first run is long enough
    that silence reads as a hang.
    """
    global _process, _keepalive, _log

    def say(message):
        if on_status:
            on_status(message)

    if not config.MANAGED_SERVER:
        return False  # the user pointed us at their own; it's not ours to start

    with _lock:
        if _process and _process.poll() is None:
            return False
        if _port_in_use():
            say(f"Using the model server already running on port {config.PORT}.")
            return False

        os.makedirs(config.CONFIG_DIR, exist_ok=True)

        # Outside the try below: not having a binary is a different failure
        # from not being able to start one, and runtime.ensure already says
        # what it tried.
        try:
            binary = runtime.ensure(on_status=say)
        except runtime.InstallError as error:
            raise ServerError(
                f"{error}\n"
                "Install llama.cpp yourself and put llama-server on your PATH, "
                "or set AI_SHELL_SERVER to its full path."
            ) from None

        # Separate from the binary above, and separate from the start below:
        # "there is nothing to run", "there are no weights to run it on" and
        # "it wouldn't start" are three different problems with three
        # different fixes, and collapsing them loses the one that matters.
        try:
            model_path = weights.ensure(config.MODEL_REF, config.MODEL_LABEL, on_status=say)
        except weights.WeightsError as error:
            raise ServerError(str(error)) from None

        try:
            # Appended to, not truncated: when a start fails and the user
            # tries again, the first failure is usually the informative one.
            _log = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
            _process, _keepalive = current.start_background(_argv(binary, model_path), _log)
        except FileNotFoundError:
            # Only reachable for a binary the user named: anything else came
            # from runtime.ensure, which just checked that it exists.
            raise ServerError(
                f"Couldn't find '{binary}'.\n"
                "Check the path in AI_SHELL_SERVER, or unset it to let the app "
                "install llama.cpp itself."
            ) from None
        except OSError as error:
            raise _fail(f"Couldn't start '{config.SERVER_BINARY}': {error}") from None

        atexit.register(stop)

    say(f"Starting {config.MODEL_LABEL} ({config.MODEL_REF})...")
    _wait_until_ready()
    return True


def _wait_until_ready():
    # Nothing to report while this runs. It used to announce the first-run
    # download, which happened inside this wait; that download is now finished
    # and reported on before the process is started at all.
    deadline = time.monotonic() + READY_TIMEOUT

    while time.monotonic() < deadline:
        if _is_ready():
            return

        exit_code = _process.poll()
        if exit_code is not None:
            # Dying during startup is the common failure — a missing backend
            # DLL, a model that doesn't exist, a port already taken by
            # something that wasn't listening when we looked. All of them are
            # in the log, and none of them are worth waiting out.
            stop()
            raise _fail(f"The model server stopped while starting (exit code {exit_code}).")

        time.sleep(0.5)

    stop()
    raise _fail(f"The model server didn't become ready within {READY_TIMEOUT // 60} minutes.")


def stop():
    """Stop the server, if this process is the one that started it. Safe to
    call more than once, and safe to call when nothing was ever started."""
    global _process, _keepalive, _log

    with _lock:
        process, _process = _process, None
        keepalive, _keepalive = _keepalive, None
        log, _log = _log, None

    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # A server mid-load can ignore a polite stop; it holds gigabytes,
            # so it doesn't get to linger.
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    if keepalive is not None:
        # Dropping this is what releases the OS-level tie (on Windows, closing
        # the job handle). Explicit rather than left to the garbage collector,
        # so it happens now and not at some later collection.
        keepalive.close()

    if log:
        try:
            log.close()
        except OSError:
            pass
