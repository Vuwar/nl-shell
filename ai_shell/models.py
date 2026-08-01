"""Which model to run, and whether this computer can actually run it.

The shell used to name one model, sized for one laptop. That number is the
single least portable thing in the project: the same build has to work on a
handheld with 8GB of shared memory and on a desktop with a 24GB card, and the
model that suits one is either impossible or a waste on the other. So the
model is a choice made per machine, out of the list below.

Two rules shape that list.

One family, several sizes. The system prompt in ai_shell.llm is tuned — it
asks for a strict JSON shape, and it leans on the model following a fair
number of rules at once. Model families differ enormously in how reliably they
do that, so swapping in a different family is a change that has to be tested
against the prompt, not a preference. Sizes and quantisations within a family
behave consistently enough to be offered as a slider.

Repos, not paths. Each entry is a HuggingFace reference that llama-server's
`-hf` flag resolves and caches itself, so choosing a bigger model is a config
change rather than an errand — no download page, no file to put somewhere, no
path to get wrong.
"""

from dataclasses import dataclass

from ai_shell import fit

# Room the model needs beyond its own weights: the KV cache for the context
# window plus llama.cpp's compute buffers. Same multiplier wherever it runs —
# those buffers don't care whether they're in VRAM or RAM.
_OVERHEAD = 1.25

# What the machine needs for *itself*, and must not be counted as available.
# A fraction rather than a constant because the number genuinely scales: an
# 8GB laptop running Windows and a browser has nothing like 8GB spare, and the
# floor is what an idle desktop OS costs before this app opens anything. Get
# this wrong low and the model fits on paper while the machine swaps.
_RESERVE_FLOOR_GB = 4.0
_RESERVE_FRACTION = 0.25


@dataclass(frozen=True)
class Model:
    id: str            # what settings.json stores, and what the API call is told
    ref: str           # llama-server -hf <ref>
    label: str         # for the settings screen
    weights_gb: float  # the GGUF's size on disk

    @property
    def footprint_gb(self):
        """What this model occupies once loaded and serving."""
        return self.weights_gb * _OVERHEAD


def usable_ram_gb(ram_gb):
    """Of `ram_gb` installed, what a model may actually take."""
    return ram_gb - max(_RESERVE_FLOOR_GB, ram_gb * _RESERVE_FRACTION)


# Smallest first — recommend() walks this backwards to find the largest fit.
MODELS = (
    # 1.5B is the floor, not a recommendation: it holds the JSON shape but
    # drops rules from the prompt, so vague requests get guessed at instead of
    # asked about. Offered because a wrong answer beats an app that won't run.
    Model("qwen2.5-coder-1.5b-q4", "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M", "1.5B — minimum", 1.1),
    Model("qwen2.5-coder-3b-q4", "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF:Q4_K_M", "3B — light", 2.0),
    Model("qwen2.5-coder-7b-q4", "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M", "7B — balanced", 4.7),
    Model("qwen2.5-coder-7b-q6", "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:Q6_K", "7B — higher quality", 6.3),
    Model("qwen2.5-coder-14b-q4", "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF:Q4_K_M", "14B — strong", 9.0),
    Model("qwen2.5-coder-32b-q4", "Qwen/Qwen2.5-Coder-32B-Instruct-GGUF:Q4_K_M", "32B — best", 19.9),
)

_BY_ID = {model.id: model for model in MODELS}

# What the project ran before any of this existed, and what an unreadable
# machine falls back to: the largest size an ordinary 16GB laptop handles.
FALLBACK = _BY_ID["qwen2.5-coder-7b-q4"]

# Nothing smaller is worth choosing *on purpose* — below this the shell stops
# asking clarifying questions and starts inventing commands. It's still an
# option for a machine that can't hold anything else (see recommend).
_FLOOR = _BY_ID["qwen2.5-coder-3b-q4"]

# The smallest model whose reading of a page of web results is worth printing
# above the sources. Translating a request into a command is a narrow job with
# a grammar holding the shape steady; summarising five snippets into a true
# sentence is not, and it's the job where a small model fails invisibly — the
# answer reads perfectly and says something the sources never did. So the floor
# for that one job is higher than the floor for running the shell at all, and
# below it the app says so rather than pretending otherwise.
_SUMMARY_FLOOR = _BY_ID["qwen2.5-coder-7b-q4"]

