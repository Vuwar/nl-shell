# AI Shell

**Say what you want. It writes the command and runs it.**

A small terminal that takes plain English and turns it into real shell commands
- PowerShell on Windows, bash on macOS and Linux. It runs entirely on your own
machine: no account, no API key, no subscription, and nothing you type is sent
to anyone's model.

```
ai> what's using the most disk space in this folder
ai> create a folder called test-project on my desktop
ai> open eminem on youtube
ai> is python installed
ai> delete the file called old_notes.txt
```

The last one stops and asks first. The others just run.

Comes as a console REPL or a desktop window, whichever you prefer.

## Why it's built this way

**It's yours.** The model runs locally through
[llama.cpp](https://github.com/ggml-org/llama.cpp). Your files, your folder
names, the things you ask at 2am - none of it leaves the machine. There is no
usage meter and nothing to cancel.

**It asks before it hurts you.** Every command is classified before it runs.
Read-only and reversible things just happen. Anything that deletes, overwrites,
installs, or changes a system setting stops and shows you the exact command
first - and says what it does in plain English, because reading PowerShell
shouldn't be the price of using this:

```
  Remove-Item -Path 'C:\Users\me\Desktop\old_notes.txt'

    · Deletes C:\Users\me\Desktop\old_notes.txt

  This deletes files. Run it? (y/N/e to edit)
```

You can edit the command before it runs. That judgement isn't the model's
alone: a separate layer reads the finished command and can only ever make it
*stricter*, never more permissive.

**It admits what it doesn't know.** A local model has no internet and no idea
what year it is. Ask it something current and it searches the web and reads
the pages back to you, with sources. Ask it about your machine and it writes a
command that actually checks, instead of guessing.

**It doesn't waste your time on things it can just do.** Opening a website,
launching Task Manager, reaching the Bluetooth settings page - the answers to
those are facts, not judgement calls, so they're looked up in a table and
answered instantly, offline, the same way every time.

## Install

Three routes, none better than the others. All are tens of megabytes: the
inference engine and the model are fetched on first run, not shipped inside
the download.

### One command

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Vuwar/nl-shell/main/packaging/install.ps1 | iex
```

**macOS / Linux**:

```sh
curl -fsSL https://raw.githubusercontent.com/Vuwar/nl-shell/main/packaging/install.sh | sh
```

Puts it where the OS expects it - Start Menu on Windows, `/Applications` on
macOS, `~/.local` on Linux. Nothing needs an administrator. Both scripts are
short and readable ([install.ps1](packaging/install.ps1),
[install.sh](packaging/install.sh)), and reading a script before piping it into
a shell is a good habit.

### pip

Python 3.10+. Gets you the window, the console REPL, and `ai_shell` as an
importable package:

```sh
pip install "$(curl -fsSL https://api.github.com/repos/Vuwar/nl-shell/releases/latest \
  | grep -o 'https://[^"]*\.whl')"
```

Then `ai-shell` for the console, `ai-shell-gui` for the window.

### By hand

Everything is on the
[releases page](https://github.com/Vuwar/nl-shell/releases):

| | File | Notes |
|---|---|---|
| **Windows** | `AI-Shell-<version>-windows-x64-setup.exe` | Per-user, no administrator. `...-windows-x64.zip` is the same app as a plain folder. |
| **macOS** | `AI-Shell-<version>-macos-arm64.zip` (Apple Silicon) or `-macos-x64.zip` (Intel) | Unzip into `/Applications`. |
| **Linux** | `ai-shell-<version>-linux-x64.tar.gz` | Needs GTK and WebKit2GTK 4.1. Built on Ubuntu 22.04. |

**About the warning on first launch.** These builds aren't signed with a paid
certificate, so Windows SmartScreen says "Windows protected your PC" (*More
info* → *Run anyway*) and macOS Gatekeeper calls it an unidentified developer
(right-click → *Open* → *Open*). Neither means anything is wrong with the
download. It means nobody has paid a certificate authority about it.

## First run

It downloads llama.cpp and a model sized to your graphics card - a few
gigabytes, once, shown as it arrives. After that it keeps itself current:
new releases download in the background and offer a Restart button. Nothing is
replaced until you click it.

The model and the engine live in your config folder, not the app folder, so an
app update is tens of megabytes and leaves the weights alone.

## Being honest about it

This is v0. Worth knowing before you point it at anything you care about:

- **It runs as you.** No sandbox. Same permissions as opening a terminal
  yourself.
- **The safety layer is a good net, not a cage.** It catches the common
  destructive shapes. A command neither the model nor the rules recognise
  still runs without asking. Read what you confirm.
- **One command at a time.** No multi-step plans yet.
- **Windows is the best-tested platform**, because that's where it was built.
  macOS and Linux work but have seen far less real use.

The full list is in [Known limitations](docs/how-it-works.md#known-limitations-this-is-v0-not-production).

## Docs

- **[How it works](docs/how-it-works.md)** - which model you get and why, web
  lookups, the rules under the model, project layout, full limitations
- **[Working on it](docs/development.md)** - running from source, the tests,
  builds and releases
- **[What this could become](docs/future-development.md)** - a catalogue of
  ideas with their costs attached

## Licence

[MIT](LICENSE).
