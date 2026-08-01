"""Everything that differs between one installation and the next.

Three sources, most specific first:

  1. an environment variable — a one-off override, for trying something
     without editing anything;
  2. settings.json in the per-user config folder — what the settings screen
     writes, and what persists;
  3. a default worked out from the machine on first run, then written to (2)
     so it's only worked out once.

The third is the reason this file is no longer four constants. A model that
fits the developer's laptop is not a model that fits everyone's, and the
project can't know which machine it's on until it's on one — so the first
launch measures, chooses, and records. See ai_shell.models for the list it
chooses from and ai_shell.hardware for the measuring.

Nothing here reaches for the network or starts a process; ai_shell.server does
that, using the values below.
"""

import json
import os

# Submodules imported directly, not as `from ai_shell import ...`: this module
# is reached through ai_shell/__init__.py importing Session, so the package
# object is still half-built when these run and has no attributes yet.
import ai_shell
import ai_shell.hardware as hardware
import ai_shell.models as models
from ai_shell.platforms import current

CONFIG_DIR = current.config_dir()
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

# The port llama-server is started on when we're the ones starting it. 8080 is
# llama.cpp's own default, so a server the user started by hand is already
# where we'd look.
DEFAULT_PORT = 8080

# 8192 covers the system prompt (~1.5k) plus the 30-slot history window with
# room to spare. Larger costs KV-cache memory the model-size choice already
# budgeted for, so it isn't scaled up on big machines.
DEFAULT_CONTEXT = 8192


def _read_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        # No file yet on a first run, and an unreadable or hand-mangled one is
        # the same situation: nothing is configured, so measure and start over.
        return {}


