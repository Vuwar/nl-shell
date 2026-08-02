"""The model's weights: finding them, fetching them, and keeping what arrived.

Until now llama-server did this itself - `-hf <repo>:<quant>` resolves,
downloads and caches the GGUF. That worked until a connection dropped. Its
downloader tries three times over six seconds, exits, and discards the partial
file, so twelve minutes of downloading became nothing and the app could only
report "the model server stopped while starting (exit code 1)".

None of that is reachable from outside the process, so this module takes the
job over. The shape follows ai_shell.runtime, which owns the llama.cpp binary
for the same reasons:

  * It acts only when something is missing. A file already on disk under its
    final name has been verified, and is not fetched or checked again.
  * It installs into the app's own folder, not into llama.cpp's cache. Sharing
    a copy with a hand-run llama-server would mean reproducing an undocumented
    naming scheme exactly, and being wrong about it means silently downloading
    a second copy of several gigabytes.
  * It pins what it fetched. The revision comes from the API and goes into the
    URL, so the weights don't change underneath a user between launches.

What is here that isn't in runtime.py is resume. A llama.cpp build is thirty
megabytes and restarting one is an annoyance; a model is six thousand, and
restarting that is the evening.
"""

import hashlib
import http.client
import os
import re
import shutil
import time
import urllib.error
from dataclasses import dataclass

from ai_shell import config, fetch
from ai_shell.progress import Smoother

API = "https://huggingface.co/api/models/{repo}?blobs=true"
DOWNLOAD = "https://huggingface.co/{repo}/resolve/{revision}/{name}"


class WeightsError(RuntimeError):
    """The weights couldn't be resolved, fetched or verified."""


@dataclass(frozen=True)
class File:
    name: str
    url: str
    size: int
    sha256: str


def _split_ref(ref):
    """('Qwen/…-GGUF', 'Q6_K') out of 'Qwen/…-GGUF:Q6_K'."""
    repo, _, quant = (ref or "").partition(":")
    if "/" not in repo or not quant:
        raise WeightsError(
            f"'{ref}' isn't a HuggingFace reference of the form repo/name:QUANT."
        )
    return repo, quant


def _matching(names, quant):
    """(unsplit, shards) among `names`, for this quantisation.

    Anchored rather than a substring test: 'q6_k' is a substring of 'q6_k_l'
    and 'q4_k' of 'q4_k_m', so a contains-check answers a request for one
    quantisation with a different one - several gigabytes of the wrong file,
    with nothing failing until the model loads.
    """
    tag = re.escape(quant)
    unsplit = re.compile(rf"-{tag}\.gguf$", re.IGNORECASE)
    shard = re.compile(rf"-{tag}-\d{{5}}-of-\d{{5}}\.gguf$", re.IGNORECASE)
    return (
        sorted(name for name in names if unsplit.search(name)),
        sorted(name for name in names if shard.search(name)),
    )


def _as_file(repo, revision, sibling):
    name = sibling["rfilename"]
    lfs = sibling.get("lfs") or {}
    size = lfs.get("size") or sibling.get("size") or 0
    sha256 = lfs.get("sha256")
    if not size or not sha256:
        # Without a length there's nothing to check free space against, and
        # without a checksum a resumed download can't be shown to be sound.
        # Both are published for every GGUF that matters; refusing is better
        # than fetching gigabytes we can't stand behind.
        raise WeightsError(f"{name} is published without a size or a checksum.")
    return File(name, DOWNLOAD.format(repo=repo, revision=revision, name=name), size, sha256)


def resolve(ref):
    """(revision, [File]) for the weights `ref` names.

    The quantisation in a reference is a tag, not a filename, so the file list
    comes from the API rather than being constructed.
    """
    repo, quant = _split_ref(ref)
    try:
        data = fetch.json_document(API.format(repo=repo))
    except fetch.FetchError as error:
        raise WeightsError(f"Couldn't look up {repo}: {error}") from None

    revision = data.get("sha") or "main"
    siblings = {
        sibling["rfilename"]: sibling
        for sibling in data.get("siblings", [])
        if sibling.get("rfilename")
    }
    unsplit, shards = _matching(siblings, quant)

    # Repos routinely publish both packagings of identical weights - the
    # default model has a 6.25GB file and the same bytes as two shards. One
    # file is one request, one checksum and no ordering to get wrong, so it
    # wins; the shard path exists for repos that publish nothing else.
    chosen = unsplit[:1] or shards
    if not chosen:
        raise WeightsError(f"{repo} publishes no {quant} .gguf file.")
    return revision, [_as_file(repo, revision, siblings[name]) for name in chosen]


