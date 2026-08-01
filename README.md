# AI Shell (v0)

A tiny terminal where you type plain English and it runs real shell commands
for you — PowerShell on Windows, bash on macOS and Linux. Available as a
console REPL or a desktop window.

## Setup

This runs fully locally via [llama.cpp](https://github.com/ggml-org/llama.cpp)
— no API key, no cost, and nothing you type is sent to anyone's model. The app
installs the inference engine, downloads the model, and starts and stops the
server itself, so there's nothing to set up beyond Python and no background
service to remember to launch.

The one exception is [asking it to look something up](#looking-things-up-on-the-web):
a web search sends that search query to DuckDuckGo, the same as typing it into
a search box would. Nothing else leaves the machine, and it only happens when
the question can't be answered without it.

Three ways in, none of them better than the others — pick whichever suits how
you already install things. All three are tens of megabytes, because the
inference engine and the model are fetched on first run rather than shipped
inside the download.

### One command

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Vuwar/nl-shell/main/packaging/install.ps1 | iex
```

**macOS / Linux**:

```sh
curl -fsSL https://raw.githubusercontent.com/Vuwar/nl-shell/main/packaging/install.sh | sh
```

Downloads the latest release for your machine and puts it where the OS expects
it — Start Menu on Windows, `/Applications` on macOS, `~/.local` on Linux.
Nothing needs an administrator. Set `AI_SHELL_VERSION` first to pin a release;
on Windows, `$env:AI_SHELL_PORTABLE = "1"` unpacks a folder instead of running
the installer. Both scripts are short and readable —
[install.ps1](packaging/install.ps1), [install.sh](packaging/install.sh) —
and reading a script before piping it into a shell is a good habit.

You only do this once. After that the app keeps itself current: it downloads
new releases in the background and offers a Restart button when one is ready —
see [Updating an installed copy](#updating-an-installed-copy), including how to
switch it off.

### pip

If you already have Python 3.10+, this gets you both the window and the console
REPL, plus `ai_shell` as an importable package:

```sh
pip install "$(curl -fsSL https://api.github.com/repos/Vuwar/nl-shell/releases/latest \
  | grep -o 'https://[^"]*\.whl')"
```

On Windows, or if you'd rather see what you're installing: download the `.whl`
from the [releases page](https://github.com/Vuwar/nl-shell/releases) and
`pip install` the file.

```
ai-shell          # console REPL
ai-shell-gui      # desktop window
```

The distribution is called `nl-shell` because `ai-shell` was already taken on
PyPI by an unrelated project. It isn't on PyPI at all yet — the wheels are
attached to each [release](https://github.com/Vuwar/nl-shell/releases), which
is why there's no plain `pip install nl-shell` to give you. The command above
asks the releases API which wheel is current rather than naming a version,
because a version written into this file would be wrong one release later.

Installing straight from git (`pip install git+https://...`) gets you a working
`ai-shell` but a `ai-shell-gui` that has nothing to draw: the React front end is
a build product that isn't in the repository, and only the released wheels have
it built in. Use a wheel, or [build from source](#or-run-from-source).

On Linux, add the system GTK/WebKit packages listed below, then
`pip install "nl-shell[gtk]"` for the Python binding.

### Download a build by hand

Everything is on the
[releases page](https://github.com/Vuwar/nl-shell/releases):

| | File | Notes |
|---|---|---|
| **Windows** | `AI-Shell-<version>-windows-x64-setup.exe` | Installs per-user, no administrator. `...-windows-x64.zip` is the same app as a folder if you'd rather not run an installer. |
| **macOS** | `AI-Shell-<version>-macos-arm64.zip` (Apple Silicon) or `-macos-x64.zip` (Intel) | Unzip into `/Applications`. |
| **Linux** | `ai-shell-<version>-linux-x64.tar.gz` | Needs GTK and WebKit2GTK 4.1 from your package manager (see below). Built on Ubuntu 22.04, so an older distro may not have a new enough glibc. |

### About the warnings you'll see

These builds aren't signed with a paid certificate, so both desktop OSes say so
on first launch:

- **Windows** — SmartScreen shows "Windows protected your PC". *More info* →
  *Run anyway*.
- **macOS** — Gatekeeper refuses an app from an "unidentified developer".
  Right-click the app → *Open* → *Open*, or
  `xattr -dr com.apple.quarantine "/Applications/AI Shell.app"`.

The one-command installers clear the macOS one for you, which is worth knowing
you're agreeing to. Neither warning means anything is wrong with the download;
they mean nobody has paid a certificate authority about it.

### Or run from source

1. Install Python 3.10+ (check with `python --version`; on macOS and Linux it
   may be `python3`).

2. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

   (llama.cpp's server exposes an OpenAI-compatible API, so the `openai`
   package is used as the client — no OpenAI account or key needed.
   `pywebview` is used for the desktop window, and needs a web view from
   the OS:

   - **Windows** — the WebView2 runtime, which ships with Windows 10/11.
   - **macOS** — its own WebKit, reached through the `pyobjc` packages that
     `pip install -r requirements.txt` pulls in for you.
   - **Linux** — GTK and WebKit, which pip can't install. Get them from your
     package manager first, then the Python binding:

     ```
     # Debian/Ubuntu
     sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
     # Fedora
     sudo dnf install python3-gobject gtk3 webkit2gtk4.1
     ```

     The console REPL needs none of this — skip it if you only want `run_cli.py`.)

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
   PATH and nothing needs an administrator — uninstalling is deleting
   `llama.cpp/` from the config folder named below.

   **The first run also downloads the model** — a few GB, so it can take a
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
   another app and it folds down to a small tile — still showing whether
   anything is running, or finished while you were away — and unfolds exactly
   as you left it when you click the tile or give it focus again. `/settings`
   turns that off if you'd rather it stayed put.

   The build it fetches follows the same decision as the model size: Vulkan
   when the model will be offloaded to a GPU, CPU-only otherwise. Vulkan
   rather than CUDA because it's one 30MB archive that works on any vendor,
   against 600MB of build plus CUDA runtime that has to match your driver.
   On an NVIDIA card CUDA is somewhat faster — if you want that, install
   [a CUDA build](https://github.com/ggml-org/llama.cpp/releases) yourself
   and set `AI_SHELL_SERVER` to it. A binary you name is always used as
   given; the app only installs one when it can't find any.

## Which model you get

There's no single right model here: the same app has to work on a laptop with
8GB of shared memory and on a desktop with a 24GB card, and a model that suits
one is either impossible or a waste on the other.

So on first run the app measures the machine — RAM, and GPU memory if it finds
a GPU — and picks the largest model that will genuinely fit, from 1.5B up to
32B. The choice is written to a settings file and reused after that, so the
measuring happens once.

Two things worth knowing about how it chooses:

- **A GPU decides it, unless the GPU is too small to be worth using.** The
  same model runs an order of magnitude faster on the card than in RAM. But a
  card that can only hold the smallest model is ignored — a machine with 32GB
  of RAM and a 2GB display adapter should not be handed the weakest model on
  the list.
- **Without a GPU it stops at 7B, however much RAM you have.** Fitting isn't
  the same as being usable. CPU inference is bound by memory bandwidth, so a
  14B answers at a couple of tokens a second and a 32B at well under one —
  which for a shell prompt is the same as not working.
- **The card's memory isn't all yours.** Your desktop, your compositor and a
  browser are holding some of it before this app opens anything, so the budget
  is what's left after a share is set aside for them. Sizing against the card's
  full capacity looks fine and isn't: a model that doesn't quite fit gets paged
  across the bus a piece at a time, which is *slower* than never having touched
  the card at all.
- **As much of the model goes on the card as fits, not all or nothing.** How
  much is decided at each start, from what's free at that moment. Measured on
  an 8GB card with a browser and a few other things open, running a 7B-Q4:

  | layers on the card | tokens/sec |
  |---|---|
  | none (all processor) | 16.5 |
  | 24 of 28 | 35.0 |
  | 27 of 28 | 42.2 |
  | all 28 | **6.9** |

  The last layer also carries the output tensor, and asking for it tips the
  request past what the driver will hand out — at which point *less* ends up
  on the card, not more, and every token crosses the bus. So "all of it if it
  fits, none of it otherwise" could only choose the top of that curve or the
  bottom, and on this class of card it chose the bottom. Filling to a margin
  gets most of the win and cannot land on the cliff.

  This is also why a model bigger than your card is worth offering rather than
  refusing: the same 8GB card runs a 7B-Q6 it cannot hold at about 20 tokens a
  second, which is a trade of speed for quality rather than a wall.

Every size is the same model family (Qwen2.5-Coder). That's deliberate: the
system prompt asks for a strict JSON shape and a fair number of rules at once,
and families differ a lot in how reliably they hold that. Sizes within a
family don't, so size is safe to vary.

### Changing it, and why an answer was slow

Type `model` in the console or open `/settings` in the window to see the whole
list and switch. Each row says what switching costs — a model downloaded once
switches back instantly — and whether this machine runs it slower, or is too
small for it to be worth trying at all.

If an answer takes far longer than usual, the app says why rather than leaving
you watching dots. The usual cause is something else using the graphics card —
a game, or a browser with a lot of tabs — and closing it is the whole fix.
Where the model is simply too big for the card it was picked for, switching to
a smaller one is; the app will say which of the two it is.

Nothing is changed on your behalf either way. Being told your card is full and
being moved onto a different model without asking are not the same thing, and
the second is not the app's decision to make.

### The download, and losing your connection halfway through it

The weights land in `models/` beside the settings file — `%APPDATA%\ai-shell\`
on Windows, `~/.config/ai-shell/` elsewhere. They're several gigabytes, so
they're fetched in a way that expects a connection to fail: a dropped transfer
carries on from the byte it stopped at rather than starting over, and the app
retries by itself, with a growing wait between attempts, before it says
anything to you.

If it does eventually give up, what already arrived stays on disk. The desktop
window puts a **Try again** button on the error; in the console, running
`ai-shell` again does the same thing. Either way it resumes rather than
restarting. So does closing the app mid-download and opening it later.

Every file is checked against the checksum HuggingFace publishes for it before
it's used. That's a pass over the whole download, so you'll see a short
"Checking the download…" at the end of the first run — a few seconds, bounded
by how fast the disk reads rather than by anything clever.

To override any of it:

| Setting | What it does |
| --- | --- |
| `AI_SHELL_MODEL_REF` | The model to serve, as a HuggingFace ref — e.g. `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF:Q4_K_M` |
| `AI_SHELL_MODEL_DIR` | Where to keep the weights, if the default drive is the wrong one for 20GB |
| `AI_SHELL_SERVER` | Full path to a `llama-server` of your own. Also turns the auto-install off |
| `AI_SHELL_PORT` | Port to run it on (default 8080) |
| `AI_SHELL_CONTEXT` | Context window in tokens (default 8192) |
| `AI_SHELL_BASE_URL` | Use a server you started yourself, and don't start one |
| `AI_SHELL_MODEL` | The model name sent in API calls — only matters with `AI_SHELL_BASE_URL` |

The persistent version of the same choices lives in `settings.json`, in
`%APPDATA%\ai-shell\` on Windows and `~/.config/ai-shell/` elsewhere. Delete
it to have the machine measured again.

Still prefer [Ollama](https://ollama.com)? It works unchanged — it speaks the
same API, and setting `AI_SHELL_BASE_URL` tells the app not to start a server
of its own:

```
set AI_SHELL_BASE_URL=http://localhost:11434/v1
set AI_SHELL_MODEL=qwen2.5-coder:7b
```

## Try it

```
ai> list all files in my downloads folder
ai> create a folder called test-project on my desktop
ai> what's using the most disk space in this folder
ai> delete the file called old_notes.txt
ai> what's the latest version of python
```

Notice: the delete will pause and ask you to confirm before running, because
it's classified as risky. Read-only or reversible stuff just runs. The last
one isn't a command at all — see below.

## Looking things up on the web

A local model has no internet and no idea what year it is, and the honest
consequence used to be that asking one for a current fact got you either a
refusal or a confident invention. Now a question the model can't answer from
its own weights turns into a web search instead: it says what to look up, the
shell does the looking, and the model is asked only to read the results back.

```
ai> what's the latest version of python
→ Looking that up on the web.
The latest version of Python is 3.14.6, released on June 10, 2026. [1][2]
[1] Download Python | Python.org
    https://www.python.org/downloads/  · read
[2] Python Release Python 3.14.0 | Python.org
    https://www.python.org/downloads/release/python-3140/  · read
```

The search finds which pages might answer the question; the shell then opens
them and reads them. Those are separate jobs and only the first one needs a
datacentre, so only the first one is borrowed. It matters because a search
result's snippet is a sentence written to earn a click, and handing a small
model five of those is asking it to do the hard version of the job — the
`· read` mark says which sources the answer actually came out of, rather than
which ones it saw a teaser for. A page that won't open keeps the snippet it
came with, so this can improve an answer and can't degrade one.

Two things get checked before an answer is shown. A citation has to name a
result that contains something the answer says — the model is otherwise happy
to credit the top result for a figure printed only on the fifth. And a date the
answer states has to appear in the pages that were read; if it doesn't, the
model is asked once more, and if it's still inventing dates the sources go up
with no summary at all.

The sources are always shown, and in the desktop window they're clickable —
because the summary above them is a convenience and they are the actual
result. That distinction matters more on a small model: reading five snippets
into one true sentence is a much harder job than translating a request into a
command, and it's the job where a small model goes wrong invisibly, producing
a fluent sentence the sources never supported. So on anything below 7B the app
says so once per session, above the links, rather than presenting the guess
with the same confidence a 14B's answer would get.

Searches go to DuckDuckGo's no-key HTML endpoint — there's nothing to sign up
for and nothing to configure, which is the same bargain as the rest of the
app. It's also the only thing here that talks to the internet: questions about
your own machine stay commands, and the query is all that's ever sent.

The cost of using a search page rather than a paid API is that DuckDuckGo can
decide you're a robot — several searches in quick succession will do it — and
answer with a picture puzzle instead of results. The app tells you that's what
happened and that it clears on its own in a few minutes, rather than reporting
it as "nothing found", which would send you off rewriting a question that was
fine.

## How it works (short version)

- You type a request
- It's sent to a local model (via llama.cpp) with instructions to translate it
  into one real command for *this* machine's shell, and to say whether that
  command is safe or risky — or, when the answer isn't on this machine at all,
  to give a web search query instead of a command
- The reply is constrained to a JSON schema while the model generates it —
  llama.cpp compiles the schema to a grammar and masks out any token that
  would break the shape, so code fences, preambles and truncated objects
  aren't possible rather than merely rare. Servers that don't support this
  fall back to being asked nicely and having the answer salvaged
- Safe commands run immediately
- Risky commands (delete, overwrite, install, system settings, etc.) show
  you the exact command and ask for confirmation before running — and let
  you edit it first, because the model getting one path segment wrong
  shouldn't mean retyping the whole request

When you edit a command before running it, the pair — what you asked for, what
the model wrote, what you replaced it with — is appended to
`corrections.jsonl` in the config folder. It stays on your machine; nothing
reads it yet, and nothing sends it anywhere. It exists so there is real data
about where the model goes wrong on *your* computer by the time something can
use it.

Anything that looks like a credential is replaced with `[redacted]` first —
values after `--password`, `-Token`, `--api-key` and friends, `password=` in a
connection string, `Bearer` tokens, and long opaque hex or base64 runs. That is
best-effort pattern matching, not a guarantee; file paths are deliberately left
alone, because a record that scrubbed them would teach nothing.

Turn it off with `AI_SHELL_CORRECTIONS=0`, or `"corrections": false` in
`settings.json`.

## Project layout

```
ai_shell/           core logic, no UI code — LLM calls, command execution, session state
ai_shell/config.py  settings: environment, then settings.json, then measured defaults
ai_shell/corrections.py  commands you edited before running, for later use as training/eval data
ai_shell/models.py  the model list, and which one this machine should run
ai_shell/hardware.py how much RAM and GPU memory there is
ai_shell/runtime.py finds llama-server, and installs one when there isn't one
ai_shell/updater.py notices a newer release of the app, and installs it on request
ai_shell/fetch.py   downloading and unpacking, shared by those two
ai_shell/server.py  starts, waits for and stops llama-server
ai_shell/web.py     web search, for questions this machine can't answer
ai_shell/platforms/ everything that differs between Windows, macOS and Linux
ai_shell_cli/       console REPL, built on ai_shell
ai_shell_gui/       pywebview desktop window, built on ai_shell
ai_shell_gui/frontend/  the React front end (build output in frontend/dist is what the window loads)
packaging/          how the desktop app is built into something downloadable
.github/workflows/  build.yml — builds every push, releases when there's one to cut
tests/              unittest suite; tests/test_live.py is the part that needs the internet
pyproject.toml      the pip package (distribution name nl-shell; version read from ai_shell/__init__.py)
release-please-config.json  what the commit messages are allowed to mean
run_cli.py          `python run_cli.py`
run_gui.py          `python run_gui.py`
```

Both interfaces are thin wrappers around `ai_shell.Session`, which owns
conversation history and command execution — so the CLI and GUI never
duplicate that logic, and a future interface (e.g. a web version) can reuse
the same core again.

Nothing outside `ai_shell/platforms/` asks which OS it's running on. A
platform object supplies the three things that actually differ: how to run a
command (which shell, how to quote, how to open a file), how to describe this
OS to the model (its shell's name, its path style, worked examples in it), and
how to find and launch installed applications — the Start Menu on Windows,
`/Applications` on macOS, `.desktop` entries on Linux. Supporting another OS
means adding a class there, not editing the core.

## Builds and releases

Every push to `main` and every pull request builds all four targets and runs
the tests on Windows, macOS and Linux (`.github/workflows/build.yml`). Nothing is
published — the builds land as artifacts on the run, downloadable from the
Actions tab for two weeks. The point is that `main` is always known to be
buildable, so releasing is never the moment you find out the macOS job has been
broken for a fortnight.

### Versioning

The version number is not written by hand. It comes from the commit messages,
via [Conventional Commits](https://www.conventionalcommits.org/) — the subject
line of each commit says what kind of change it is, and that decides the bump:

| Commit subject | Bump | Example |
|---|---|---|
| `fix: ...` | patch | `0.1.0` → `0.1.1` |
| `feat: ...` | minor | `0.1.0` → `0.2.0` |
| `feat!: ...`, or `BREAKING CHANGE:` in the body | minor while below 1.0 | `0.1.0` → `0.2.0` |
| `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `build:`, `perf:` | none | — |

A scope is optional: `fix(gui): panel reopens after it folds away`.

Breaking changes bump the *minor* rather than the major because this is a `0.x`
project, which is the standard way of saying the interface can still move.
Going to 1.0 is a deliberate act — put `Release-As: 1.0.0` in a commit body
when you mean it.

Pull request titles are checked against this format, because a squash merge
turns the title into the commit subject. The check failing doesn't block a
merge unless you add it to branch protection; it's there so a subject that
would silently count for nothing gets noticed. A commit that doesn't parse
isn't rejected — it just contributes no bump and no changelog line.

### Releasing

There's nothing to tag. [release-please](https://github.com/googleapis/release-please)
watches `main` and keeps a pull request open — *"chore(main): release 0.2.0"* —
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

The app lands in `dist/` — `dist/AI Shell/AI Shell.exe` on Windows,
`dist/AI Shell.app` on macOS, `dist/ai-shell/ai-shell` on Linux. Building the
front end first is not optional: the spec copies `ai_shell_gui/frontend/dist`,
it doesn't produce it. (It won't silently ship an empty window — the app checks
and says what's missing — but it also won't build one that works.)

The pip package is the same front-end-first story, `python -m build` instead of
PyInstaller:

```
npm --prefix ai_shell_gui/frontend install && npm --prefix ai_shell_gui/frontend run build
pip install build && python -m build
```

Two things are deliberately *not* in the bundle. The inference engine and the
model stay out, because `ai_shell/runtime.py` already fetches them into the
user's config folder on first run — so the download is ~40MB instead of several
gigabytes, and updating the app doesn't re-download the weights. The build is
also `--onedir` rather than `--onefile`: a onefile executable unpacks itself to
a temp folder on every launch, which costs seconds and looks like malware to a
heuristic scanner, and an app whose job is running shell commands starts that
argument at a disadvantage. Windows users still download one file —
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
| Windows installer (`unins000.exe` beside the exe) | runs the new setup silently — the `AppId` makes it an upgrade, not a second copy |
| Windows portable zip | the folder is swapped for the new one |
| macOS `.app` | the bundle is swapped |
| Linux tarball | the folder is swapped |
| pip | `pip install --upgrade` of the downloaded wheel |
| a checkout of this repository | never — that's what `git pull` is for |

Every one of those replaces files the running process has open, which Windows
forbids outright. So the app doesn't do it: it writes a small `.cmd` or `.sh`
script, starts it detached and quits, and the script waits for the process to
disappear before touching anything. The old copy is moved aside *before* the
new one lands, and put back if the new one won't move in — a failed update
leaves a working app rather than half of two.

Untouched by all of this: `%APPDATA%\ai-shell` (or `~/.config/ai-shell`), where
the model weights and llama.cpp live. That's why an update is tens of megabytes
and not several gigabytes.

Two ways to turn it off — `"auto_update": false` in `settings.json`, or
`AI_SHELL_AUTO_UPDATE=0` — after which nothing is checked and nothing is
downloaded. The releases page is checked at most once every six hours, so
launching the app five times in an afternoon is one request. Draft releases are
invisible to it: GitHub's "latest" is the newest *published* release, so
pressing publish is what actually ships a version to people.

## Tests

```
python -m unittest discover -s tests
```

Standard library `unittest`, no test framework — the requirements file is two
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
CAPTCHA, they skip rather than fail — an outage somewhere else shouldn't read
as a broken build.

Nearly every case is a bug that actually happened, and says so in a comment:
Wikipedia locking the reader out via `robots.txt`, `python.org` sending gzip
unasked and becoming mojibake, a weather page whose text is labels with the
numbers stripped out, the model citing five sources at once or none, citing
pages that don't contain the figure it quoted, and inventing a release date
out of two real ones.

## Known limitations (this is v0, not production)

- Only handles single commands — nothing that needs multi-step planning yet
- No persistent memory across sessions (each run starts fresh)
- Command safety classification is done by the model's judgment, not a
  hardcoded rule list — good enough to start, not bulletproof. Don't point
  this at anything you can't afford to lose, and read the command before
  confirming risky actions. Editing one doesn't get it re-classified: it was
  called risky once and it stays risky, which is the safe direction to be
  wrong in.
- No sandboxing — it runs with your full user permissions, same as opening
  a terminal yourself
- Windows is the best-tested platform, simply because that's where it was
  built. The macOS and Linux paths are written but have had far less real
  use, and small models are also noticeably better at PowerShell than at
  writing careful `find` invocations.
- On Linux, opening a file is fire-and-forget (`xdg-open` is backgrounded so
  the app doesn't block the shell), so a file with no handler registered
  fails silently rather than telling you why
- The packaged builds have no icon and no code signature. The icon is missing
  art, not missing code — drop `app.ico` and `app.icns` into `packaging/icons/`
  and the next build picks them up. The signature costs money: a Windows
  certificate is a few hundred a year, and macOS notarization needs a paid
  Apple developer account, so until then both OSes warn about the download
  (see [Download a build](#download-a-build)).
- The macOS and Linux builds are produced by CI but have not been run by
  anyone. Windows is the one that's been launched and used.
- The window says what it's waiting for while the model loads, but the
  first-run *model* download has no percentage behind it — only a line saying
  a download is happening. (The engine install does show one.) llama.cpp
  reports the real figure to `llama-server.log`, which is where it stays for
  now.
- The model is chosen for you and can be overridden by environment variable
  or by editing `settings.json`, but the GUI's settings screen can't change
  it yet.
- Model sizing is based on total RAM and GPU memory, not what's free right
  now. A machine already running something large may pick a model that then
  has to compete with it.
- A web answer can still attach a real date to the wrong thing — quoting a
  release date that belongs to a different release, say. The check catches a
  date that appears nowhere in the sources, which is a different mistake.
  Verifying that a date belongs to the subject beside it was tried and
  measured: it got six of eight test answers wrong, and rejected four correct
  answers to catch one bad one, so it isn't in. Read the cited page when a
  specific figure matters.
- Pages built entirely by JavaScript can't be read — the fetched HTML has no
  article in it. They're detected and fall back to the search snippet rather
  than feeding the model a page of empty labels, but the answer is that much
  thinner. News and price sites are the common cases.

## Natural next steps, if you want to keep building

- Put a real progress bar behind the model download — llama.cpp knows the
  percentage, the window currently only knows that a download is happening
- Let the GUI's settings screen pick the model, listing what this machine can
  actually run
- Draw an icon, and sign the builds, so the download stops being something the
  OS warns about
- Add a config file for "always confirm" vs "trust more" modes
- Add logging of every command run, so you have an audit trail
- Teach it multi-step plans, so "back up my photos and then clear the folder"
  becomes two confirmed commands instead of one refused request