def _write_settings(data):
    """Best-effort persist. A read-only config folder is not a reason to
    refuse to start — it only means the hardware probe runs again next time."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except OSError:
        pass


def _resolve():
    """(settings, model, first_run) — the stored settings brought up to date
    with a model that exists, probing the machine only if nothing valid is
    recorded yet."""
    settings = _read_settings()

    model = models.by_id(settings.get("model"))
    if model:
        return settings, model, False

    # Either a first run, or a model id that no longer exists because the
    # registry changed under a settings file written by an older build.
    probed = hardware.probe()
    model = models.recommend(probed["ram_gb"], probed["vram_gb"], probed.get("vram_shared", False))
    settings["model"] = model.id
    settings["hardware"] = probed
    _write_settings(settings)
    return settings, model, True


_SETTINGS, _MODEL, FIRST_RUN = _resolve()

# What the machine was found to have, for the settings screen to show next to
# the model list. Read back from settings rather than re-probed: this has to
# be the hardware the recorded choice was made against.
HARDWARE = _SETTINGS.get("hardware") or {}

# --- the model ------------------------------------------------------------
# MODEL is the name put in the API call. llama-server ignores it and serves
# whatever it was loaded with, but the OpenAI client requires the field and an
# honest value makes a captured request readable.
#
# The override is what makes an unmanaged server usable: point BASE_URL at an
# Ollama install and the name suddenly matters again, because Ollama picks the
# model by it and won't recognise an id from our registry.
MODEL = os.environ.get("AI_SHELL_MODEL") or _MODEL.id
MODEL_REF = os.environ.get("AI_SHELL_MODEL_REF") or _MODEL.ref
MODEL_LABEL = _MODEL.label

# Where the weights are kept. Ours, beside the llama.cpp install runtime.py
# puts in the same folder, so uninstalling stays "delete a folder". Not
# llama.cpp's own cache: sharing one copy with a hand-run llama-server would
# mean reproducing its undocumented file naming exactly, and being wrong about
# it means silently downloading a second copy of several gigabytes. The
# override is for a machine whose system drive is the wrong place for 20GB.
MODEL_DIR = (
    os.environ.get("AI_SHELL_MODEL_DIR")
    or _SETTINGS.get("model_dir")
    or os.path.join(CONFIG_DIR, "models")
)

# --- the server -----------------------------------------------------------
HOST = os.environ.get("AI_SHELL_HOST") or "127.0.0.1"
PORT = int(os.environ.get("AI_SHELL_PORT") or _SETTINGS.get("port") or DEFAULT_PORT)
CONTEXT_SIZE = int(os.environ.get("AI_SHELL_CONTEXT") or _SETTINGS.get("context") or DEFAULT_CONTEXT)

# Where the llama-server executable is. The bare name means "on PATH", which
# is what a normal install looks like — and when it isn't there either,
# ai_shell.runtime fetches one into CONFIG_DIR rather than failing.
_NAMED_SERVER = os.environ.get("AI_SHELL_SERVER") or _SETTINGS.get("server_binary")
SERVER_BINARY = _NAMED_SERVER or "llama-server"

# Whether that name came from the user. A build somebody chose deliberately —
# a CUDA one, a local compile — must be used as given and never quietly
# replaced by one we downloaded, so this is what turns the auto-install off.
SERVER_BINARY_EXPLICIT = bool(_NAMED_SERVER)

# Which llama.cpp release was installed for us, if any. Recorded so the engine
# isn't silently swapped underneath the user on some later launch.
RUNTIME_RELEASE = _SETTINGS.get("llama_cpp_release")

# --- updating the app itself ----------------------------------------------
# What this build calls itself, for ai_shell.updater to compare against the
# latest release. The one attribute of the half-built package it is safe to
# read here: __version__ is assigned in ai_shell/__init__.py above the import
# that leads to this module, so by the time this line runs it is already set.
VERSION = ai_shell.__version__

# Whether the app may look for, and download, a newer version of itself. On by
# default; the install is still never applied without the user asking for it
# (see ai_shell/updater.py). Off entirely for anyone who'd rather their
# software didn't phone home, and for packagers whose distribution does the
# updating.
AUTO_UPDATE = (os.environ.get("AI_SHELL_AUTO_UPDATE") or "").strip() != "0" and bool(
    _SETTINGS.get("auto_update", True)
)

# When GitHub was last asked, as a Unix timestamp. Kept so that launching the
# app five times in an afternoon is one request, not five.
LAST_UPDATE_CHECK = _SETTINGS.get("update_checked_at") or 0

# Whether an edited command is recorded to CONFIG_DIR/corrections.jsonl. On by
# default, and unlike anything that reads existing shell history this only sees
# commands typed into this app, in this session, on their way to running — it
# never leaves the machine. Off by default would collect nothing, which is the
# same as not having the feature. See ai_shell/corrections.py for what a record
# holds and what is scrubbed out of it first.
CORRECTIONS = (os.environ.get("AI_SHELL_CORRECTIONS") or "").strip() != "0" and bool(
    _SETTINGS.get("corrections", True)
)

# -1 offloads every layer to the GPU; 0 keeps the whole model on the CPU.
# Deciding here rather than passing -1 always: llama.cpp will happily offload
# part of a model that doesn't fit, which is slower than not offloading at all
# because every token then crosses the bus twice.
_VRAM = HARDWARE.get("vram_gb")
GPU_LAYERS = -1 if _VRAM and _VRAM >= _MODEL.footprint_gb else 0

_ENV_BASE_URL = os.environ.get("AI_SHELL_BASE_URL")
BASE_URL = _ENV_BASE_URL or f"http://{HOST}:{PORT}/v1"

# Whether to start and stop the server ourselves. Pointing AI_SHELL_BASE_URL
# somewhere is a statement that something is already running there — an Ollama
# install, a shared box, a llama-server with hand-picked flags — and spawning
# a second server to ignore would be both wasteful and confusing.
MANAGED_SERVER = _ENV_BASE_URL is None

# api_key has to be *something* for the OpenAI client to send a request, and
# nothing local checks it.
API_KEY = "local"

# --- what this model can't be trusted with --------------------------------
# Reading web results and saying what they mean is the one job here where a
# small model fails without looking like it failed (see models._SUMMARY_FLOOR).
# The app can't make a 3B better at it, but it can stop presenting its answer
# with the same confidence as a 14B's — so the interfaces print this once
# alongside the first web answer of a session, and the sources stay visible
# underneath either way.
#
# Only for a model we chose. A name the user supplied, or a server they pointed
# us at, could be anything at all, and warning about a 70B someone is running
# on their own hardware would be both wrong and patronising.
_MODEL_IS_OURS = MANAGED_SERVER and MODEL == _MODEL.id

SUMMARY_CAVEAT = (
    None
    if not _MODEL_IS_OURS or models.summarizes_reliably(_MODEL)
    else (
        # The label's first half is the size ("3B — light"); the qualifier
        # after it is for the settings screen's list, not for a sentence.
        f"The {MODEL_LABEL.split(' — ')[0]} model this computer runs is a small one, so its "
        f"reading of these results can be hit-or-miss — the sources are the part to trust."
    )
)


def remember_runtime(tag):
    """Record the llama.cpp release ai_shell.runtime just installed, so later
    launches reuse it instead of looking at the release page again."""
    global RUNTIME_RELEASE
    RUNTIME_RELEASE = tag
    _SETTINGS["llama_cpp_release"] = tag
    _write_settings(_SETTINGS)


def remember_update_check(when):
    """Record that the release page was just checked, so the next launch a
    minute later doesn't ask again."""
    global LAST_UPDATE_CHECK
    LAST_UPDATE_CHECK = when
    _SETTINGS["update_checked_at"] = when
    _write_settings(_SETTINGS)


def connection_error():
    """What to tell the user when the model can't be reached — one message,
    shared, because the CLI and the GUI were drifting apart on it.

    Which advice is useful depends on whose server it is. When we start it,
    a failure is ours and the user needs to know what's missing; when they
    pointed us at one, the only thing we can usefully say is that it isn't
    answering."""
    if MANAGED_SERVER and SERVER_BINARY_EXPLICIT:
        # Their binary, so the useful question is whether the one they named
        # actually works — nothing was installed on their behalf to blame.
        return (
            f"Couldn't reach the local model server on port {PORT}.\n"
            f"Check that '{SERVER_BINARY}' runs, or unset AI_SHELL_SERVER to "
            f"let the app install llama.cpp itself."
        )
    if MANAGED_SERVER:
        return (
            f"Couldn't reach the local model server on port {PORT}.\n"
            f"See {os.path.join(CONFIG_DIR, 'llama-server.log')} for why it stopped."
        )
    return f"Can't reach a model server at {BASE_URL}. Is it running?"
