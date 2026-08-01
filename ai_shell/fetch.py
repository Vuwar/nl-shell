"""Fetching things off the internet and unpacking them, safely.

Two parts of this app download a release archive and unpack it into a folder:
ai_shell.runtime, which installs llama.cpp the first time, and
ai_shell.updater, which installs a newer version of the app itself. They want
the same four things — a GitHub release's assets, a download with progress, an
extractor that can't write outside the folder it was given, and the executable
bit a zip doesn't carry — so those live here rather than in one of them with
the other importing from it sideways.

Nothing here knows what it's downloading or why. That's deliberate: an
extractor with an opinion about its payload is one more place for the guard
below to be argued around.
"""

import json
import os
import stat
import tarfile
import urllib.error
import urllib.request
import zipfile

# Sent on every request. GitHub's API rejects requests without one, and a name
# in someone's logs is more use than a Python default.
USER_AGENT = "ai-shell"

# How often a download reports back. Percentage rather than bytes because the
# callers put this line in front of a user, where "37%" says more than a
# number of megabytes against a total they never asked about.
PROGRESS_STEP = 10


class FetchError(RuntimeError):
    """A download, an API call or an extraction didn't work out."""


def github_release(api_url, timeout=30):
    """(tag, {asset name: download url}) for a GitHub release endpoint.

    Works for /releases/latest and /releases/tags/<tag> alike — they return
    the same shape, and which one to ask for is the caller's business.
    """
    request = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise FetchError(f"Couldn't reach {api_url}: {error}") from None
    assets = {
        asset.get("name", ""): asset.get("browser_download_url")
        for asset in data.get("assets", [])
        if asset.get("browser_download_url")
    }
    return data.get("tag_name") or "latest", assets


def download(url, destination, on_progress=None, timeout=60):
    """Fetch `url` to `destination`, reporting whole percentages as it goes.

    Raises FetchError rather than the assorted URLError/OSError family, so a
    caller has one thing to catch around a download.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            read = 0
            reported = 0
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    read += len(chunk)
                    if total and on_progress:
                        percent = read * 100 // total
                        if percent >= reported + PROGRESS_STEP:
                            reported = percent - percent % PROGRESS_STEP
                            on_progress(reported)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise FetchError(f"Couldn't download {url}: {error}") from None


def check_members(names, root):
    """Refuse an archive whose members would be written outside `root`.

    A release built by the project's own CI is not the threat this guards
    against — a substituted or corrupted archive is, and an extractor that can
    write anywhere on the disk is worth not having. Absolute paths and `..`
    both land outside `root` once resolved, so one check covers them.
    """
    root = os.path.realpath(root)
    for name in names:
        target = os.path.realpath(os.path.join(root, name))
        if target != root and not target.startswith(root + os.sep):
            raise FetchError(f"Refusing to extract '{name}': it points outside {root}.")


def extract(archive_path, destination):
    """Unpack a .zip or a .tar.gz into `destination`, members checked first."""
    try:
        if archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as archive:
                check_members(archive.namelist(), destination)
                archive.extractall(destination)
        else:
            with tarfile.open(archive_path) as archive:
                check_members(archive.getnames(), destination)
                archive.extractall(destination)
    except FetchError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as error:
        raise FetchError(f"Couldn't unpack {os.path.basename(archive_path)}: {error}") from None


def make_executable(path):
    """Restore the executable bit, which a zip doesn't carry."""
    if os.name == "nt":
        return
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
