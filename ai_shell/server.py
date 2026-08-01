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
from ai_shell import fit
from ai_shell import models
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

# What the card had free just before we loaded anything onto it, and again
# once the model was resident. The difference is our own footprint, which is
# the only way to tell our weights apart from somebody else's browser: after
# the model loads, "in use" is mostly us, and a reading that doesn't subtract
# us reports this app to the user as the program hogging their card.
_free_vram_at_start = None
_free_vram_after_load = None


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


def _gpu_layers():
    """How much of the model to put on the card for this particular start.

    Decided per start rather than per install, because it depends on what the
    user has open right now. config.GPU_LAYERS is the fallback for a machine
    whose free memory can't be read at all — there, all-or-nothing against the
    card's total is the best guess available.
    """
    model = config.current_model()
    if _free_vram_at_start is None or model is None:
        return config.GPU_LAYERS
    return fit.gpu_layers(
        model,
        _free_vram_at_start,
        config.CONTEXT_SIZE,
        config.HARDWARE.get("vram_shared", False),
    )


def _argv(binary, model_path, gpu_layers=None):
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
        # One conversation at a time, which is what a shell prompt is. Left to
        # itself this build opens four slots and gives each one the full
        # context, so -c 8192 becomes four caches of 8192 — on a 7B that is
        # about 1.8GB of graphics memory to hold three conversations nobody is
        # having, and it is taken out of the same budget the weights need.
        "-np", "1",
        "-ngl", str(config.GPU_LAYERS if gpu_layers is None else gpu_layers),
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
            # Recorded so the picker can say which models are already here
            # without asking HuggingFace, which is a network call a settings
            # screen shouldn't need.
            config.remember_weights(config.MODEL, model_path)
        except weights.WeightsError as error:
            raise ServerError(str(error)) from None

        # Before the process starts, and only here: ~45ms on a thread that is
        # about to spend the better part of a minute loading weights, behind a
        # window that has already opened. Afterwards the reading would be
        # mostly our own model and would describe nothing.
        global _free_vram_at_start
        _free_vram_at_start = current.free_vram_gb()

        try:
            # Appended to, not truncated: when a start fails and the user
            # tries again, the first failure is usually the informative one.
            _log = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
            _process, _keepalive = current.start_background(
                _argv(binary, model_path, _gpu_layers()), _log
            )
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
    global _free_vram_after_load
    deadline = time.monotonic() + READY_TIMEOUT

    while time.monotonic() < deadline:
        if _is_ready():
            # Taken here, the moment the weights are resident and before any
            # request has run: this minus the reading from before the start is
            # what this app is costing the card, which is what later checks
            # subtract so they describe other programs and not us.
            _free_vram_after_load = current.free_vram_gb()
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


def our_vram_gb():
    """What this app's own model is costing the card, or None if unknown.

    Two readings either side of loading the weights. Crude, and the only thing
    available: nvidia-smi reports per-process graphics memory as N/A for most
    processes on Windows, so "how much is ours" cannot simply be asked.

    Clamped at zero because the two readings are moments apart on a shared
    card — somebody else closing a window between them would otherwise make
    our footprint negative.
    """
    if _free_vram_at_start is None or _free_vram_after_load is None:
        return None
    return max(0.0, _free_vram_at_start - _free_vram_after_load)


def others_vram_gb(free_now):
    """How much of the card is held by programs that aren't us.

    The naive reading — total minus free — counts our own weights, which is
    how this app came to tell a user that "other programs" were using 5.9GB
    of their card while it was itself using 3.3GB of that.
    """
    total = config.HARDWARE.get("vram_gb")
    if not total or free_now is None:
        return None
    ours = our_vram_gb() or 0.0
    return max(0.0, (total - free_now) - ours)


def fit_notice():
    """One sentence about a model that cannot fit this card, or None.

    Only the permanent mismatch is reported here. A card that is merely busy
    right now is left to ai_shell.session, which says so only when an answer
    was actually slow — a prediction made before the first request can be
    wrong by a rounding error, and being told the machine will be slow and
    then finding it isn't is worse than not being told.
    """
    model = config.current_model()
    if not model:
        return None  # a model the user named; not ours to have an opinion about
    kind = fit.verdict(
        model,
        config.HARDWARE.get("vram_gb"),
        None,  # deliberately not the free reading: see the docstring
        config.HARDWARE.get("vram_shared", False),
    )
    if kind != "oversized":
        return None
    # measured=False: nothing has been slow yet, and saying otherwise about a
    # session the user hasn't had is how a warning stops being believed.
    return fit.explain(kind, measured=False)


def switch_model(model_id, on_status=None):
    """Change the model this app runs, fetching its weights if they aren't
    here yet. {"ok": True} once the new server is answering.

    Stopping the old server first is what makes this safe: the weights of two
    models will not fit the memory that couldn't hold one.
    """
    if not config.MANAGED_SERVER:
        return {
            "ok": False,
            "reason": (
                "This app is using a model server you started yourself, "
                "so the model is your own to choose."
            ),
        }
    if not models.by_id(model_id):
        return {"ok": False, "reason": "That isn't a model this app knows."}
    if model_id == config.MODEL:
        return {"ok": True}

    stop()
    config.set_model(model_id)
    try:
        ensure_running(on_status=on_status)
    except ServerError as error:
        # The choice is left pointing at the new model on purpose: the failure
        # is nearly always a half-finished download, and the retry has to
        # resume that one rather than reinstating the old model.
        return {"ok": False, "reason": str(error)}
    return {"ok": True}


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
