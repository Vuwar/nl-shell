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
    """A download, an API call or an extraction didn't work out.

    `cause` is the exception underneath, kept because the caller's decision
    about it differs: a reset connection is worth retrying and a 404 is not,
    and that judgement doesn't belong in a module with no opinion about its
    payload.
    """

    def __init__(self, message, cause=None):
        super().__init__(message)
        self.cause = cause


def json_document(url, timeout=30):
    """Parsed JSON from `url`, or a FetchError carrying what went wrong."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise FetchError(f"Couldn't reach {url}: {error}", error) from None


def github_release(api_url, timeout=30):
    """(tag, {asset name: download url}) for a GitHub release endpoint.

    Works for /releases/latest and /releases/tags/<tag> alike — they return
    the same shape, and which one to ask for is the caller's business.
    """
    data = json_document(api_url, timeout)
    assets = {
        asset.get("name", ""): asset.get("browser_download_url")
        for asset in data.get("assets", [])
        if asset.get("browser_download_url")
    }
    return data.get("tag_name") or "latest", assets


def download(url, destination, on_progress=None, timeout=60, resume=False):
    """Fetch `url` to `destination`, reporting whole percentages as it goes.

    With `resume`, an existing `destination` is continued rather than
    replaced: its length becomes a Range request, and the body is appended.
    Whatever arrived before a failure therefore stays on disk and is worth
    something to the next attempt — which for a six-gigabyte model is the
    difference between a retry and starting the evening again.

    Nothing is renamed here. A caller that wants a partial file to be
    distinguishable from a finished one passes the partial name and does the
    renaming itself, because only the caller knows what "finished" means.

    Raises FetchError rather than the assorted URLError/OSError family, so a
    caller has one thing to catch around a download.
    """
    existing = os.path.getsize(destination) if resume and os.path.exists(destination) else 0

    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # A server is free to ignore the range and answer 200 with the
            # whole file. Appending that to what we already have makes a file
            # containing two overlapping copies and no error at all, so the
            # only safe reading of a 200 is "start again".
            resumed = bool(existing) and response.status == 206
            if not resumed:
                existing = 0
            total = existing + int(response.headers.get("Content-Length") or 0)
            read = existing
            reported = (read * 100 // total) - (read * 100 // total) % PROGRESS_STEP if total else 0
            with open(destination, "ab" if resumed else "wb") as handle:
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
        raise FetchError(f"Couldn't download {url}: {error}", error) from None


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
