# AI Shell (v0)

A tiny terminal where you type plain English and it runs real Windows
PowerShell commands for you.

## Setup

This runs fully locally via [Ollama](https://ollama.com) — no API key, no
cost, nothing leaves your machine.

1. Install Python 3.10+ (you probably already have it on Windows — check
   with `python --version` in cmd or PowerShell).

2. Install the one dependency:

   ```
   pip install openai
   ```

   (Ollama exposes an OpenAI-compatible API, so the `openai` package is
   used as the client — no OpenAI account or key needed.)

3. Install [Ollama](https://ollama.com/download) and pull the model:

   ```
   ollama pull qwen2.5-coder:7b
   ```

   `qwen2.5-coder:7b` was picked to fit comfortably in 6GB of VRAM while
   staying good at command generation and strict JSON output. If you have
   more VRAM (12GB+), `qwen2.5-coder:14b` will do better; on 6GB or less,
   stick with the 7b.

4. Run it (Ollama runs as a background service after install, so it should
   already be listening on `localhost:11434`):

   ```
   python ai_shell.py
   ```

## Try it

```
ai> list all files in my downloads folder
ai> create a folder called test-project on my desktop
ai> what's using the most disk space in this folder
ai> delete the file called old_notes.txt
```

Notice: the last one will pause and ask you to confirm before deleting,
because it's classified as risky. Read-only or reversible stuff just runs.

## How it works (short version)

- You type a request
- It's sent to a local model (via Ollama) with instructions to translate it
  into one real PowerShell command, and to say whether that command is safe
  or risky
- Safe commands run immediately
- Risky commands (delete, overwrite, install, registry changes, etc.) show
  you the exact command and ask for a y/N before running

## Known limitations (this is v0, not production)

- Only handles single commands — nothing that needs multi-step planning yet
- No persistent memory across sessions (each run starts fresh)
- Command safety classification is done by the model's judgment, not a
  hardcoded rule list — good enough to start, not bulletproof. Don't point
  this at anything you can't afford to lose, and read the command before
  confirming risky actions.
- No sandboxing — it runs with your full user permissions, same as opening
  PowerShell yourself

## Natural next steps, if you want to keep building

- Add a config file for "always confirm" vs "trust more" modes
- Let it remember context across a session (e.g. "now zip that folder"
  referring to the folder from your last command)
- Add logging of every command run, so you have an audit trail
- Swap PowerShell execution for cross-platform (bash) once you're ready
  to try this on Linux
