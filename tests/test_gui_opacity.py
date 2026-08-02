"""ai_shell_gui - the window opacity slider.

Two halves worth testing. The platform dispatch, because each backend keeps
its window somewhere different and a wrong guess is silent - the window simply
stays solid. And the API the slider calls, because dragging it must not write
settings.json on every frame.

The backends are faked. A real one would need a window on screen, which the CI
that runs this has no such thing as.
"""

import sys
import unittest
from unittest import mock

from ai_shell import config

try:
    from ai_shell_gui import app as gui
except Exception:  # pragma: no cover - pywebview absent from this environment
    gui = None


class FakeWindow:
    uid = "master"


class FakeForm:
    """WinForms' BrowserForm, as far as this code is concerned: something with
    a window handle on it."""

    HWND = 4242

    def __init__(self):
        self.Handle = mock.Mock()
        self.Handle.ToInt32.return_value = self.HWND


class FakeNSWindow:
    def __init__(self):
        self.alpha = None

    def setAlphaValue_(self, value):
        self.alpha = value


class FakeGtkWindow:
    def __init__(self):
        self.alpha = None

    def set_opacity(self, value):
        self.alpha = value


def fake_backend(module_name, instance):
    """The named pywebview backend module, holding `instance` under the uid
    FakeWindow uses."""
    backend = mock.Mock()
    backend.BrowserView.instances = {FakeWindow.uid: instance}
    return mock.patch.dict(sys.modules, {module_name: backend})


@unittest.skipIf(gui is None, "pywebview isn't installed")
class PlatformDispatch(unittest.TestCase):
    def test_windows_makes_the_window_layered_and_sets_its_alpha(self):
        # Same mechanism the rounded-corner chrome already uses, so the alpha
        # is 0-255 rather than a fraction, and the layered style has to be on
        # the window before the alpha means anything.
        user32 = mock.Mock()
        user32.GetWindowLongW.return_value = 0
        with mock.patch.object(gui.sys, "platform", "win32"), \
             mock.patch("ctypes.windll", create=True) as windll, \
             fake_backend("webview.platforms.winforms", FakeForm()):
            windll.user32 = user32
            gui._set_window_opacity(FakeWindow(), 40)

        WS_EX_LAYERED, LWA_ALPHA = 0x80000, 0x2
        user32.SetWindowLongW.assert_called_once_with(FakeForm.HWND, -20, WS_EX_LAYERED)
        user32.SetLayeredWindowAttributes.assert_called_once_with(
            FakeForm.HWND, 0, 102, LWA_ALPHA)  # 40% of 255

    def test_macos_sets_the_native_windows_alpha(self):
        native = FakeNSWindow()
        holder = mock.Mock(window=native)
        with mock.patch.object(gui.sys, "platform", "darwin"), \
             fake_backend("webview.platforms.cocoa", holder):
            gui._set_window_opacity(FakeWindow(), 65)
        self.assertAlmostEqual(native.alpha, 0.65)

    def test_anything_else_goes_through_gtk(self):
        native = FakeGtkWindow()
        holder = mock.Mock(window=native)
        with mock.patch.object(gui.sys, "platform", "linux"), \
             fake_backend("webview.platforms.gtk", holder):
            gui._set_window_opacity(FakeWindow(), 100)
        self.assertAlmostEqual(native.alpha, 1.0)

    def test_a_backend_that_refuses_leaves_the_window_alone_rather_than_raising(self):
        # A window that stays solid is a disappointing setting. A window that
        # takes the app down with it is a bug report.
        backend = mock.Mock()
        backend.BrowserView.instances = {}  # no window under that uid
        with mock.patch.object(gui.sys, "platform", "win32"), \
             mock.patch.dict(sys.modules, {"webview.platforms.winforms": backend}):
            gui._set_window_opacity(FakeWindow(), 50)


@unittest.skipIf(gui is None, "pywebview isn't installed")
class SliderApi(unittest.TestCase):
    def make(self):
        """An Api with a window attached and no model server behind it."""
        for patch in (mock.patch.object(gui.server, "ensure_running"),
                      mock.patch.object(gui.updater, "Updater")):
            patch.start()
            self.addCleanup(patch.stop)
        api = gui.Api()
        api._settled.wait(timeout=5)
        api._window = FakeWindow()
        return api

    def setUp(self):
        before = config.OPACITY
        self.addCleanup(lambda: setattr(config, "OPACITY", before))
        self.applied = []
        patch = mock.patch.object(
            gui, "_set_window_opacity",
            lambda window, percent: self.applied.append(percent))
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_current_value_is_readable_for_the_first_render(self):
        api = self.make()
        with mock.patch.object(config, "OPACITY", 71):
            self.assertEqual(api.opacity(), 71)

    def test_setting_applies_persists_and_reports_the_clamped_value(self):
        api = self.make()
        with mock.patch.object(config, "_write_settings") as written:
            self.assertEqual(api.set_opacity(500), 100)
        self.assertEqual(self.applied, [100])
        self.assertEqual(written.call_args[0][0]["opacity"], 100)

    def test_a_preview_moves_the_window_without_touching_the_disk(self):
        # This is the drag. It arrives once per frame, and settings.json is on
        # a disk that doesn't need to hear about every one of them.
        api = self.make()
        with mock.patch.object(config, "_write_settings") as written:
            self.assertEqual(api.preview_opacity(45), 45)
        self.assertEqual(self.applied, [45])
        written.assert_not_called()
        self.assertNotEqual(config.OPACITY, 45)

    def test_a_preview_is_clamped_like_a_saved_value(self):
        api = self.make()
        with mock.patch.object(config, "_write_settings"):
            self.assertEqual(api.preview_opacity(1), config.MIN_OPACITY)
        self.assertEqual(self.applied, [config.MIN_OPACITY])


if __name__ == "__main__":
    unittest.main()
