"""Keeping the app up to date without the user downloading anything again.

The releases already exist - .github/workflows/build.yml attaches an installer,
a portable zip, a macOS bundle, a Linux tarball and a wheel to every GitHub
release. What was missing was the app noticing. Until now a fix shipped on
Tuesday reached a user whenever they next thought to visit the releases page,
which for most people is never.

So: on launch, in the background, this asks GitHub what the latest release is.
If it's newer than ai_shell.__version__ it downloads the one asset that matches
how this copy was installed, and then stops and says so. Nothing is replaced
until the user clicks Restart. That's the whole bargain - the download is
automatic because it costs the user nothing to have it ready, and the install
is not, because an app that runs shell commands should not swap itself out
from under someone mid-sentence.

    launch -> check -> download -> "Update ready (0.2.0)  [Restart]" -> apply

Five ways in, five ways to apply
--------------------------------
How a copy was installed decides how it's replaced, so the first thing this
does is work out which of these it is:

  windows-installer  Inno Setup put it there (unins000.exe sits beside the
                     exe). Run the new setup.exe silently; it upgrades in
                     place because the AppId matches.
  windows-portable   The zip, unpacked by hand or by install.ps1. Swap the
                     folder.
  macos              AI Shell.app. Swap the bundle.
  linux              The tarball's folder. Swap it.
  pip                Installed into a Python environment. pip installs the
                     new wheel over it.
  source             A checkout. Never updated - that's what git is for.

Why a script does the work
--------------------------
Every one of those replaces files that the running process has open, which
Windows forbids outright and which is merely a bad idea elsewhere. So applying
an update is not something this process does: it writes a small shell script,
starts it detached, and quits. The script waits for our process to disappear,
does the swap, and starts the new version. It is deliberately dumb - no
Python, since a swapped-out app has no interpreter to rely on, and no branches
beyond the ones baked in at write time.

The model weights and llama.cpp are untouched by all of this. They live in the
config folder (see ai_shell.runtime), not in the app folder, which is why an
update is tens of megabytes and not several gigabytes.
"""

import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time

from ai_shell import config, fetch

REPO = os.environ.get("AI_SHELL_UPDATE_REPO") or "Vuwar/nl-shell"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"

# Where downloads land. Beside settings.json rather than in the app folder,
# which on half these channels is about to be deleted.
DOWNLOAD_DIR = os.path.join(config.CONFIG_DIR, "updates")

# How long a check is good for. The point is to notice a release within a day
# or so of it happening, not to poll GitHub - most launches should ask nothing.
CHECK_INTERVAL = 6 * 60 * 60  # seconds

# How long the apply script waits for this process to exit before going ahead
# anyway. Generous: the alternative to waiting is replacing files still in use.
_WAIT_TRIES = 300

WINDOWS_INSTALLER = "windows-installer"
WINDOWS_PORTABLE = "windows-portable"
MACOS = "macos"
LINUX = "linux"
PIP = "pip"
SOURCE = "source"

# The channels whose update is "replace this folder with that folder".
_SWAP_CHANNELS = (WINDOWS_PORTABLE, MACOS, LINUX)


class UpdateError(RuntimeError):
    """An update couldn't be checked for, fetched or applied."""


# --- version numbers --------------------------------------------------------
def parse_version(text):
    """"v0.2.0-rc1" -> (0, 2, 0, 0, "rc1"). Junk -> None.

    The fourth field is the release/pre-release flag, and it sorts the way
    semver says: a pre-release is *older* than the release it leads to, so
    0.2.0-rc1 must lose to 0.2.0. Tuples compare left to right, so 0 for a
    pre-release and 1 for a final release puts them in that order - and the
    suffix itself only breaks ties between two pre-releases of the same
    version, where asciibetical order is close enough to be useful and wrong
    only for people numbering past rc9.
    """
    if not text:
        return None
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+](.+))?$", str(text).strip())
    if not match:
        return None
    major, minor, patch, suffix = match.groups()
    return (int(major), int(minor), int(patch), 0 if suffix else 1, suffix or "")


