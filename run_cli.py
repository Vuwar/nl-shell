"""Console REPL. Starts the model server first, so the shell is usable the
moment the prompt appears rather than failing on the first request.

The same two steps are behind the `ai-shell` command an install puts on your
PATH - see ai_shell_cli.app.run. This is the version that runs out of a
checkout, with nothing installed.
"""

from ai_shell_cli.app import run

if __name__ == "__main__":
    run()
