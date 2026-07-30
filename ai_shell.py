"""
AI Shell — a terminal where you type natural language and it runs real commands.

Usage:
    python ai_shell.py

Requires:
    pip install openai
    Ollama running locally (https://ollama.com) with the model pulled:
        ollama pull qwen2.5-coder:7b

How it works:
    1. You type what you want in plain English
    2. A local model translates it into a real Windows command (PowerShell)
    3. The model also classifies it as SAFE or RISKY
    4. SAFE commands run immediately
    5. RISKY commands (delete, overwrite, format, etc.) ask you to confirm first
"""

import re
import subprocess
import sys
import json

try:
    from openai import OpenAI
except ImportError:
    print("Missing dependency. Run: pip install openai")
    sys.exit(1)


MODEL = "qwen2.5-coder:7b"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

SYSTEM_PROMPT = """You are a command translator for a Windows AI shell.
The user will describe what they want in plain English. Your job:

1. Translate their request into a single real PowerShell command (or a short
   PowerShell script if needed) that accomplishes it on Windows.
2. Classify the command as "safe" or "risky".
   - "risky" = anything that deletes, overwrites, moves files irreversibly,
     changes system settings, installs/uninstalls software, formats drives,
     touches registry, kills processes, or does anything hard to undo.
   - "safe" = read-only or easily reversible actions (listing files, reading
     content, checking status, creating new files/folders, printing info).
3. If the request is unclear, ambiguous, or not something that maps to a
   shell command (e.g. it's just a question), set "command" to null and put
   your answer/clarification in "explanation".

Respond with ONLY a single JSON object and nothing else: no markdown fences,
no preamble, no alternative options, no notes after the JSON, in this exact
shape:

{
  "command": "the powershell command, or null",
  "risk": "safe" or "risky" or null,
  "explanation": "one short sentence describing what this does, or your answer if command is null"
}

Example — risky request:
User: delete the file called old_notes.txt
{"command": "Remove-Item -Path 'old_notes.txt'", "risk": "risky", "explanation": "Permanently deletes old_notes.txt."}
"""


def ask_model(client, user_input, history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": user_input}]
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=500,
        temperature=0,
        messages=messages,
    )
    text = response.choices[0].message.content.strip()
    # strip accidental code fences just in case
    text = text.replace("```json", "").replace("```", "").strip()
    # local models sometimes add commentary after the JSON object; parse
    # just the first JSON value and ignore any trailing text
    try:
        data, _ = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return {"command": None, "risk": None, "explanation": f"(couldn't parse response: {text})"}
    return data


def run_command(command):
    print(f"\n> running: {command}\n")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=60
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(f"[stderr] {result.stderr}")
        return result
    except Exception as e:
        print(f"Error running command: {e}")
        return None


_LAUNCH_STOPWORDS = {"open", "launch", "start", "run", "please", "the", "a", "an", "app", "application"}


def resolve_app_launch(hint):
    """The model can only guess typical install paths, and guesses go stale
    (e.g. per-user LOCALAPPDATA installs vs. Program Files). Get-StartApps
    reads the same index the Start Menu uses, so it finds the real launch
    target regardless of where the app actually lives."""
    script = 'Get-StartApps | ForEach-Object { "$($_.Name)|$($_.AppID)" }'
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=15
        )
    except Exception:
        return None
    words = [w for w in re.findall(r"[a-z0-9]+", hint.lower()) if w not in _LAUNCH_STOPWORDS]
    hint_norm = "".join(words)
    if not hint_norm:
        return None
    for line in result.stdout.splitlines():
        name, _, app_id = line.partition("|")
        name_norm = re.sub(r"[^a-z0-9]", "", name.lower())
        if name_norm and (hint_norm in name_norm or name_norm in hint_norm):
            return app_id.strip()
    return None


def is_missing_file_error(command, result):
    return (
        result is not None
        and result.returncode != 0
        and "Start-Process" in command
        and "cannot find the file specified" in (result.stderr or "").lower()
    )


def main():
    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    try:
        client.models.list()
    except Exception:
        print(f"Can't reach Ollama at {OLLAMA_BASE_URL}. Is it running? Try: ollama serve")
        sys.exit(1)

    history = []

    print("AI Shell — type what you want in plain English. Ctrl+C to quit.\n")

    while True:
        try:
            user_input = input("ai> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nbye")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        data = ask_model(client, user_input, history)
        command = data.get("command")
        risk = data.get("risk")
        explanation = data.get("explanation", "")

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": json.dumps(data)})
        history = history[-20:]  # keep last 10 exchanges

        if not command:
            print(explanation)
            continue

        print(f"→ {explanation}")
        print(f"  command: {command}  [{risk}]")

        if risk == "risky":
            confirm = input("  This is risky. Run it? (y/N): ").strip().lower()
            if confirm != "y":
                print("  Skipped.")
                continue

        result = run_command(command)

        if is_missing_file_error(command, result):
            app_id = resolve_app_launch(user_input)
            if app_id:
                fallback_command = f"Start-Process 'shell:AppsFolder\\{app_id}'"
                print(f"  Path not found — retrying via Start Menu match: {fallback_command}")
                run_command(fallback_command)


if __name__ == "__main__":
    main()
