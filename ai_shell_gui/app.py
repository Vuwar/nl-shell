"""pywebview desktop window: same Session core as the CLI, a floating React panel instead of a console."""

import os
import socket
import sys
import threading

import webview

from ai_shell import Session, config, models, server, updater
from ai_shell.config import connection_error

def _frontend_root():
    """The folder holding the built React app.

    Next to this file, whether that's a checkout or an installed package. In a
    PyInstaller build it's neither: the spec copies the same
    `ai_shell_gui/frontend/dist` tree into the bundle, and sys._MEIPASS is
    where it was unpacked to. Reading __file__
    happens to work there too - PyInstaller rewrites it to point inside the
    bundle - but only by coincidence of how frozen modules are named, so the
    frozen case says where it means rather than relying on that.
    """
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "ai_shell_gui", "frontend", "dist")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")


HTML_PATH = os.path.join(_frontend_root(), "index.html")

# Input row is 56px + 1px border top and bottom; the window should hug it
# exactly, otherwise the panel shows dead space below the input line.
WINDOW_WIDTH = 560
INITIAL_HEIGHT = 58
MAX_HEIGHT = 560

# The square the window folds down to when the app loses focus. It stays on
# top like the panel does, so it has to earn the space it keeps: 48px is a
# comfortable click target and little more. The fold is anchored to the
# window's top-left corner (see _resize_window - the position never moves),
# which is where the status dot already sits, so the panel reads as collapsing
# into its own indicator rather than jumping somewhere new.
MINI_SIZE = 48


