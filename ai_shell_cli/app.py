"""The original console REPL: type plain English, confirm risky commands, see output printed."""

import sys

from ai_shell import Session, server, updater
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

    # Looks for a newer release and downloads it in the background; installing
    # it is the "update" command below. relaunch=[] because this is a console
    # session — coming back as a new window nobody asked for would be worse
    # than the user typing `ai-shell` again.
    updates = updater.Updater(relaunch=[])
    updates.start()
    announced = False

    print("AI Shell — type what you want in plain English. Ctrl+C to quit.\n")

    while True:
        # Between prompts, not on a timer: an asynchronous line arriving while
        # somebody is halfway through typing is the sort of thing that makes a
        # REPL feel broken.
        if not announced:
            waiting = updates.status()
            if waiting["state"] == "ready":
                announced = True
                print(f"  (version {waiting['version']} is downloaded — type 'update' to install it)\n")

        try:
            user_input = input("ai> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nbye")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break
        if user_input.lower() == "update":
            _install_update(updates)
            continue

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


def _install_update(updates):
    """The `update` command: hand over to the updater and leave.

    Leaving is the point — the files being replaced are the ones this process
    is running out of, so the script the updater starts is waiting for this
    interpreter to exit before it touches anything.
    """
    state = updates.status()
    if state["state"] != "ready":
        print(
            {
                "checking": "  Still checking for one.",
                "downloading": f"  Downloading it now — {state['message']}",
                "failed": f"  Couldn't fetch an update: {state['message']}",
            }.get(state["state"], "  You're on the latest version.")
        )
        return

    result = updates.install()
    if not result["ok"]:
        print(f"  {result['error']}")
        return
    print(f"  Installing {state['version']}. Run ai-shell again in a moment.")
    sys.exit(0)


if __name__ == "__main__":
    main()
