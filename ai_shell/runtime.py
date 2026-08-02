"""Finding llama-server, and fetching one when the machine hasn't got it.

The app already owns the model (llama.cpp downloads and caches the weights on
first run) and the server process (ai_shell.server starts and stops it). This
module closes the last gap: the executable itself, which until now had to be
downloaded, unzipped and put on PATH by hand before anything would run at all.

What it does is deliberately narrow:

  * It only acts when nothing is found. An installed llama-server on PATH wins,
    and a path the user set explicitly - AI_SHELL_SERVER, or server_binary in
    settings.json - is taken at face value and never second-guessed, because
    somebody who names a build has a reason for that build.
  * It installs into the app's own config folder, not into the system. Nothing
    is put on PATH, nothing needs an administrator, and uninstalling is
    deleting a folder.
  * It pins what it installed. The release tag goes into settings.json and is
    reused; the app does not quietly update the inference engine underneath a
    user between launches.

Which build it takes follows config.GPU_LAYERS, so the binary matches the
decision already made about where the model will run. A machine offloading to
a GPU gets the Vulkan build - one archive, every vendor, no separate runtime
to match against a driver version - and a machine running on the CPU gets the
CPU build. Neither can be wrong in a way that breaks the app: llama.cpp loads
its backends dynamically, so a Vulkan build on a machine whose driver won't
have it falls back to the CPU backend inside the same executable.

That choice costs some throughput against a CUDA build on an NVIDIA card. It
buys a 30MB download instead of a 600MB one (the CUDA build needs the CUDA
runtime alongside it) and removes the driver/runtime version matching, which
is the part that fails on someone else's machine. Users who want the last of
the performance can install that build themselves and point AI_SHELL_SERVER at
it - which is the case the first rule above exists to protect.
"""

import os
import platform
import shutil

from ai_shell import config, fetch

# The release the binaries come from. ggml-org is llama.cpp's own org, and
# these are the builds its release page offers - the same ones the README
# tells a user to download by hand.
RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

# Ours, so removing it is removing a folder. Kept beside settings.json rather
# than in the project directory: the install belongs to the user, not to a
# checkout that might be deleted or moved.
INSTALL_DIR = os.path.join(config.CONFIG_DIR, "llama.cpp")

BINARY_NAME = "llama-server.exe" if os.name == "nt" else "llama-server"


class InstallError(RuntimeError):
    """No llama-server could be found or fetched."""


def _arch():
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("amd64", "x86_64", "x64"):
        return "x64"
    return None


def _asset_names():
    """The release assets that would work here, best first.

    More than one because the preferred build isn't always the only usable
    one: a GPU machine can still run the CPU build, so listing it second turns
    "that asset is missing from this release" into a slower app rather than a
    failed install.
    """
    arch = _arch()
    if not arch:
        return []

    system = platform.system()
    use_gpu = config.GPU_LAYERS != 0

    if system == "Windows":
        # No Vulkan build is published for Windows on ARM.
        gpu = [f"bin-win-vulkan-{arch}.zip"] if arch == "x64" else []
        return (gpu if use_gpu else []) + [f"bin-win-cpu-{arch}.zip"]
    if system == "Darwin":
        # One build per architecture; Metal is compiled into it, so there's no
        # CPU/GPU choice to make here.
        return [f"bin-macos-{arch}.tar.gz"]
    if system == "Linux":
        gpu = [f"bin-ubuntu-vulkan-{arch}.tar.gz"] if use_gpu else []
        return gpu + [f"bin-ubuntu-{arch}.tar.gz"]
    return []


def _find_binary(root):
    """The server executable somewhere under `root`, or None.

    Searched for rather than assumed at a fixed path: the archives have not
    always agreed on whether the binaries sit at the root or under build/bin,
    and the answer isn't worth pinning a release to.
    """
    for directory, _, files in os.walk(root):
        if BINARY_NAME in files:
            return os.path.join(directory, BINARY_NAME)
    return None


def _release():
    """(tag, {asset name: download url}) for the latest llama.cpp release."""
    try:
        return fetch.github_release(RELEASES_API)
    except fetch.FetchError as error:
        raise InstallError(f"Couldn't reach the llama.cpp release page: {error}") from None


def _install(say):
    """Download and unpack a llama-server into INSTALL_DIR. Returns its path."""
    wanted = _asset_names()
    if not wanted:
        raise InstallError(
            f"No llama.cpp build is published for {platform.system()} "
            f"{platform.machine()}, so one can't be installed automatically."
        )

    tag, assets = _release()
    name = next(
        (asset for suffix in wanted for asset in assets if asset.endswith(suffix)),
        None,
    )
    if not name:
        raise InstallError(
            f"llama.cpp release {tag} has no build for this machine "
            f"(looked for {', '.join(wanted)})."
        )

    say(f"Installing llama.cpp {tag} ({name}) - this happens once.")

    # Staged next to the final folder and moved into place at the end, so an
    # interrupted download leaves nothing that looks like a working install.
    staging = INSTALL_DIR + ".partial"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    archive_path = os.path.join(staging, name)

    try:
        # Named in full rather than "%": these lines are also the desktop
        # panel's startup message, where a bare number says nothing.
        fetch.download(
            assets[name], archive_path, lambda percent: say(f"Downloading llama.cpp - {percent}%")
        )
        fetch.extract(archive_path, staging)
        os.remove(archive_path)

        binary = _find_binary(staging)
        if not binary:
            raise InstallError(f"{name} didn't contain {BINARY_NAME}.")
        fetch.make_executable(binary)

        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        os.replace(staging, INSTALL_DIR)
    except InstallError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (fetch.FetchError, OSError) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise InstallError(f"Couldn't install llama.cpp: {error}") from None

    config.remember_runtime(tag)
    say("Installed.")

    binary = _find_binary(INSTALL_DIR)
    if not binary:
        raise InstallError(f"Installed llama.cpp {tag}, but {BINARY_NAME} isn't where it landed.")
    return binary


def ensure(on_status=None):
    """The llama-server this app should run, installing one if it has to.

    Raises InstallError when there's nothing to run and nothing could be
    fetched - the caller turns that into the message the user sees.
    """
    def say(message):
        if on_status:
            on_status(message)

    # A named binary is the user's decision, not a starting point for ours.
    # Reported as missing rather than replaced, because silently running a
    # different build than the one somebody configured is worse than an error.
    if config.SERVER_BINARY_EXPLICIT:
        return config.SERVER_BINARY

    found = shutil.which(config.SERVER_BINARY)
    if found:
        return found

    installed = _find_binary(INSTALL_DIR)
    if installed:
        return installed

    return _install(say)
