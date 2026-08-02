"""How much model this computer can hold.

A thin composition of the two probes on ai_shell.platforms.current, kept out
of config.py because the interesting part isn't reading the numbers - it's
that reading them costs something. The GPU probe shells out to nvidia-smi,
which is tens of milliseconds on a good day and seconds on a machine with a
sleeping discrete GPU that has to spin up to answer.

That cost is paid once, on the first run, and the answer is written into the
settings file. Every launch after that reads a number off disk.
"""

from ai_shell.platforms import current


def probe():
    """{"ram_gb", "vram_gb"} for this machine, either of which may be None
    when the platform couldn't work it out. Never raises: a probe that fails
    is a machine we know nothing about, which is a case the caller already
    handles."""
    try:
        ram_gb = current.total_ram_gb()
    except Exception:
        ram_gb = None
    try:
        vram_gb = current.vram_gb()
    except Exception:
        vram_gb = None
    try:
        shared = current.vram_is_shared()
    except Exception:
        shared = False
    return {
        "ram_gb": round(ram_gb, 1) if ram_gb else None,
        "vram_gb": round(vram_gb, 1) if vram_gb else None,
        # Recorded rather than re-asked: it describes the machine the recorded
        # choice was made against, exactly like the two numbers above.
        "vram_shared": shared,
    }


def describe(hardware):
    """One line naming what was found, for the first-run message that explains
    why a particular model was chosen."""
    ram, vram = hardware.get("ram_gb"), hardware.get("vram_gb")
    if vram and ram:
        return f"{vram:g}GB GPU memory, {ram:g}GB RAM"
    if vram:
        return f"{vram:g}GB GPU memory"
    if ram:
        return f"{ram:g}GB RAM, no GPU detected"
    return "unknown hardware"
