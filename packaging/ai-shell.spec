# PyInstaller build for the desktop window. Run from the repository root:
#
#     npm --prefix ai_shell_gui/frontend install
#     npm --prefix ai_shell_gui/frontend run build
#     pyinstaller packaging/ai-shell.spec
#
# The React app has to be built first: this only copies
# ai_shell_gui/frontend/dist, it doesn't produce it, and PyInstaller will
# happily build a bundle whose window opens on a missing file.
#
# One spec for all three platforms rather than three specs, because almost
# everything is shared and the parts that aren't are small and easier to
# compare when they sit next to each other.
#
# --onedir, not --onefile. A onefile build unpacks itself to a temp directory
# on every launch, which costs seconds and looks like malware to a scanner -
# and this app runs shell commands, so it starts that argument at a
# disadvantage. Users still download one file: the Windows job wraps this
# folder in an installer, and macOS ships it as a .app.
#
# Deliberately NOT bundled: llama-server and the model weights. ai_shell.runtime
# fetches the engine into the user's config folder on first run and llama.cpp
# caches the weights beside it, so those live in ~/.config/ai-shell (or
# %APPDATA%\ai-shell) and survive every update of this bundle. Putting several
# gigabytes of model in the download would mean re-downloading it for a
# one-line fix.

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH is the folder holding this file; the project is its parent.
ROOT = os.path.dirname(SPECPATH)

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

# A space reads better in a Start Menu and a Dock; Linux gets the plain name
# because the bundle there is a directory people type their way into.
APP_NAME = "AI Shell" if WINDOWS or MACOS else "ai-shell"
BUNDLE_ID = "dev.vuwar.ai-shell"


def icon_for(extension):
    """packaging/icons/app.<ext> if it's there, else None.

    Optional on purpose: a missing icon is a cosmetic problem, and a build that
    refuses to run without one is a worse one.
    """
    path = os.path.join(SPECPATH, "icons", f"app.{extension}")
    return path if os.path.exists(path) else None


# --- what goes in besides the code ------------------------------------------
datas = [
    # The built React app. The destination has to mirror the source layout -
    # ai_shell_gui/app.py looks for ai_shell_gui/frontend/dist under
    # sys._MEIPASS.
    (os.path.join(ROOT, "ai_shell_gui", "frontend", "dist"), os.path.join("ai_shell_gui", "frontend", "dist")),
]

# pywebview and pythonnet both ship their own PyInstaller hooks (declared as
# pyinstaller40 entry points), which is what collects WebView2's DLLs and the
# .NET runtime on Windows. Nothing to do here for those.

# The backend pywebview will actually load. It picks one at runtime with an
# import inside a function, which the dependency graph can't see, so the one
# this platform needs is named explicitly. Only one per platform: pulling in
# the Qt backend as a fallback would add ~100MB for a path that never runs.
if WINDOWS:
    hiddenimports = ["webview.platforms.winforms", "webview.platforms.edgechromium"]
elif MACOS:
    hiddenimports = ["webview.platforms.cocoa"]
else:
    hiddenimports = ["webview.platforms.gtk"]

# ai_shell.platforms picks its own class the same way. These are cheap and
# pure-Python, so all three are kept rather than trimmed to the current one -
# it keeps the bundle honest about what the package contains.
hiddenimports += collect_submodules("ai_shell")

excludes = [
    # Nothing here is ever imported at runtime, and between them they were 110MB
    # of a 156MB bundle.
    #
    # tkinter comes in through the standard library's own optional imports, and
    # the Qt bindings through pywebview's other backend. The data-science stack
    # is the openai package's doing: it names pandas, numpy and PIL in
    # type-checking and lazy-extra branches that never execute here, but that
    # PyInstaller's static analysis can't tell apart from real imports - and
    # pandas then drags in pyarrow, which alone was half the build.
    #
    # A clean virtualenv wouldn't have most of these installed to find, but the
    # exclusion is what makes a build off a developer's everyday interpreter
    # come out the same size as the release one.
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "matplotlib",
    "numpy",
    "pandas",
    "pyarrow",
    "PIL",
    "IPython",
    "pytest",
]


analysis = Analysis(
    [os.path.join(ROOT, "run_gui.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed binaries are a reliable way to get flagged by Defender
    console=False,  # this app owns a window; a console behind it is noise
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # whatever the runner is; the release matrix builds both
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_for("ico") if WINDOWS else icon_for("icns"),
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

if MACOS:
    app = BUNDLE(
        collect,
        name=f"{APP_NAME}.app",
        icon=icon_for("icns"),
        bundle_identifier=BUNDLE_ID,
        info_plist={
            "NSHighResolutionCapable": True,
            # The panel floats over other windows and is dragged by its own
            # surface; the standard title bar would fight both.
            "LSMinimumSystemVersion": "11.0",
            "CFBundleShortVersionString": os.environ.get("AI_SHELL_VERSION", "0.0.0"),
            "CFBundleVersion": os.environ.get("AI_SHELL_VERSION", "0.0.0"),
            # Asked for by name at runtime when the user says "open Safari" and
            # the app has to look through /Applications.
            "NSAppleEventsUsageDescription": "AI Shell runs the commands you confirm.",
        },
    )
