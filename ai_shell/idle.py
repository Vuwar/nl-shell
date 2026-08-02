"""When the app should let go of the graphics card, and nothing about how.

The weights cost the same whether the user asked something two seconds ago or
two hours ago, and on a machine with one graphics card the program that wants
those gigabytes next is usually a game. So the server is stopped when nobody
is using it, and the next model call starts it again - about four seconds,
once, after a long silence.

This module is only the timing half of that. It knows nothing about
llama.cpp, graphics cards or processes: how to stop, how to start, and how to
tell whether the card is wanted elsewhere all arrive as callbacks from
ai_shell.server, which is the half that owns those things. What is left is
small enough to test with a fake clock and no threads at all.

Two rules matter more than they look:

  * This module's lock is always taken before ai_shell.server's, never after.
    The release path runs on the watchdog thread and reaches into
    server.stop(), so the two locks meet on this thread every time a timeout
    expires. Taking them in the other order anywhere else is a deadlock.
  * Nothing is ever joined. server.stop() calls park() on the way past, and on
    the release path that is the watchdog thread asking itself to stop. park()
    raises a flag; the loop reads it and returns.
"""

import contextlib
import threading
import time

# How often the watchdog asks. Far below any timeout worth setting, and far
# above what asking costs.
POLL_SECONDS = 20

# How long the app has to have been quiet before a busy card is read as
# somebody else's need rather than a pause in the conversation. Releasing
# costs the user four seconds if their next question was seconds away, and a
# browser opening tabs can move a gigabyte - while a game takes longer than
# this just to reach its menu.
PRESSURE_GRACE = 30

# Re-entrant because the release path re-enters: check() holds this while it
# calls release(), which is server.stop(), which calls park() back into here.
_lock = threading.RLock()

_wake = None        # start the server again
_release = None     # stop it
_pressure = None    # is the card wanted elsewhere?
_idle_seconds = 0   # 0 or less disables everything below

_in_flight = 0      # model calls in progress; never release above zero
_released = False   # whether we are the reason there is no server
_last_activity = 0.0
_generation = 0     # which configure() the running watchdog belongs to
_watching = None    # the Event that ends it

# Patched by the tests, which drive check() rather than waiting for it.
_clock = time.monotonic


def configure(wake, release, pressure, idle_seconds):
    """Start watching a server that has just come up.

    Replaces any earlier watch: a model switch stops one server and starts
    another, and two watchdogs holding two sets of callbacks would take turns
    stopping whatever is running.
    """
    global _wake, _release, _pressure, _idle_seconds
    global _released, _last_activity, _generation, _watching

    with _lock:
        if _watching:
            _watching.set()          # the previous watchdog ends itself
        _wake, _release, _pressure = wake, release, pressure
        _idle_seconds = idle_seconds
        _released = False
        _last_activity = _clock()
        _generation += 1
        generation = _generation
        _watching = threading.Event() if idle_seconds > 0 else None
        waiting = _watching

    if waiting is None:
        return                       # turned off, so not even a thread
    threading.Thread(
        target=_watch, args=(generation, waiting),
        daemon=True, name="ai-shell-idle",
    ).start()


def _watch(generation, waiting):
    """Ask check() every POLL_SECONDS until this watch is over."""
    while not waiting.wait(POLL_SECONDS):
        with _lock:
            if generation != _generation:
                return               # a later configure() owns the watch now
        try:
            if check():
                return               # released; the next call starts it again
        except Exception:
            # Swallowed on purpose. pressure() reads a driver and release()
            # kills a process, and a watchdog that dies of one bad reading
            # turns this feature off for the rest of the session with no
            # symptom the user could report.
            pass


def check():
    """One pass of the policy. True when this released the server.

    A plain function rather than a step inside the thread, so the whole rule
    can be driven by a test with a fake clock.
    """
    global _released

    with _lock:
        if _released or _in_flight or _idle_seconds <= 0:
            return False

        quiet = _clock() - _last_activity
        if quiet < _idle_seconds:
            if quiet < PRESSURE_GRACE or not _asks_for_the_card():
                return False

        # Released under the lock, not after it. A model call arriving between
        # the decision and the stop would be sent to a server on its way out,
        # and active() raises _in_flight under this same lock - so there is no
        # window at all rather than a small one.
        _released = True
        _release()
        return True


def _asks_for_the_card():
    return bool(_pressure and _pressure())


@contextlib.contextmanager
def active():
    """Hold the server up for one model call, starting it first if it was released.

    Wrapped around ai_shell.llm's single completion call, which is the only
    place this app talks to a model. Harmless when nothing was ever
    configured - an unmanaged server has no watchdog, and this becomes a
    counter nobody reads.
    """
    global _in_flight, _released, _last_activity

    with _lock:
        _in_flight += 1
        wake = _wake if _released else None
    try:
        if wake:
            # Outside the lock: this starts a process and waits several
            # seconds for it, and holding the lock across that would stall
            # every other caller for the same seconds.
            wake()
            with _lock:
                _released = False
        yield
    finally:
        with _lock:
            _in_flight -= 1
            _last_activity = _clock()


def park():
    """Stop watching. Stops nothing else.

    ai_shell.server.stop() calls this on the way past, including from inside a
    release, on the watchdog's own thread - which is why this raises a flag
    rather than joining anything. The released flag goes up because after this
    there is no server, however it came to stop, and the next model call has to
    be the thing that starts it.
    """
    global _released, _watching

    with _lock:
        _released = True
        if _watching:
            _watching.set()
            _watching = None