def is_newer(candidate, current):
    """Whether release `candidate` is worth offering to someone on `current`.

    An unparseable candidate is never newer. That matters more than it looks:
    the answer comes off the internet, and "couldn't read the tag" must not
    mean "offer it anyway".
    """
    new, now = parse_version(candidate), parse_version(current)
    if not new or not now:
        return False
    return new > now


# --- which copy of the app is this ------------------------------------------
def _frozen():
    return bool(getattr(sys, "frozen", False))


def _macos_bundle():
    """The .app this is running out of, or None.

    sys.executable inside a bundle is Contents/MacOS/AI Shell, so the bundle
    is three levels up - checked rather than assumed, because the same frozen
    build also runs as a plain folder during development.
    """
    bundle = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
    return bundle if bundle.endswith(".app") else None


def detect_channel():
    """Which of the six situations above this copy is in."""
    if not _frozen():
        # A checkout has the project files above the package; an installed
        # copy has site-packages there. This is the difference between "you
        # have git" and "you have a release".
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.exists(os.path.join(root, "pyproject.toml")):
            return SOURCE
        return PIP

    if sys.platform == "win32":
        # Inno leaves its uninstaller in the application folder, so its
        # presence is the same question as "did an installer put this here",
        # asked of the disk rather than of a setting someone could have
        # copied along with the folder.
        beside = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.exists(os.path.join(beside, "unins000.exe")):
            return WINDOWS_INSTALLER
        return WINDOWS_PORTABLE

    if sys.platform == "darwin":
        return MACOS if _macos_bundle() else SOURCE
    return LINUX


def install_root():
    """The folder an update replaces, for the channels that replace one.

    The .app on macOS, and the folder holding the executable everywhere else -
    which for a PyInstaller onedir build is the whole of what was shipped.
    """
    channel = detect_channel()
    if channel == MACOS:
        return _macos_bundle()
    if channel in (WINDOWS_PORTABLE, WINDOWS_INSTALLER, LINUX):
        return os.path.dirname(os.path.abspath(sys.executable))
    return None


def _arch_tag():
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "x64"


def asset_suffix(channel):
    """The end of the release asset's file name for this channel, or None.

    Matched by suffix rather than built in full because the version sits in
    the middle of every one of these names, and the whole point of asking
    GitHub was not knowing the version yet.
    """
    return {
        WINDOWS_INSTALLER: "-windows-x64-setup.exe",
        WINDOWS_PORTABLE: "-windows-x64.zip",
        MACOS: f"-macos-{_arch_tag()}.zip",
        LINUX: "-linux-x64.tar.gz",
        PIP: "-py3-none-any.whl",
    }.get(channel)


def _executable_in(root, channel):
    """The app executable inside a freshly unpacked tree, or None.

    Checked before anything is swapped: an archive that unpacked into
    something without an app in it is a corrupt download, and finding that out
    *after* moving the working copy aside is finding it out too late.
    """
    if channel == MACOS:
        return root if root.endswith(".app") and os.path.isdir(root) else None
    name = "AI Shell.exe" if channel == WINDOWS_PORTABLE else "ai-shell"
    candidate = os.path.join(root, name)
    return candidate if os.path.exists(candidate) else None