class Api:
    """Methods here are callable from JS as window.pywebview.api.<name>(...)."""

    def __init__(self):
        self.session = Session()

        # The model server is started here rather than before the window,
        # because loading several gigabytes of weights takes seconds the user
        # would otherwise spend looking at an empty desktop. The window opens
        # first and says what it's waiting for; anything typed in the meantime
        # is held by submit() until the server answers.
        self._startup = {"state": "starting", "message": "Starting the model…"}
        # The same start, as numbers rather than a sentence. Kept beside the
        # message rather than inside it because the two move at different
        # rates: the message changes once a percent, this several times a
        # second. None whenever there is nothing worth drawing.
        self._progress = None
        self._startup_lock = threading.Lock()
        self._settled = threading.Event()  # set once the server is up or has failed
        threading.Thread(target=self._start_server, daemon=True).start()

        # Looking for a newer version of the app, on its own thread, behind
        # everything else. It downloads what it finds and then waits - see
        # install_update() for the half the user has a say in.
        self._updater = updater.Updater()
        self._updater.start()

        # Leading underscore: pywebview auto-exposes every public attribute
        # of this object to JS by recursively walking it via dir()/getattr().
        # A plain `self.window` sends it straight into the raw native window
        # object, and WinForms' AccessibilityObject.Bounds.Empty property
        # returns a fresh Rectangle on every read, so pywebview's identity-
        # based cycle detection never triggers and it recurses until the
        # interpreter's stack blows up. Underscore-prefixed names are
        # skipped by that walk, so this keeps the reference without
        # triggering it.
        self._window = None  # set once create_window() returns

    # --- starting the model server ------------------------------------------
    def _set_startup(self, state, message):
        with self._startup_lock:
            self._startup = {"state": state, "message": message}
            if state == "ready":
                self._progress = None
            elif state == "failed" and self._progress:
                # Kept, not cleared: the grid freezes where it stopped, which
                # is the one moment the user is owed a picture of how far it
                # got. Only the phase changes.
                self._progress = dict(self._progress, phase="failed")

    def _set_progress(self, payload):
        with self._startup_lock:
            self._progress = payload

    def _start_server(self):
        try:
            server.ensure_running(
                on_status=lambda line: self._set_startup("starting", line),
                on_progress=self._set_progress,
            )
            self._set_startup("ready", "")
        except Exception as error:
            # Including the unexpected ones: this runs in a thread nobody is
            # waiting on, so an exception that escapes would leave the window
            # sitting on "Starting the model…" forever with no way to know why.
            self._set_startup("failed", str(error))
        finally:
            self._settled.set()

    def startup_status(self):
        """{"state": starting|ready|failed, "message", "notice", "progress"} -
        polled by the front end while it waits, so the panel can say what's
        taking the time.

        `notice` is the graphics-card explanation, or None. It arrives with
        "ready" rather than during the wait: it describes how the app will
        behave from here, which is not something to say while it is still
        loading and the user is already watching a progress line.

        `progress` is the weights download as numbers, or None when there is
        nothing worth drawing - which covers most of what a start does. The
        install screen is for the one wait that takes minutes, not for every
        wait.
        """
        with self._startup_lock:
            status = dict(self._startup)
            status["progress"] = self._progress
        # Claimed through the session so this and the slow-answer explanation
        # can't both land: they are the same sentence about the same card, and
        # hearing it twice with two different numbers reads as a broken app.
        status["notice"] = (
            self.session.claim_notice(server.fit_notice())
            if status["state"] == "ready"
            else None
        )
        return status

    def retry_startup(self):
        """Start the model server again after a start that failed.

        The window used to have one attempt: _start_server ran on a thread
        that finished, and there was no way back except closing the app.

        Every failure gets this, not a subset judged transient - deciding
        which errors are worth another go is guesswork, and being wrong about
        it strands somebody with no button on something that would have
        worked. It only saves a relaunch; it never does anything a relaunch
        wouldn't.
        """
        with self._startup_lock:
            if self._startup["state"] != "failed":
                return {"ok": False}  # already running, or already retrying
            self._startup = {"state": "starting", "message": "Starting the model…"}
            self._progress = None
            self._settled.clear()
        threading.Thread(target=self._start_server, daemon=True).start()
        return {"ok": True}

    def _wait_for_startup(self):
        """Block until a start attempt has settled; return its failure, or None.

        A loop rather than one wait, because a retry can clear _settled
        between the wait returning and the status being read - which would
        leave a caller looking at "starting", finding no failure, and
        translating against a server that isn't up. State and message are read
        together under the lock, so the answer is self-consistent.
        """
        while True:
            self._settled.wait()
            with self._startup_lock:
                state = self._startup["state"]
                if state != "starting":
                    return self._startup["message"] if state == "failed" else None

    # --- updating the app ----------------------------------------------------
    def update_status(self):
        """{"state": idle|checking|downloading|ready|failed, "version",
        "message", "notes_url"} - polled by the front end, which only puts
        anything on screen once the state is "ready"."""
        return self._updater.status()

    def install_update(self):
        """Hand over to the updater and close.

        The window has to go for the app's own files to be replaceable, and
        the script that does the replacing is already waiting for this process
        to end - so a successful start here is immediately followed by the
        same shutdown as quit(). It restarts the app when it's done.
        """
        result = self._updater.install()
        if result["ok"]:
            self.quit()
        return result

    def resize(self, width, height):
        """Called on every content-size change so the frameless panel hugs
        its content instead of the browser-window behavior of a fixed size,
        and on every frame of the fold into (and out of) the collapsed tile.
        The JS side eases the geometry itself frame-by-frame; this just
        applies whatever it asks for."""
        if not self._window:
            return
        width = max(MINI_SIZE, min(int(width), WINDOW_WIDTH))
        height = max(MINI_SIZE, min(int(height), MAX_HEIGHT))
        _resize_window(self._window, width, height)

    def window_focused(self):
        """Whether the OS considers this window the active one, or None where
        that can't be asked.

        The front end folds the panel away when the app isn't the one being
        used, and it can't take the document's word for that: WebView2's idea
        of focus is the control's, and it drifts - a window can be activated
        without its web view taking focus, and then deactivated without the
        document ever seeing a blur, leaving the panel sitting open over
        somebody else's work. Which window the OS has in front is the actual
        question, so this answers that one.
        """
        if sys.platform != "win32" or not self._window:
            return None  # the JS side falls back to document.hasFocus()
        try:
            import ctypes

            from webview.platforms.winforms import BrowserView

            hwnd = BrowserView.instances[self._window.uid].Handle.ToInt32()
            return bool(ctypes.windll.user32.GetForegroundWindow() == hwnd)
        except Exception:
            return None

    def check_connection(self):
        try:
            self.session.check_connection()
            return {"ok": True}
        except Exception:
            # The startup failure, when there was one, says what actually went
            # wrong; the generic message can only say that nothing answered.
            # Read rather than waited for - this is called from the front end's
            # poll, which must not block behind a start still in progress.
            with self._startup_lock:
                failure = (
                    self._startup["message"]
                    if self._startup["state"] == "failed"
                    else None
                )
            return {"ok": False, "error": failure or connection_error()}

    def submit(self, user_input):
        # Typing while the model is still loading is the normal case now that
        # the window opens first, so a request that arrives early waits for the
        # server instead of failing against one that isn't listening yet. The
        # front end already has its thinking dots up, and the startup line
        # underneath says what the wait is for.
        failure = self._wait_for_startup()
        if failure:
            return {
                "command": None,
                "search": None,
                "risk": None,
                "risk_reason": None,
                "explanation": failure,
                "does": [],
                "options": [],
                "notice": None,
                "error": True,
            }

        data = self.session.translate(user_input)
        command = data.get("command")
        options = data.get("options")
        if command or not isinstance(options, list):
            options = []
        return {
            "command": command,
            # Set when the answer has to come off the internet; the front end
            # then runs it through confirm() like any other pending action.
            "search": data.get("search"),
            "risk": data.get("risk"),
            # What the rules under the model objected to, so the confirmation
            # can name it. None when the model called it risky on its own.
            "risk_reason": data.get("risk_reason"),
            "explanation": data.get("explanation", ""),
            # What the command actually does, a line per step, for the
            # confirmation to show between the command and the buttons.
            # Empty when nothing could be said about it - see
            # ai_shell.describe.
            "does": data.get("does") or [],
            # the model occasionally puts junk here; keep only short strings
            "options": [o.strip() for o in options if isinstance(o, str) and o.strip()][:4],
            # Why that took so long, the first time it's worth saying.
            "notice": data.get("notice"),
        }

    def confirm(self, command=None):
        """Runs the pending command; returns {"ok", "output"} or {"ok", "reason"}.

        `command` is the user's edit of what was shown, or None to run the
        model's version. An edit is not re-classified for risk - it only
        reached an edit box by having been called risky.
        """
        return self.session.run_last(command)

    # --- choosing a model -----------------------------------------------------
    def list_models(self):
        """Every model, with what this machine can hold and what's downloaded.

        Rendered offline: "installed" comes from what a previous download
        recorded in settings, because resolving a model reference means asking
        HuggingFace, and a settings screen has to open on a train.
        """
        return {
            "ok": True,
            "models": models.catalog(
                config.HARDWARE.get("vram_gb"),
                config.HARDWARE.get("ram_gb"),
                config.HARDWARE.get("vram_shared", False),
                installed=config.installed_models(),
                current_id=config.MODEL,
            ),
            # A server the user started is theirs; the model it holds is not
            # ours to change, only to report.
            "editable": config.MANAGED_SERVER,
            "model_dir": config.MODEL_DIR,
        }

    def switch_model(self, model_id):
        """Change models, downloading the new one if it isn't here yet.

        The startup panel is reused for the wait, because from the front end's
        point of view this is the app starting again - which is exactly what
        it is: the old server is stopped and a new one comes up holding
        something else.
        """
        with self._startup_lock:
            if self._startup["state"] == "starting":
                return {"ok": False, "reason": "Still starting - try again in a moment."}
        if self.session._pending:
            return {"ok": False, "reason": "There's a command waiting for your answer first."}

        with self._startup_lock:
            self._startup = {"state": "starting", "message": "Switching model…"}
            self._settled.clear()

        def swap():
            try:
                result = server.switch_model(
                    model_id, on_status=lambda line: self._set_startup("starting", line)
                )
                if result["ok"]:
                    self._set_startup("ready", "")
                else:
                    self._set_startup("failed", result["reason"])
            except Exception as error:
                # Same reasoning as _start_server: nobody is waiting on this
                # thread, so an escaping exception would leave the panel on
                # "Switching model…" with no way to find out why.
                self._set_startup("failed", str(error))
            finally:
                self._settled.set()

        threading.Thread(target=swap, daemon=True).start()
        return {"ok": True}

    def clear(self):
        """Wipes the conversation behind a cleared screen - /clear and Esc.
        What's gone from view must be gone from the model's context too."""
        self.session.reset()
        return {"ok": True}

    def browse(self, path):
        """Contents of `path` - clicking a folder in a listing."""
        return self.session.list_directory(path)

    def open_path(self, path):
        """Opens `path` - clicking a file in a listing."""
        return self.session.open_path(path)

    def open_url(self, url):
        """Opens `url` in the user's browser - clicking a source under a web
        answer. Not open_path: a link off a search results page is the one
        thing in this window that didn't come from this machine, and the
        session checks it's really a web address before handing it to the OS."""
        return self.session.open_url(url)

    def opacity(self):
        """How see-through the window is, as a percentage - what the settings
        slider starts at."""
        return config.OPACITY

    def preview_opacity(self, percent):
        """Move the window to `percent` without recording it.

        This is a slider being dragged, so it arrives once per frame. Writing
        settings.json at that rate would be a lot of disk for a number that
        isn't final yet, and the value the user lets go of is the only one
        worth keeping."""
        applied = config._clamp_opacity(percent)
        if self._window:
            _set_window_opacity(self._window, applied)
        return applied

    def set_opacity(self, percent):
        """Move the window to `percent` and keep it there across restarts -
        the slider being let go of. Returns the value actually applied, which
        is the clamped one."""
        applied = config.set_opacity(percent)
        if self._window:
            _set_window_opacity(self._window, applied)
        return applied

    def quit(self):
        """Close the window - the JS side calls this for a bare "exit".

        Destroying on a short timer rather than inline: this runs inside
        pywebview's JS-bridge handler, and tearing the window down before
        that handler returns leaves the caller awaiting a reply from a
        window that no longer exists.
        """
        if self._window:
            threading.Timer(0.05, self._window.destroy).start()


