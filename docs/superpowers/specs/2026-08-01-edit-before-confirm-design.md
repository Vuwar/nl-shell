# Edit before confirm

Design for §4.2 of `docs/future-development.md`: let the user fix a translated
command instead of retyping the request and hoping for a better roll.

## Why this one first

The model gets most of a command right and one path segment wrong. Today that
costs a full re-translation, and re-translation is not deterministic — the
second attempt is a fresh guess, not a correction. Editing turns the most
common failure into a two-second fix.

The second reason is the one that decides the ordering. An edit is a labelled
example — *this request, on this machine, should have produced this command* —
and nothing else in the app produces one. §1.3 (learn from corrections) and
§7.1 (the eval set) both need that data, and every day this isn't shipped, the
examples are generated and discarded.

## What is already true, and what isn't

`docs/future-development.md` opens §4.2 with "The command is shown; let the user
fix it." The first half is not true of this codebase:

- `ai_shell_cli/app.py:105` prints `→ {explanation}` and nothing else.
- `ai_shell_gui/frontend/src/App.jsx:1224` adds an `explanation` entry; the
  confirm row at `:706` reads "Run this? It can't easily be undone." with no
  command anywhere on screen.
- `explanation` is specified in `ai_shell/llm.py:79` as "one short sentence
  describing what this does" — deliberately prose, not the command.

`README.md:327` already claims risky commands "show you the exact command and
ask for confirmation before running". That claim is currently false. This work
makes it true, which is why the README correction belongs in the same change
rather than in a separate fix.

So the feature is two things: show the command, then let it be edited.

## Scope

**Risky commands only.** The command becomes visible and editable in the
confirmation step. Safe commands keep running immediately and unshown — the
panel's pitch ("no need to know the command", `App.jsx:221`) is untouched, and
adding a confirmation to safe commands would contradict README's "safe commands
run immediately" for no gain here.

## Risk classification of an edited command

**The edited command stays risky. It is not re-classified.**

It only reached an edit affordance by being classified risky in the first
place, and an edit must never be able to downgrade that. This follows §3.1's
asymmetry — a rule that can only add friction cannot break anything by being
wrong — and avoids the §1.5 trap where a model "repairs" a command into a
broader one and blesses its own work.

There is also no second confirmation after an edit. The user typed the final
text themselves, which is stronger consent than clicking Run on a string
someone else wrote, and §3.1's catch is explicit that confirming too much is
how confirmations stop being read.

## Architecture

```
translate() → {command, risk: "risky", explanation}
   ↓ front end shows explanation AND the command
   ↓ user chooses: run / edit / cancel
   ↓ edit → line prefilled with the command, user fixes it, Enter
run_last(command=edited)
   ↓ edited != suggested → corrections.record(...)
   ↓ resolve_listed_paths, then execute — unchanged from here down
```

### `Session.run_last(command=None)`

`None` preserves today's behaviour exactly, so `_run_borrowed`
(`session.py:401`) and every existing caller are untouched. A string replaces
the pending command.

**The edited command goes through `resolve_listed_paths` exactly as an
unedited one does.** One code path, no branch on origin.

This was initially specified the other way and reversed after reading
`ai_shell/listing.py`. The helper is narrower than its name suggests: it
replaces an argument only when it matches a listed name *in full*
(`listing.py:60`), only against the rows of the listing currently on screen,
skips parameters that take a name rather than a path (`:64`), and quotes what
it substitutes. It cannot alter a glob, a flag, or anything it does not exactly
match.

Skipping it would therefore not prevent surprises; it would cause them. A user
editing a command is copying a name they can *see in the listing on screen*, so
a hand-typed bare name is more likely to need resolution than the model's
output is. Without it, that name resolves against the process working
directory — and on a multi-folder listing `listing_parent` returns None, so
`_context_path` is never set from it (`session.py:430`) and the command runs
against the app's launch directory. On a command classified risky, that is the
worse failure.

Absolute paths, globs, and names absent from the listing are all left alone.

## The CLI

Python's `readline` is POSIX-only, and this project is deliberately short on
dependencies. Rather than reimplement line editing, each OS's own console
editor does the work, seeded with the command.

New platform method, `prefill_input(prompt, text)`, with the base class
returning `None` for "can't do that here" in the established style. The return
values have to stay distinguishable: `None` means the platform cannot prefill,
and any string — including an empty one — is what the user actually entered.

- **POSIX** — `readline.set_startup_hook(lambda: readline.insert_text(text))`,
  stdlib, a few lines.