# --- asking GitHub ----------------------------------------------------------
def check(force=False):
    """The newer release for this machine, or None.

    None covers every kind of "nothing to do": already current, a channel that
    doesn't update itself, updates switched off, a release with no asset this
    machine can use, and - via the caller's except - GitHub being unreachable.
    A dict when there is one:

        {"version", "tag", "url", "name", "channel", "notes_url"}
    """
    channel = detect_channel()
    if channel == SOURCE or not config.AUTO_UPDATE:
        return None

    if not force and time.time() - (config.LAST_UPDATE_CHECK or 0) < CHECK_INTERVAL:
        # Checked recently. If that check found something and it's still
        # sitting in the downloads folder, it's still an update - the point of
        # the interval is not asking GitHub again, not forgetting the answer.
        return _staged_update(channel)

    try:
        tag, assets = fetch.github_release(RELEASES_API)
    except fetch.FetchError as error:
        raise UpdateError(str(error)) from None

    config.remember_update_check(time.time())

    # removeprefix, not lstrip: lstrip takes a set of characters, so a tag
    # that ever began with two of them would lose both.
    version = str(tag).removeprefix("v")
    if not is_newer(version, config.VERSION):
        return None

    suffix = asset_suffix(channel)
    name = next((asset for asset in assets if suffix and asset.endswith(suffix)), None)
    if not name:
        # A release that skipped this platform's build. Not an error worth
        # putting in front of anyone: there's nothing they could do about it,
        # and the next release will almost certainly have one.
        return None

    return {
        "version": version,
        "tag": tag,
        "url": assets[name],
        "name": name,
        "channel": channel,
        "notes_url": f"{RELEASES_PAGE}/tag/{tag}",
    }


def _staged_update(channel):
    """An update already downloaded on an earlier launch, or None.

    Quitting without clicking Restart is the normal case - people close this
    panel constantly - and re-downloading the same 40MB on every launch that
    follows would be a poor way to repay that.
    """
    suffix = asset_suffix(channel)
    if not suffix or not os.path.isdir(DOWNLOAD_DIR):
        return None
    for name in sorted(os.listdir(DOWNLOAD_DIR)):
        if not name.endswith(suffix):
            continue
        version = _version_from_asset(name, suffix)
        if version and is_newer(version, config.VERSION):
            return {
                "version": version,
                "tag": f"v{version}",
                "url": None,  # already on disk
                "name": name,
                "channel": channel,
                "notes_url": f"{RELEASES_PAGE}/tag/v{version}",
            }
    return None


def _version_from_asset(name, suffix):
    """0.2.0 out of AI-Shell-0.2.0-windows-x64-setup.exe, given the suffix.

    Given the suffix, and not merely searching for a version-shaped run of
    digits, because a pre-release tag and a platform tag are the same shape to
    a regex: 0.2.0-rc1-windows-x64.zip has to yield 0.2.0-rc1, and
    0.2.0-windows-x64.zip has to yield 0.2.0. Cutting the part whose spelling
    is already known settles it - what's left ends with the version.
    """
    stem = name[: -len(suffix)] if suffix and name.endswith(suffix) else name
    match = re.search(r"[-_](\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?)$", stem)
    return match.group(1) if match else None


