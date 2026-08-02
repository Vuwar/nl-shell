"""How much of the graphics card a model may actually have, and what to say
when the answer is "less than it's taking".

ai_shell.models sizes a model against the card's *total* memory. That is the
bug this module exists to fix: a desktop, a compositor and a browser are
holding some of that card before this app opens anything, and a model sized
against the total does not fit - it is paged across the bus a piece at a time,
which is several times slower than never having touched the card at all.

The rule lives here, alone, because three places need it and they must not
disagree: the first-run sizing in ai_shell.models, the two warnings, and the
model picker's idea of which rows fit. Numbers in, verdict out - no
subprocess, no filesystem, no network, so it is testable on a machine with no
graphics card at all.
"""

# What the machine needs for itself, and must not be counted as available.
# A fraction, with a floor, for the same reason ai_shell.models reserves RAM
# that way: a 24GB card's desktop costs more than an 8GB card's, but no card's
# costs nothing.
VRAM_RESERVE_FLOOR_GB = 1.0
VRAM_RESERVE_FRACTION = 0.15

# Below this, on a machine with a graphics card, the model is not merely small
# - it is being paged. The machine this was written against measured 0.82.
# A card-less laptop runs at 3 or so by nature, which is why every caller
# checks for a card before consulting this number.
SLOW_TOKENS_PER_SEC = 5.0

# Shorter replies than this aren't worth timing: a six-token answer spends
# most of its life in the round-trip, not the model.
MIN_TIMED_TOKENS = 20

# The gap between what a driver says is free and what it will actually hand
# out. Measured on an 8GB card reporting 5.8GB free, running a 7B-Q4 at the
# app's own 8192 context:
#
#     24 layers  35.0 tokens/sec   3.97GB resident
#     26 layers  39.5              4.15GB
#     27 layers  42.2              4.40GB
#     28 layers   6.9              3.58GB   <- all of them
#
# Note the last row: asking for every layer leaves *less* on the card, not
# more. It is not gradual paging, it is the allocation failing and llama.cpp
# falling back - which is why neither flash attention nor an 8-bit cache moved
# it (both were tried; both stayed at 6.9).
VRAM_SAFETY_GB = 0.5

# What going all-in costs beyond the layers themselves: the output tensor, and
# the cache moving onto the card with them. Demanded on top of the ordinary
# margin before every layer is offloaded, because that step is the one with a
# cliff under it - being wrong about a partial split costs a few percent, and
# being wrong about a full one costs six times the speed.
FULL_OFFLOAD_MARGIN_GB = 1.0

# Scratch space for the graph itself, over and above weights and cache.
COMPUTE_GB = 0.3

# Below this there is no point splitting: the transfers cost more than the few
# layers save, and whole-model-on-CPU is both faster and simpler to reason
# about.
MIN_WORTHWHILE_LAYERS = 4


def usable_vram_gb(total_gb, shared=False):
    """Of `total_gb` on the card, what a model may occupy.

    `shared` is Apple Silicon, where there is no separate card and
    Platform.vram_gb already returns the share macOS is willing to hand a
    single process. Reserving out of that a second time would shrink Mac model
    choice to pay for a cost macOS has already charged.
    """
    if not total_gb:
        return 0.0
    if shared:
        return total_gb
    return total_gb - max(VRAM_RESERVE_FLOOR_GB, total_gb * VRAM_RESERVE_FRACTION)


def gpu_layers(model, free_vram_gb, context_size, shared=False):
    """How many of `model`'s layers to put on the card: -1 for all, 0 for none.

    All-or-nothing was the wrong shape for this decision, and measurably so -
    see the table above VRAM_SAFETY_GB. The old rule could only pick the top
    of that curve or the bottom of it, and which one it picked turned on a
    margin of a few hundred megabytes it never measured.

    Two decisions, not one, because they carry different risks:

      * Whether to offload everything. This is the step with the cliff under
        it, so it has to be earned: room for the weights, the cache, the
        output tensor and a margin on top. Wrong here costs six times the
        speed.
      * How many layers otherwise. Wrong here costs a few percent, so it fills
        to a smaller margin - and is never allowed to reach the full count,
        which is the cliff by another route.

    Returning -1 rather than a count for the everything case leaves llama.cpp
    to handle models whose layer sizes we have approximated badly.

    `free_vram_gb` is what the card has free *before* this app loads anything,
    so it already accounts for whatever else the user is running.
    """
    if not free_vram_gb or not model.layers:
        return 0

    kv_gb = model.kv_bytes_per_token * context_size / (1024 ** 3)
    # Unified memory has no separate card to run out of, and no bus to cross
    # when it does; the safety margin there is the OS's business, not ours.
    safety = 0.0 if shared else VRAM_SAFETY_GB
    full_margin = 0.0 if shared else FULL_OFFLOAD_MARGIN_GB

    if free_vram_gb >= model.weights_gb + kv_gb + COMPUTE_GB + safety + full_margin:
        return -1

    budget = free_vram_gb - safety - kv_gb - COMPUTE_GB
    if budget <= 0:
        return 0

    # Capped one short of the whole model: the partial path must never arrive
    # at the number the check above declined to give it.
    layers = min(int(budget / model.layer_gb), model.layers - 1)
    return layers if layers >= MIN_WORTHWHILE_LAYERS else 0


def verdict(model, total_vram_gb, free_vram_gb=None, shared=False):
    """Why this model is slow on this card, or None if it isn't.

    Two different problems with two different fixes, which is why they are two
    words rather than one "it's slow":

      * "oversized" - the model cannot fit this card whatever the user closes.
        A permanent mismatch, decided from the total alone, so it survives a
        machine whose free memory can't be read (AMD, Intel, anything without
        nvidia-smi).
      * "squeezed" - it would fit an idle card, but something else is holding
        the memory right now. A game, usually. Closing it actually fixes this.

    None is the common case and the default: no card, no reading, or nothing
    wrong.
    """
    if not total_vram_gb:
        return None
    if model.footprint_gb > usable_vram_gb(total_vram_gb, shared):
        return "oversized"
    if free_vram_gb is not None and model.footprint_gb > free_vram_gb:
        return "squeezed"
    return None


def explain(kind, total_vram_gb=None, free_vram_gb=None, measured=True):
    """One plain sentence for `kind`, with no route out of it.

    Deliberately ends without "press X to switch": the window and the console
    have different ways in (a settings screen and a typed word), and a shared
    module that names one of them is wrong in the other. Each interface adds
    its own sentence.

    `measured` is whether an answer has actually been slow. False is the
    startup check, which is describing what this machine is about to be like -
    opening that with "that was slow" is a claim about something the user has
    not experienced yet.
    """
    opening = "That was slow because" if measured else "Worth knowing:"

    if kind == "squeezed":
        held = ""
        if total_vram_gb and free_vram_gb is not None:
            held = f" - other programs are using {total_vram_gb - free_vram_gb:.1f}GB of it"
        return (
            f"{opening} your graphics card is nearly full{held}. "
            "Closing what else is running, a game or a browser usually, makes this much faster."
        )

    # Not "it runs from ordinary memory" any more, and not "a smaller one
    # answers in seconds": as much of an oversized model as fits now goes on
    # the card, which on the machine this was written for is the difference
    # between 0.8 tokens a second and 20. It is a trade of speed for quality,
    # which is a choice, not a fault.
    return (
        f"{opening} this model is bigger than your graphics card can hold, so part of it "
        "runs from ordinary memory. It works, but a smaller model would answer faster."
    )