- **Windows** — `WriteConsoleInputW` via `ctypes` injects the command as
  keystrokes, then a plain `input()` shows it prefilled and the console's own
  editor handles arrows and backspace.
- **Base / `None`** — a type-over prompt: the command is printed and whatever
  is typed replaces it whole.

An empty line cancels in both paths, and the type-over prompt says so. The
alternative — empty meaning "keep the original" when there is nothing in the
buffer, but "I deleted it" when there is — makes the same keystroke run a risky
command on one platform and cancel it on another. Keeping the unedited command
is what `y` at the previous prompt is for.

The fallback is required, not decorative. `WriteConsoleInputW` needs a real
console handle, so redirected stdin — tests, CI, pipes — takes the type-over
path automatically. That is what keeps `tests/` runnable.

```
→ Deletes the three log files in Downloads.

  Remove-Item ~/Downloads/*.log

  This can't easily be undone. Run it? (y/N/e to edit):
```

## The GUI

The `confirm` entry carries the command. The confirm row shows it in a `<code>`
block above three buttons: **Run it**, **Edit**, **Cancel**.

Edit swaps the block for a prefilled `<textarea>` — a textarea rather than an
input because `command` may be a short script (`llm.py:21`). Enter runs,
Shift+Enter inserts a newline, Escape cancels. `Api.confirm(command=None)`
mirrors the `Session` signature.

## `ai_shell/corrections.py`

Append-only JSONL at `CONFIG_DIR/corrections.jsonl`, one record per edit:

```json
{"at": "2026-08-01T12:34:56Z", "request": "…", "suggested": "…",
 "corrected": "…", "model": "…", "os": "windows"}
```

`model` is recorded because §7.1 needs to know which model produced the command
that had to be fixed.

Both commands are stored **as written** — the user's text and the model's text,
neither passed through `resolve_listed_paths`. The model's output goes through
that helper too, so raw-versus-raw is the honest comparison.

Nothing reads this file yet. No retrieval, no prompt injection, no UI. Those
are §1.3 and §7.1.

**Written only when `corrected != suggested`.** A risky command confirmed
unedited is not a correction, and recording it would dilute the set with
examples that teach nothing.

### The off switch

Mirrors `AUTO_UPDATE` (`config.py:140`) exactly: `AI_SHELL_CORRECTIONS=0` in
the environment, or `"corrections": false` in `settings.json`. On by default —
unlike §1.4's shell-history mining, this records only commands typed into this
app during this session, and it never leaves the machine. Off by default would
collect nothing, which defeats the purpose.

### Redaction

Applied to both commands before writing, best-effort:

- values following `--password`, `-Password`, `--token`, `-Token`, `--secret`,
  `--api-key`, `-ApiKey` and similar
- `password=` in connection strings
- `Bearer <token>`
- bare hex or base64 runs of 20 characters or more

Each becomes `[redacted]`. The README says plainly that this is best-effort and
not a guarantee. The file is local-only, so the risk is bounded — but a claim
of completeness would be the thing people remember if it were ever wrong.

## Error handling

- Write failures are swallowed, in the style of `_write_settings`
  (`config.py:65`). A read-only config folder must never stop a command from
  running.
- An empty or whitespace-only edit cancels, on both the prefilled and the
  type-over path. It never becomes an empty command.
- `prefill_input` raising on an unusual console falls through to the type-over
  prompt rather than taking down the REPL.

## Testing

New `tests/test_corrections.py`:

- each redaction pattern, and a command containing none of them
- the off switch, in both the environment and settings forms
- nothing written when the command is unchanged
- append shape across several records
- an unwritable directory does not raise

CLI tests cover the type-over path only, since redirected stdin is what a test
run has. `prefill_input` returning `None` is therefore the tested branch, and
an empty line cancelling is asserted there.

Extended session tests:

- `run_last(command=…)` executes the edited command, not the pending one
- the correction is recorded, with the raw text on both sides
- an identical command records nothing
- `run_last()` with no argument is byte-for-byte today's behaviour, and
  `_run_borrowed` is unaffected

Every existing test passes unchanged.

## Documentation

- `README.md:327` becomes true, and gains the edit affordance.
- The corrections file, its location, its contents, its off switch and the
  best-effort nature of redaction are documented.

## Out of scope

Reading the corrections file (§1.3), an eval harness over it (§7.1), a
`/corrections` inspect-and-clear UI, showing commands for safe requests, and
any re-classification machinery. This ships the edit and the write side of the
dataset, nothing more.
