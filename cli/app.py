"""The original console REPL: type plain English, confirm risky commands, see output printed."""

import sys

from ai_shell import Session
from ai_shell.config import connection_error
from ai_shell.listing import format_listing
from ai_shell.web import format_sources


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
