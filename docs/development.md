# Working on AI Shell

Running it from a checkout, the test suite, and how a release is built and
shipped. For what the app is and how to install it, see the
[README](../README.md); for how it works inside, see
[how-it-works.md](how-it-works.md).

## Run from source

1. Install Python 3.10+ (check with `python --version`; on macOS and Linux it
   may be `python3`).

2. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

   (llama.cpp's server exposes an OpenAI-compatible API, so the `openai`
   package is used as the client - no OpenAI account or key needed.
   `pywebview` is used for the desktop window, and needs a web view from
   the OS:

   - **Windows** - the WebView2 runtime, which ships with Windows 10/11.
   - **macOS** - its own WebKit, reached through the `pyobjc` packages that
     `pip install -r requirements.txt` pulls in for you.
   - **Linux** - GTK and WebKit, which pip can't install. Get them from your
     package manager first, then the Python binding:

     ```
     # Debian/Ubuntu
     sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
     # Fedora
     sudo dnf install python3-gobject gtk3 webkit2gtk4.1
     ```

     The console REPL needs none of this - skip it if you only want `run_cli.py`.)

   The GUI's front end is a React app that needs building once (and again
   after any front-end edit):

   ```
   cd ai_shell_gui/frontend
   npm install
   npm run build
   ```