# --- getting it onto the disk -----------------------------------------------
def stage(update, on_progress=None):
    """Download `update` and, for the channels that need it, unpack it.

    Returns the update with "file" (what was downloaded) and, for the swap
    channels, "tree" (the unpacked app, ready to be moved into place) filled
    in. Both are what the apply script is pointed at.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    downloaded = os.path.join(DOWNLOAD_DIR, update["name"])
    _sweep_downloads(keep=update["name"])

    if update.get("url") and not os.path.exists(downloaded):
        partial = downloaded + ".partial"

        # fetch reports raw bytes five times a second now. What leaves here is
        # still a percentage that changes at most a hundred times, because it
        # ends up in a status dict the window polls.
        said = [-1]

        def progress(read, total):
            percent = read * 100 // total if total else 0
            if percent != said[0] and on_progress:
                said[0] = percent
                on_progress(percent)

        try:
            fetch.download(update["url"], partial, progress)
            os.replace(partial, downloaded)
        except (fetch.FetchError, OSError) as error:
            _remove(partial)
            raise UpdateError(f"Couldn't download the update: {error}") from None
    elif not os.path.exists(downloaded):
        raise UpdateError("The downloaded update has gone missing.")

    staged = dict(update, file=downloaded)
    if update["channel"] in _SWAP_CHANNELS:
        staged["tree"] = _unpack(staged)
    return staged


def _sweep_downloads(keep):
    """Delete everything in the downloads folder except `keep` and the apply
    script.

    An update that's downloaded but never installed is the normal case - this
    panel gets closed constantly - so without this, every release anyone
    skipped would still be on their disk.
    """
    try:
        names = os.listdir(DOWNLOAD_DIR)
    except OSError:
        return
    for name in names:
        if name == keep or name.startswith("apply-update"):
            continue
        _remove(os.path.join(DOWNLOAD_DIR, name))


def _unpack(update):
    """Unpack the archive next to the folder it will replace, and return the
    unpacked app.

    Next to it, rather than in the downloads folder, so that applying the
    update is a rename within one directory - which is atomic, instant, and
    can't fail halfway across a drive boundary with half an app at each end.
    """
    root = install_root()
    if not root:
        raise UpdateError("Couldn't work out which folder to update.")

    parent = os.path.dirname(root)
    staging = os.path.join(parent, f".ai-shell-update-{update['version']}")
    # This folder sits beside the installed app, so anything stale here is
    # 40MB of a version nobody took, in a folder the user can see. The
    # sweep covers this version's own leftovers too, from a download that
    # was interrupted last time.
    try:
        for name in os.listdir(parent):
            if name.startswith(".ai-shell-update-"):
                _remove(os.path.join(parent, name))
    except OSError:
        pass  # the makedirs below reports an unusable folder properly

    try:
        os.makedirs(staging, exist_ok=True)
    except OSError as error:
        raise UpdateError(
            f"Can't write to {parent}, so the update can't be unpacked there: {error}"
        ) from None

    try:
        fetch.extract(update["file"], staging)
    except fetch.FetchError as error:
        _remove(staging)
        raise UpdateError(str(error)) from None

    # Every one of these archives holds exactly one top-level folder - the
    # app. More than one means the packaging changed and this code hasn't.
    entries = [os.path.join(staging, name) for name in os.listdir(staging)]
    tree = entries[0] if len(entries) == 1 and os.path.isdir(entries[0]) else None
    executable = _executable_in(tree, update["channel"]) if tree else None
    if not executable:
        _remove(staging)
        raise UpdateError(f"{update['name']} didn't contain an app.")

    fetch.make_executable(executable)
    return tree


# --- applying it ------------------------------------------------------------
def relaunch_argv():
    """How to start this app again once it's been replaced.

    Not sys.argv: the arguments this run was given (a one-off override, a file
    someone dragged on) belong to this run. What the new version should get is
    a plain start, the same as from the Start Menu.
    """
    channel = detect_channel()
    if channel == MACOS:
        return ["open", _macos_bundle() or ""]
    if _frozen():
        return [sys.executable]

    # pip. The console script is the thing on PATH and the thing pip just
    # rewrote, so it's what to run - unless this was started as a script, in
    # which case that script is still the entry point it was.
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if argv0.endswith(".py") and os.path.exists(argv0):
        return [sys.executable, argv0]
    if argv0 and os.path.exists(argv0):
        return [argv0]
    return [sys.executable, "-m", "ai_shell_gui.app"]


def apply(update, relaunch=None):
    """Write the apply script, start it detached, and return.

    The caller must then quit - promptly, because the script is already
    watching for that. `relaunch` is the argv to start afterwards; [] for a
    console session, where a new window nobody asked for is worse than none.
    """
    if relaunch is None:
        relaunch = relaunch_argv()

    script = _write_script(update, relaunch)
    try:
        if os.name == "nt":
            # Detached and with no console of its own: this outlives us, and
            # a black window appearing as the app closes reads as a crash.
            subprocess.Popen(
                [os.environ.get("COMSPEC") or "cmd.exe", "/c", script],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                ["/bin/sh", script],
                start_new_session=True,  # survives this process's death
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
    except OSError as error:
        raise UpdateError(f"Couldn't start the updater: {error}") from None


def _write_script(update, relaunch):
    """The script that replaces the app once this process is gone."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    path = os.path.join(DOWNLOAD_DIR, "apply-update" + (".cmd" if os.name == "nt" else ".sh"))
    body = _windows_script(update, relaunch) if os.name == "nt" else _posix_script(update, relaunch)
    with open(path, "w", encoding="utf-8", newline="\r\n" if os.name == "nt" else "\n") as handle:
        handle.write(body)
    if os.name != "nt":
        fetch.make_executable(path)
    return path


