"""The original console REPL: type plain English, confirm risky commands, see output printed."""

import sys

from ai_shell import Session, config, models, server, updater
from ai_shell.config import connection_error
from ai_shell.listing import format_listing
from ai_shell.platforms import current
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

    # Claimed through the session, so this and the after-a-slow-answer
    # explanation can't both be printed: same sentence, same card.
    startup_notice = session.claim_notice(server.fit_notice())
    if startup_notice:
        print(f"  {startup_notice} Type 'model' to switch.\n")

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
        # A bare word, matching `update`: this REPL has no command prefix, and
        # inventing one for a single feature would leave two conventions where
        # there is currently one.
        if user_input.lower() == "model" or user_input.lower().startswith("model "):
            _model_command(user_input[5:].strip())
            continue

        data = session.translate(user_input)
        command = data.get("command")
        risk = data.get("risk")
        explanation = data.get("explanation", "")

        if data.get("notice"):
            print(f"  ({data['notice']} Type 'model' to switch.)")

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

        # None means "run what the model wrote"; a string is the user's own
        # version, which the session records as a correction.
        edited = None
        if risk == "risky":
            print(f"\n  {command}\n")
            choice = input("  This can't easily be undone. Run it? (y/N/e to edit): ").strip().lower()
            if choice == "e":
                edited = _edit_command(command)
                if not edited:
                    print("  Skipped.")
                    continue
            elif choice != "y":
                print("  Skipped.")
                continue

        result = session.run_last(edited)
        if not result["ok"]:
            print(f"✕ {result['reason']}")
        elif result.get("listing") is not None:
            if result["path"]:
                print(result["path"])
            print(format_listing(result["listing"], result["kind"]))
        else:
            print(result["output"] if result["output"] else "✓ Done")


def _model_command(argument):
    """`model` lists what this machine can run; `model 3` switches to one.

    A bare word rather than a slash command, matching `update`. The tradeoff
    is the one `update` already makes: somebody whose actual request is the
    word "model" gets the list instead.
    """
    rows = models.catalog(
        config.HARDWARE.get("vram_gb"),
        config.HARDWARE.get("ram_gb"),
        config.HARDWARE.get("vram_shared", False),
        installed=config.installed_models(),
        current_id=config.MODEL,
    )

    if not argument:
        print()
        for number, row in enumerate(rows, start=1):
            if row["current"]:
                note = "in use"
            elif not row["fits"]:
                note = "too big for your card"
            elif row["installed"]:
                note = "downloaded"
            else:
                note = f"{row['weights_gb']}GB download"
            print(f"  {number}. {row['label']:<22} {note}")
        print(f"\n  Type 'model 2' to switch. Downloads are kept in {config.MODEL_DIR}.\n")
        return

    if not argument.isdigit() or not 1 <= int(argument) <= len(rows):
        print(f"  Pick a number from 1 to {len(rows)}.")
        return

    chosen = rows[int(argument) - 1]
    if chosen["current"]:
        print("  That's the one already running.")
        return
    if not chosen["fits"]:
        print(f"  {chosen['label']} is bigger than this machine can hold — it will be slow.")
    if not chosen["installed"]:
        print(f"  Downloading {chosen['label']} — {chosen['weights_gb']}GB, this takes a while.")

    result = server.switch_model(chosen["id"], on_status=lambda line: print(f"  {line}"))
    if not result["ok"]:
        print(f"  {result['reason']}")
        return
    print(f"  Now running {chosen['label']}.")


def _edit_command(command):
    """The command as the user wants it, or "" to cancel.

    Two ways in. Where the platform can seed the console's own line editor,
    the command is already on the line and the user fixes the part that's
    wrong. Where it can't — a redirected stdin, an unusual terminal — the
    command has just been printed above, and whatever is typed replaces it
    whole.

    An empty line cancels on both paths. The alternative, where empty means
    "keep it" when there is nothing in the buffer and "I deleted it" when
    there is, makes the same keystroke run a risky command on one platform and
    cancel it on another. Keeping the command unedited is what `y` is for.
    """
    edited = current.prefill_input("  ", command)
    if edited is None:
        print("  Type the corrected command, or leave it empty to cancel:")
        try:
            edited = input("  ")
        except (EOFError, KeyboardInterrupt):
            print()
            return ""
    return edited.strip()


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