# The largest model worth running without a GPU, regardless of how much RAM
# there is. Fitting is not the same as being usable: CPU inference is bound by
# memory bandwidth, so a 14B answers at a couple of tokens a second and a 32B
# at well under one. A workstation with 64GB and no GPU can hold the 32B
# comfortably and would take minutes per reply — which for a shell prompt is
# the same as not working. Capping keeps the CPU path merely slow.
_CPU_CEILING = _BY_ID["qwen2.5-coder-7b-q4"]


def by_id(model_id):
    """The model with this id, or None if the name isn't one we know."""
    return _BY_ID.get(model_id)


def summarizes_reliably(model):
    """Whether this model's summary of web results can be shown without a
    warning next to it. See _SUMMARY_FLOOR."""
    return model.weights_gb >= _SUMMARY_FLOOR.weights_gb


def _largest_fitting(budget_gb, ceiling=None):
    """The biggest model fitting in `budget_gb`, not exceeding `ceiling`."""
    fits = [
        model for model in MODELS
        if model.footprint_gb <= budget_gb
        and (ceiling is None or model.weights_gb <= ceiling.weights_gb)
    ]
    return fits[-1] if fits else None


def recommend(ram_gb, vram_gb, shared=False):
    """The best model this machine can hold, given probed hardware.

    A GPU decides it whenever it can hold something worth running: the same
    model is an order of magnitude faster on the card than in RAM, and one
    that doesn't fit gets partially offloaded, which is slower than never
    having touched the GPU because every token then crosses the bus twice.

    The GPU's budget is what fit.usable_vram_gb leaves after the desktop, not
    the card's total. Sizing against the total is what put a 7.875GB model on
    an 8GB card that had 5.5GB of browser on it already, and a model that
    doesn't fit is not merely a worse choice — it is several times slower than
    the CPU it was chosen over.

    A GPU too small to hold even the floor model is the interesting case, and
    it isn't rare — plenty of laptops pair 32GB of RAM with a 2GB display
    adapter. Taking the GPU's answer there would hand a machine that could run
    14B the weakest model on the list, so a card that small is ignored and the
    size comes from RAM instead.

    Either number may be None. Both None is an unreadable machine, which gets
    FALLBACK — the behaviour this project had before it could measure
    anything. A machine that measured but is smaller than everything on the
    list gets the smallest: too weak to be a good experience, but the entry
    exists precisely so that such a machine gets a working app rather than
    none.
    """
    gpu_pick = _largest_fitting(fit.usable_vram_gb(vram_gb, shared)) if vram_gb else None
    ram_pick = _largest_fitting(usable_ram_gb(ram_gb), _CPU_CEILING) if ram_gb else None

    if gpu_pick and gpu_pick.weights_gb >= _FLOOR.weights_gb:
        return gpu_pick
    if ram_pick:
        return ram_pick
    if gpu_pick:
        return gpu_pick
    if ram_gb or vram_gb:
        return MODELS[0]
    return FALLBACK


def catalog(vram_gb, ram_gb, shared=False, installed=(), current_id=None):
    """Every model, annotated for a picker: what fits, what's downloaded, what
    is in use.

    "Fits" is the same question recommend answers, asked per row rather than
    resolved to a winner — the card's budget where there is a card worth using,
    RAM under the CPU ceiling where there isn't. A machine with no GPU is not
    offered a 32B it would take minutes per reply to run.

    `installed` is a collection of model ids whose weights are already on
    disk. It is passed in rather than worked out here because answering it
    properly means looking at the filesystem, and this module deliberately
    doesn't.
    """
    usable_gpu = fit.usable_vram_gb(vram_gb, shared) if vram_gb else 0.0
    on_gpu = usable_gpu >= _FLOOR.footprint_gb
    budget = usable_gpu if on_gpu else usable_ram_gb(ram_gb or 0)
    ceiling = None if on_gpu else _CPU_CEILING

    return [
        {
            "id": model.id,
            "label": model.label,
            "weights_gb": model.weights_gb,
            "fits": (
                model.footprint_gb <= budget
                and (ceiling is None or model.weights_gb <= ceiling.weights_gb)
            ),
            "installed": model.id in installed,
            "current": model.id == current_id,
        }
        for model in MODELS
    ]