def _windows_script(update, relaunch):
    channel = update["channel"]
    root = install_root()
    lines = [
        "@echo off",
        # Paths run through a user's name, and cmd reads a batch file in the
        # OEM codepage unless told otherwise.
        "chcp 65001 >nul",
        "setlocal",
        f":: AI Shell {config.VERSION} -> {update['version']}",
        "set /a tries=0",
        ":wait",
        f'tasklist /FI "PID eq {os.getpid()}" /NH 2>nul | find "{os.getpid()}" >nul',
        "if errorlevel 1 goto apply",
        "set /a tries+=1",
        f"if %tries% GEQ {_WAIT_TRIES} goto apply",
        # ping, not timeout: timeout wants a console to read a keypress from,
        # and this script deliberately hasn't got one.
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":apply",
    ]

    if channel == WINDOWS_INSTALLER:
        # The AppId in packaging/windows/installer.iss is what makes this an
        # upgrade of the existing install rather than a second copy beside it.
        lines += [
            f'"{update["file"]}" /SILENT /SUPPRESSMSGBOXES /NORESTART',
            f'del /f /q "{update["file"]}" >nul 2>&1',
        ]
    elif channel == PIP:
        # The wheel that was already downloaded, not the package name: this
        # can't quietly install something else off an index.
        lines += [
            f'"{sys.executable}" -m pip install --upgrade --no-input "{update["file"]}" >nul 2>&1',
            f'del /f /q "{update["file"]}" >nul 2>&1',
        ]
    else:
        old = f"{root}.old"
        lines += [
            f'if exist "{old}" rmdir /s /q "{old}"',
            f'move "{root}" "{old}" >nul',
            # If the move failed the old app is still there and still works,
            # which is the good outcome of a bad situation - start it and stop.
            "if errorlevel 1 goto giveup",
            f'move "{update["tree"]}" "{root}" >nul',
            f'if errorlevel 1 move "{old}" "{root}" >nul',
            f'rmdir /s /q "{old}" >nul 2>&1',
            f'rmdir /s /q "{os.path.dirname(update["tree"])}" >nul 2>&1',
            f'del /f /q "{update["file"]}" >nul 2>&1',
            ":giveup",
        ]

    if relaunch:
        # The empty "" is start's title argument. Without it, start treats a
        # quoted path as the title and opens a console instead of the app.
        lines.append('start "" ' + " ".join(f'"{part}"' for part in relaunch))
    # Deleting the script while cmd is still reading it leaves it looking for
    # the next line of a file that has gone - an error nobody sees, since this
    # runs detached, but an error all the same. The (goto) makes cmd give up
    # its read handle first, and & keeps the delete on the same line, which is
    # the last line cmd ever reads.
    lines += ['(goto) 2>nul & del /f /q "%~f0"', ""]
    return "\n".join(lines)