def present(ref):
    """The already-downloaded weights for `ref` in the model folder, or None.

    Offline by design, which is the whole reason it doesn't just call
    resolve(): a settings screen listing six models must not make six
    HuggingFace requests to find out which of them are on the disk it is
    running from.

    So the file name is matched instead. Every GGUF repo names its files after
    itself - Qwen2.5-Coder-7B-Instruct-GGUF:Q6_K arrives as
    qwen2.5-coder-7b-instruct-q6_k.gguf - and the quantisation is matched with
    the same anchored test resolve uses, so a q4_k_m file is never mistaken
    for the q4_k somebody asked for.

    A guess, and treated as one: config.installed_models prefers the path a
    finished download recorded, and only falls back here for weights fetched
    by a build that kept no such record. Being wrong mislabels a row in a
    list; it cannot cause a download, because ensure() skips any file already
    on disk, and it cannot cause the wrong file to be loaded, because the path
    llama-server is given always comes from ensure().
    """
    try:
        repo, quant = _split_ref(ref)
    except WeightsError:
        return None

    stem = repo.rsplit("/", 1)[-1]
    if stem.lower().endswith("-gguf"):
        stem = stem[: -len("-gguf")]

    try:
        names = os.listdir(config.MODEL_DIR)
    except OSError:
        return None  # no folder yet, or one we can't read: nothing is installed

    prefix = f"{stem.lower()}-"
    unsplit, shards = _matching(
        [name for name in names if name.lower().startswith(prefix)], quant
    )
    # Same preference as resolve: one file beats a set of shards, and the
    # first shard is what llama.cpp is pointed at when shards are all there is.
    chosen = unsplit[:1] or shards[:1]
    return os.path.join(config.MODEL_DIR, chosen[0]) if chosen else None


# How many times a transfer is restarted before the user is told. Generous
# because each attempt resumes: the cost of one more try is seconds, and the
# cost of giving up too early is a download somebody has to start again.
ATTEMPTS = 8
BACKOFF = (2, 4, 8, 16, 30, 30, 30)

# Room to want beyond the download itself, for the filesystem's own overhead
# and for not filling a disk to the last byte.
SPACE_MARGIN = 1.1

_TRANSIENT_HTTP = (408, 429, 500, 502, 503, 504)


def _gb(size):
    return f"{size / 1_000_000_000:.1f}"


def _size(path):
    return os.path.getsize(path) if os.path.exists(path) else 0


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _retryable(error):
    """Whether this failure is worth another attempt.

    A connection that died is; a 404, a repo that has become gated, and a full
    disk are not. Eight attempts at those spend ninety seconds arriving at the
    same message.
    """
    cause = getattr(error, "cause", None)
    if isinstance(cause, urllib.error.HTTPError):
        return cause.code in _TRANSIENT_HTTP
    return isinstance(cause, (urllib.error.URLError, OSError, http.client.HTTPException))


def _check_space(pending):
    """Refuse before the first byte if the disk can't hold what's left."""
    need = int(sum(file.size - _size(path + ".partial") for file, path in pending) * SPACE_MARGIN)
    free = shutil.disk_usage(config.MODEL_DIR).free
    if free < need:
        raise WeightsError(
            f"The model needs about {_gb(need)} GB free in {config.MODEL_DIR}, "
            f"and there is {_gb(free)} GB."
        )


