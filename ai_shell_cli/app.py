"""The original console REPL: type plain English, confirm risky commands, see output printed."""

import sys

from ai_shell import Session, server
from ai_shell.config import connection_error
from ai_shell.listing import format_listing
from ai_shell.web import format_sources


def run():
    """Start the model server, then the REPL — the whole `ai-shell` command.

    Separate from main() so that starting the server stays optional for anyone
    driving the REPL against one they're already running, and so run_cli.py and
    the installed console script are the same two steps rather than two
    copies of them.

    A failed start is fatal here, unlike in the desktop window: there's a
    console in front of the user either way, so printing why and stopping beats
    a prompt that rejects everything typed into it.
    """
    try:
        server.ensure_running(on_status=print)
    except server.ServerError as error:
        print(error)
        sys.exit(1)
    main()


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    session = Session()

    try:
        session.check_connection()
    except Exception:
        print(connection_error())
        sys.exit(1)

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

        data = session.translate(user_input)
        command = data.get("command")
        risk = data.get("risk")
        explanation = data.get("explanation", "")

        if not command and data.get("search"):
            print(f"→ {explanation}")
            result = session.run_last()
            if not result["ok"]:
                print(f"✕ {result['reason']}")
                continue
            if result["answer"]:
                print(result["answer"])
            print(format_sources(result["results"]))
            if result["caveat"]:
                print(f"  ({result['caveat']})")
            continue

        if not command:
            print(explanation)
            options = data.get("options")
            if isinstance(options, list):
                opts = [o.strip() for o in options if isinstance(o, str) and o.strip()][:4]
                if opts:
                    print("  " + " / ".join(opts) + " — type the one you want (or anything else)")
            continue

        print(f"→ {explanation}")

        if risk == "risky":
            confirm = input("  This can't easily be undone. Run it? (y/N): ").strip().lower()
            if confirm != "y":
                print("  Skipped.")
                continue

        result = session.run_last()
        if not result["ok"]:
            print(f"✕ {result['reason']}")
        elif result.get("listing") is not None:
            if result["path"]:
                print(result["path"])
            print(format_listing(result["listing"], result["kind"]))
        else:
            print(result["output"] if result["output"] else "✓ Done")


if __name__ == "__main__":
    main()