def _free_port():
    """A port nothing is listening on, for pywebview's own file server.

    The built front end isn't loaded from disk - pywebview serves it over
    HTTP and points the window at localhost. Which port that is matters more
    than it sounds: with private_mode off, pywebview stops choosing a free
    one and uses a single fixed port (42001) shared by every application on
    the machine. Private mode has to stay off, because it wipes localStorage
    on every run and the settings screen keeps its choices there.

    So two copies of this app - an installed one and a checkout, or two
    checkouts - are handed the same port. The second one's server fails to
    bind, silently, on a daemon thread nobody is watching, and the window is
    still pointed at the address. It then renders the *other* copy's front
    end with this copy's Python behind it: a new backend answering through an
    old UI, which produces symptoms that look like impossible bugs. Asking
    the OS for a free port and naming it explicitly is what keeps the two
    apart.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def main():
    # Checked before anything else, because the alternative is a window that
    # opens on nothing and gives no hint why. Two ways to get here: a checkout
    # where nobody has run the front-end build yet, and a wheel that was built
    # without it (dist/ is a build product and isn't in the repository, so
    # `pip install` straight from git produces exactly that).
    if not os.path.exists(HTML_PATH):
        raise SystemExit(
            f"The desktop window's front end isn't built - nothing at {HTML_PATH}.\n"
            "From a checkout:\n"
            "    npm --prefix ai_shell_gui/frontend install\n"
            "    npm --prefix ai_shell_gui/frontend run build\n"
            "If you installed this with pip, install a release wheel rather than\n"
            "straight from the repository - the released wheels have it built in."
        )

    api = Api()

    screen = webview.screens[0]
    x = (screen.width - WINDOW_WIDTH) // 2
    y = int(screen.height * 0.16)

    window = webview.create_window(
        "AI Shell",
        HTML_PATH,
        js_api=api,
        width=WINDOW_WIDTH,
        height=INITIAL_HEIGHT,
        # pywebview's default min_size is (200, 100), which silently stops the
        # window from ever shrinking to the bare 58px input bar - and WinForms
        # enforces it against any resize, including the collapse to MINI_SIZE.
        min_size=(MINI_SIZE, MINI_SIZE),
        x=x,
        y=y,
        resizable=False,
        frameless=True,
        easy_drag=True,
        # pywebview's Windows backend has no real per-pixel window
        # transparency - transparent=True only blends the WebView2 control
        # against its own Form's default (plain gray) background, not the
        # desktop, which is what produced the gray box. shadow=True with
        # transparent=False takes the DWM path instead, giving a real
        # OS-composited soft shadow that blends into the desktop properly.
        shadow=True,
        on_top=True,
        transparent=False,
        background_color="#12101a",
    )
    api._window = window

    def _dress(window=window):
        _apply_window_chrome(window)
        _set_window_opacity(window, config.OPACITY)

    window.events.shown += _dress
    # private_mode defaults to True, which wipes localStorage on every run -
    # the settings screen persists its choices there. Turning it off is also
    # what makes the port explicit rather than optional; see _free_port.
    webview.start(private_mode=False, http_port=_free_port())


# SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER
_SWP_SIZE_ONLY = 0x0002 | 0x0004 | 0x0010 | 0x0200


def _resize_window(window, width, height):
    """Resize in place, without touching position, z-order or focus.

    pywebview's own resize() ends in a SetWindowPos that leaves out
    SWP_NOACTIVATE, which is harmless while the panel is being used and
    unusable for the collapse: the app has just lost focus, and a window that
    activates itself on every frame of the fold would yank the user out of
    whatever they clicked on - and then re-expand the panel it was folding
    away. Fixing the position at the same time is what anchors the collapse to
    the top-left corner: the window shrinks toward the status dot rather than
    around some point the user never chose.

    Windows-only detail. Elsewhere pywebview's resize() is the same shape (its
    GTK/Cocoa backends don't reactivate the window), so it stands in.
    """
    if sys.platform != "win32":
        window.resize(width, height)
        return
    try:
        import ctypes

        from webview.platforms.winforms import BrowserView

        form = BrowserView.instances[window.uid]
        # pywebview's API is in logical pixels and scales on the way out;
        # SetWindowPos speaks physical ones, so the same factor applies here.
        scale = getattr(form, "_scale", 1) or 1
        ctypes.windll.user32.SetWindowPos(
            form.Handle.ToInt32(),
            0,
            0,
            0,
            int(width * scale),
            int(height * scale),
            _SWP_SIZE_ONLY,
        )
    except Exception:
        # A pywebview whose internals moved: the panel still resizes, it just
        # gets pywebview's activating version of it.
        window.resize(width, height)


def _set_window_opacity(window, percent):
    """Make the whole window `percent` opaque, text included.

    WebView2 can't do per-pixel desktop transparency (tested: transparent
    pixels composite against the control's own background, and DWM acrylic
    never shows through), but a layered window CAN be uniformly translucent -
    the closest to liquid glass this stack allows. It was a fixed 86% until
    the settings screen grew a slider for it.

    Each backend keeps its window somewhere different, and none of them expose
    this through pywebview's own API. Best-effort like the rest of the native
    code here: a backend whose internals have moved leaves a solid window,
    which is a disappointing setting rather than a broken app.
    """
    fraction = max(0.05, min(1.0, percent / 100))
    try:
        if sys.platform == "win32":
            import ctypes

            from webview.platforms.winforms import BrowserView

            hwnd = BrowserView.instances[window.uid].Handle.ToInt32()
            GWL_EXSTYLE, WS_EX_LAYERED, LWA_ALPHA = -20, 0x80000, 0x2
            user32 = ctypes.windll.user32
            # The style is re-applied on every change rather than once at
            # startup: the alpha means nothing without it, and asking twice
            # costs nothing.
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            user32.SetLayeredWindowAttributes(hwnd, 0, round(255 * fraction), LWA_ALPHA)
        elif sys.platform == "darwin":
            from webview.platforms.cocoa import BrowserView

            BrowserView.instances[window.uid].window.setAlphaValue_(fraction)
        else:
            from webview.platforms.gtk import BrowserView

            # Needs a running compositor. Without one the call is accepted and
            # simply does nothing, which is the same outcome as the except below.
            BrowserView.instances[window.uid].window.set_opacity(fraction)
    except Exception:
        pass


def _apply_window_chrome(window):
    """Rounded native window (Windows 11).

    Frameless WinForms windows keep square corners by default, so the CSS
    panel's rounded outline used to sit inside a square dark window - the
    visible dark slivers at each corner. DWMWA_WINDOW_CORNER_PREFERENCE=ROUND
    makes the OS clip (and shadow) the window itself with antialiased rounded
    corners, so the panel can fill the window edge-to-edge. Translucency is
    _set_window_opacity's job, and it runs on every platform.

    Windows-only, and little is missing elsewhere: macOS rounds and shadows a
    frameless window itself, and on Linux that's the window manager's business
    rather than the app's.
    """
    if sys.platform != "win32":
        return
    try:
        from webview.platforms.winforms import BrowserView, DwmSetWindowAttribute

        hwnd = BrowserView.instances[window.uid].Handle.ToInt32()
        DwmSetWindowAttribute(hwnd, 33, 2)  # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
        DwmSetWindowAttribute(hwnd, 20, 1)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        # Windows draws its own thin border line around rounded windows; hide
        # it (DWMWA_BORDER_COLOR = DWMWA_COLOR_NONE) - focus glow is done in CSS.
        DwmSetWindowAttribute(hwnd, 34, 0xFFFFFFFE)
    except Exception:
        pass  # older pywebview or Windows 10: square opaque corners, still functional


if __name__ == "__main__":
    main()