def _download(file, path, label, before, total, say, emit):
    """Fetch one file into `path`, resuming and retrying until it verifies.

    `before` is how many bytes of the whole set are already accounted for, so
    the percentage counts the set rather than restarting at zero per shard.

    `say` and `emit` are the same progress reported twice, at two different
    rates. `say` is a line for a terminal and moves in whole percents; `emit`
    is the desktop panel's payload and moves as often as fetch reports.
    """
    partial = path + ".partial"
    refetched = False
    attempt = 0

    while True:
        attempt += 1
        # Restarted per attempt, and seeded with what is already on disk: a
        # resumed download that counted those bytes as having just arrived
        # would open with a rate of several gigabytes a second.
        smoother = Smoother(started_at=before + _size(partial))
        said = [-1]

        def progress(read, file_total):
            done = min(before + read, total)
            percent = done * 100 // total if total else 0
            smoother.sample(done, time.monotonic())
            emit(
                "downloading",
                bytes_done=done,
                bytes_total=total,
                percent=percent,
                rate=smoother.rate,
                eta=smoother.eta_for(total),
            )
            # Whole percents only. fetch reports five times a second now, and
            # this line goes to a terminal as well as to the window.
            if percent != said[0]:
                said[0] = percent
                say(
                    f"Downloading {label} - {percent}% "
                    f"({_gb(done)} of {_gb(total)} GB)"
                )

        try:
            fetch.download(file.url, partial, progress, resume=True)
        except fetch.FetchError as error:
            if not _retryable(error) or attempt >= ATTEMPTS:
                raise WeightsError(
                    f"{error}\n"
                    f"{_gb(before + _size(partial))} of {_gb(total)} GB is kept in "
                    f"{config.MODEL_DIR}.\n"
                    "Start the app again and it picks up from there."
                ) from None
            wait = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            done = before + _size(partial)
            at = done * 100 // total
            emit(
                "retrying",
                bytes_done=done,
                bytes_total=total,
                percent=at,
                retry={"attempt": attempt + 1, "of": ATTEMPTS, "wait": wait},
            )
            say(
                f"Connection lost at {at}% - retrying in {wait}s "
                f"(attempt {attempt + 1} of {ATTEMPTS})"
            )
            time.sleep(wait)
            continue

        done = before + file.size
        emit(
            "verifying",
            bytes_done=done,
            bytes_total=total,
            percent=done * 100 // total if total else 0,
        )
        say("Checking the download…")
        if _sha256(partial) == file.sha256:
            # Renaming is what marks it verified. No separate state file can
            # then disagree with the disk, and a half-file can never be loaded
            # as weights because it never wears the name.
            os.replace(partial, path)
            return

        os.remove(partial)
        if refetched:
            raise WeightsError(
                f"{file.name} failed its checksum twice, so the copy being served is "
                "damaged rather than merely interrupted. Try again later."
            )
        # Once is most likely a resume that stitched the wrong bytes - a proxy
        # answering a range request with something else. That is repairable by
        # starting clean; twice is not, and looping on gigabytes is not a fix.
        refetched = True
        attempt = 0
        emit(
            "refetching",
            bytes_done=before,
            bytes_total=total,
            percent=before * 100 // total if total else 0,
        )
        say("The download didn't match its checksum - fetching it again from the start.")


def ensure(ref, label, on_status=None, on_progress=None):
    """The path to hand `llama-server -m`, downloading the weights if needed.

    Raises WeightsError when they can't be had - the caller turns that into
    the message the user sees.

    `on_status` is a line for a human to read. `on_progress` is the same
    download as a dict, for an interface that draws it rather than printing
    it. Only what this module can know goes into that payload, so there is
    nothing about layers or graphics cards here - ai_shell.server merges
    those in on the way past.
    """
    def say(message):
        if on_status:
            on_status(message)

    def emit(phase, **fields):
        if on_progress:
            on_progress(dict(phase=phase, label=label, **fields))

    emit("resolving")
    say(f"Resolving {label}…")
    _, files = resolve(ref)

    # Before disk_usage, which raises on a path that doesn't exist yet.
    os.makedirs(config.MODEL_DIR, exist_ok=True)

    targets = [
        (file, os.path.join(config.MODEL_DIR, os.path.basename(file.name)))
        for file in files
    ]
    pending = [(file, path) for file, path in targets if not os.path.exists(path)]

    if pending:
        _check_space(pending)
        total = sum(file.size for file, _ in targets)
        before = sum(file.size for file, path in targets if os.path.exists(path))
        for file, path in pending:
            _download(file, path, label, before, total, say, emit)
            before += file.size

    # The first file, not any file: a sharded model is loaded by pointing
    # llama.cpp at -00001-of-000NN, which finds the rest itself.
    return targets[0][1]
