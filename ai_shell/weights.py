"""The model's weights: finding them, fetching them, and keeping what arrived.

Until now llama-server did this itself — `-hf <repo>:<quant>` resolves,
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

import re
from dataclasses import dataclass

from ai_shell import fetch

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
    quantisation with a different one — several gigabytes of the wrong file,
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

    # Repos routinely publish both packagings of identical weights — the
    # default model has a 6.25GB file and the same bytes as two shards. One
    # file is one request, one checksum and no ordering to get wrong, so it
    # wins; the shard path exists for repos that publish nothing else.
    chosen = unsplit[:1] or shards
    if not chosen:
        raise WeightsError(f"{repo} publishes no {quant} .gguf file.")
    return revision, [_as_file(repo, revision, siblings[name]) for name in chosen]