def _posix_script(update, relaunch):
    channel = update["channel"]
    root = install_root()
    quote = _shell_quote
    lines = [
        "#!/bin/sh",
        f"# AI Shell {config.VERSION} -> {update['version']}",
        "tries=0",
        f"while kill -0 {os.getpid()} 2>/dev/null; do",
        "  tries=$((tries + 1))",
        f"  [ $tries -ge {_WAIT_TRIES} ] && break",
        "  sleep 1",
        "done",
    ]

    if channel == PIP:
        # --no-input because there is no one at a terminal to answer, and the
        # already-downloaded wheel rather than the name so this can't quietly
        # install something else from an index.
        lines.append(
            f"{quote(sys.executable)} -m pip install --upgrade --no-input {quote(update['file'])} "
            f">/dev/null 2>&1"
        )
        lines.append(f"rm -f {quote(update['file'])}")
    else:
        old = f"{root}.old"
        lines += [
            f"rm -rf {quote(old)}",
            f"if mv {quote(root)} {quote(old)}; then",
            f"  mv {quote(update['tree'])} {quote(root)} || mv {quote(old)} {quote(root)}",
            f"  rm -rf {quote(old)} {quote(os.path.dirname(update['tree']))}",
            f"  rm -f {quote(update['file'])}",
            "fi",
        ]

    if relaunch:
        lines.append(" ".join(quote(part) for part in relaunch) + " >/dev/null 2>&1 &")
    lines += ['rm -f "$0"', ""]
    return "\n".join(lines)


def _shell_quote(text):
    """`text` as one literal argument to /bin/sh."""
    return "'" + str(text).replace("'", "'\\''") + "'"


def _remove(path):
    """Delete a file or a folder, whichever it turns out to be. Best effort:
    every caller is either cleaning up after a failure it's already reporting,
    or clearing space it's about to overwrite anyway."""
    shutil.rmtree(path, ignore_errors=True)
    try:
        os.remove(path)
    except OSError:
        pass


# --- what the interfaces talk to -------------------------------------------
class Updater:
    """Runs the check and the download on a thread, and reports where it got to.

    Polled rather than pushed, matching how the desktop panel already watches
    the model server start: pywebview's bridge only calls in one direction,
    and a status this cheap costs nothing to ask for.
    """

    def __init__(self, relaunch=None):
        self._relaunch = relaunch
        self._lock = threading.Lock()
        self._state = {"state": "idle", "version": None, "message": "", "notes_url": None}
        self._update = None

    def start(self):
        """Begin checking, in the background. Safe to call when updates are
        off or this is a checkout - it just finds nothing to do."""
        threading.Thread(target=self._run, daemon=True).start()

    def _set(self, state, **fields):
        with self._lock:
            self._state = {
                "state": state,
                "version": fields.get("version", self._state.get("version")),
                "message": fields.get("message", ""),
                "notes_url": fields.get("notes_url", self._state.get("notes_url")),
            }

    def _run(self):
        try:
            self._set("checking")
            update = check()
            if not update:
                self._set("idle")
                return

            self._set(
                "downloading", version=update["version"], notes_url=update["notes_url"],
                message="Downloading…",
            )
            staged = stage(
                update,
                on_progress=lambda percent: self._set(
                    "downloading",
                    version=update["version"],
                    notes_url=update["notes_url"],
                    message=f"Downloading… {percent}%",
                ),
            )
            with self._lock:
                self._update = staged
            self._set("ready", version=staged["version"], notes_url=staged["notes_url"])
        except UpdateError as error:
            # A failed update is not a failed app. It's reported where a
            # curious user will find it and nowhere else.
            self._set("failed", message=str(error))
        except Exception as error:  # noqa: BLE001 - a daemon thread nobody awaits
            self._set("failed", message=f"Update check failed: {error}")

    def status(self):
        """{"state": idle|checking|downloading|ready|failed, "version",
        "message", "notes_url"} - a snapshot, safe to poll."""
        with self._lock:
            return dict(self._state)

    def install(self):
        """Start the apply script. The caller quits immediately afterwards.

        Returns {"ok": True} once the script is running, or {"ok": False,
        "error"} - in which case nothing has been touched and the app should
        carry on as it was.
        """
        with self._lock:
            update = self._update
        if not update:
            return {"ok": False, "error": "There's no update ready to install."}
        try:
            apply(update, relaunch=self._relaunch)
        except UpdateError as error:
            self._set("failed", message=str(error))
            return {"ok": False, "error": str(error)}
        return {"ok": True}