3. Run it:

   ```
   python run_gui.py     # desktop window
   python run_cli.py     # console REPL
   ```

   There is no third thing to install. If `llama-server` isn't already on
   your PATH, the app downloads a llama.cpp build for your machine (~30MB)
   into its own config folder the first time it runs, then starts it, waits
   for it to be ready, and shuts it down on exit. Nothing is put on your
   PATH and nothing needs an administrator - uninstalling is deleting
   `llama.cpp/` from the config folder named below.

   **The first run also downloads the model** - a few GB, so it can take a
   while depending on your connection. Later runs reuse the cached weights.

   The desktop window opens straight away and says what it's waiting for
   underneath the input line; you can type your first request while the model
   is still loading and it will answer as soon as it can. The console REPL
   waits for the server first, printing the same progress, because a prompt
   that can't answer yet is worse than a pause. Either way a warm start is
   about 8 seconds, nearly all of it llama.cpp reading the weights into
   memory.

   The window floats above everything else so it's there the moment you want
   it, and it earns that by getting out of the way when you don't: click into
   another app and it folds down to a small tile - still showing whether
   anything is running, or finished while you were away - and unfolds exactly
   as you left it when you click the tile or give it focus again. `/settings`
   turns that off if you'd rather it stayed put, and has an opacity slider for
   how much of your desktop shows through the window.

   The build it fetches follows the same decision as the model size: Vulkan
   when the model will be offloaded to a GPU, CPU-only otherwise. Vulkan
   rather than CUDA because it's one 30MB archive that works on any vendor,
   against 600MB of build plus CUDA runtime that has to match your driver.
   On an NVIDIA card CUDA is somewhat faster - if you want that, install
   [a CUDA build](https://github.com/ggml-org/llama.cpp/releases) yourself
   and set `AI_SHELL_SERVER` to it. A binary you name is always used as
   given; the app only installs one when it can't find any.

## Tests

```
python -m unittest discover -s tests
```

Standard library `unittest`, no test framework - the requirements file is two
packages and running the tests shouldn't make it three. The default run takes
about a fifth of a second: the model is stubbed and no page is fetched, so it
needs neither the internet nor a model server.

The tests that genuinely need both are kept apart and skip themselves unless
you ask:

```
AI_SHELL_LIVE_TESTS=1 python -m unittest tests.test_live
```

Those fetch real pages and run a real search, so they're slow and they depend
on sites belonging to other people. When a search engine decides it wants a
CAPTCHA, they skip rather than fail - an outage somewhere else shouldn't read
as a broken build.

Nearly every case is a bug that actually happened, and says so in a comment:
Wikipedia locking the reader out via `robots.txt`, `python.org` sending gzip
unasked and becoming mojibake, a weather page whose text is labels with the
numbers stripped out, the model citing five sources at once or none, citing
pages that don't contain the figure it quoted, and inventing a release date
out of two real ones.

## Builds and releases

Every push to `main` and every pull request builds all four targets and runs
the tests on Windows, macOS and Linux (`.github/workflows/build.yml`). Nothing is
published - the builds land as artifacts on the run, downloadable from the
Actions tab for two weeks. The point is that `main` is always known to be
buildable, so releasing is never the moment you find out the macOS job has been
broken for a fortnight.

### Versioning

The version number is not written by hand. It comes from the commit messages,
via [Conventional Commits](https://www.conventionalcommits.org/) - the subject
line of each commit says what kind of change it is, and that decides the bump:

| Commit subject | Bump | Example |
|---|---|---|
| `fix: ...` | patch | `0.1.0` → `0.1.1` |
| `feat: ...` | minor | `0.1.0` → `0.2.0` |
| `feat!: ...`, or `BREAKING CHANGE:` in the body | minor while below 1.0 | `0.1.0` → `0.2.0` |
| `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `build:`, `perf:` | none | - |

A scope is optional: `fix(gui): panel reopens after it folds away`.

Breaking changes bump the *minor* rather than the major because this is a `0.x`
project, which is the standard way of saying the interface can still move.
Going to 1.0 is a deliberate act - put `Release-As: 1.0.0` in a commit body
when you mean it.

Pull request titles are checked against this format, because a squash merge
turns the title into the commit subject. The check failing doesn't block a
merge unless you add it to branch protection; it's there so a subject that
would silently count for nothing gets noticed. A commit that doesn't parse
isn't rejected - it just contributes no bump and no changelog line.

### Releasing

There's nothing to tag. [release-please](https://github.com/googleapis/release-please)
watches `main` and keeps a pull request open - *"chore(main): release 0.2.0"* -
holding the version bump and the changelog for everything merged since the last
release. It updates itself as you merge more. Nothing is built or published
while it sits there, so it doubles as a preview of what the next release would
be.

**Merging that PR is the release.** It tags the commit, drafts a GitHub release
with the changelog, builds all four targets plus the wheel, and attaches them.
The release stays a **draft** until you press publish.

Two files are updated for you and shouldn't be edited by hand: `__version__` in
`ai_shell/__init__.py` (which `pyproject.toml` reads, so it's the only place the
version lives) and the wheel filename in the pip instructions above.

One repository setting is required for any of this to work: **Settings →
Actions → General → Allow GitHub Actions to create and approve pull requests**.
Without it, release-please can't open its PR and the job fails with a
permissions error.

It's all one workflow file. Building and releasing are the same pipeline with
one extra step on the end, and splitting them meant every push to main ran two
workflows, each needing a rule for skipping the other one's commits.

To build locally:

```
npm --prefix ai_shell_gui/frontend install && npm --prefix ai_shell_gui/frontend run build
pip install pyinstaller
pyinstaller --noconfirm packaging/ai-shell.spec
```

The app lands in `dist/` - `dist/AI Shell/AI Shell.exe` on Windows,
`dist/AI Shell.app` on macOS, `dist/ai-shell/ai-shell` on Linux. Building the
front end first is not optional: the spec copies `ai_shell_gui/frontend/dist`,
it doesn't produce it. (It won't silently ship an empty window - the app checks
and says what's missing - but it also won't build one that works.)

The pip package is the same front-end-first story, `python -m build` instead of
PyInstaller:

```
npm --prefix ai_shell_gui/frontend install && npm --prefix ai_shell_gui/frontend run build
pip install build && python -m build
```

Two things are deliberately *not* in the bundle. The inference engine and the
model stay out, because `ai_shell/runtime.py` already fetches them into the
user's config folder on first run - so the download is ~40MB instead of several
gigabytes, and updating the app doesn't re-download the weights. The build is
also `--onedir` rather than `--onefile`: a onefile executable unpacks itself to
a temp folder on every launch, which costs seconds and looks like malware to a
heuristic scanner, and an app whose job is running shell commands starts that
argument at a disadvantage. Windows users still download one file -
`packaging/windows/installer.iss` wraps the folder in an installer, which also
fetches the WebView2 runtime on the rare machine that hasn't got it.

### Updating an installed copy

Installed copies update themselves. On launch, in the background,
`ai_shell/updater.py` asks the releases page whether there's a newer version,
downloads the one asset matching how this copy was installed, and then stops:

```
Version 0.2.0 is ready to install          [ Restart ]
```

The download is automatic because it costs the user nothing to have it ready.
The install is not, because an app that runs shell commands shouldn't replace
itself mid-sentence. Clicking Restart closes the panel, swaps the app and
opens it again; in the console REPL the same thing is the `update` command.

How the swap happens depends on how the app got there, which the updater works
out for itself:

| How it was installed | How it updates |
|---|---|
| Windows installer (`unins000.exe` beside the exe) | runs the new setup silently - the `AppId` makes it an upgrade, not a second copy |
| Windows portable zip | the folder is swapped for the new one |
| macOS `.app` | the bundle is swapped |
| Linux tarball | the folder is swapped |
| pip | `pip install --upgrade` of the downloaded wheel |
| a checkout of this repository | never - that's what `git pull` is for |

Every one of those replaces files the running process has open, which Windows
forbids outright. So the app doesn't do it: it writes a small `.cmd` or `.sh`
script, starts it detached and quits, and the script waits for the process to
disappear before touching anything. The old copy is moved aside *before* the
new one lands, and put back if the new one won't move in - a failed update
leaves a working app rather than half of two.

Untouched by all of this: `%APPDATA%\ai-shell` (or `~/.config/ai-shell`), where
the model weights and llama.cpp live. That's why an update is tens of megabytes
and not several gigabytes.

Two ways to turn it off - `"auto_update": false` in `settings.json`, or
`AI_SHELL_AUTO_UPDATE=0` - after which nothing is checked and nothing is
downloaded. The releases page is checked at most once every six hours, so
launching the app five times in an afternoon is one request. Draft releases are
invisible to it: GitHub's "latest" is the newest *published* release, so
pressing publish is what actually ships a version to people.
