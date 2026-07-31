"""Desktop window.

The window opens first and the model server starts behind it. Loading several
gigabytes of weights takes seconds, and spending them on an empty desktop made
the app feel slow to start when what was actually slow was the model: now the
panel is up in about a second, says what it's waiting for, and holds anything
typed in the meantime until the server can answer it.

A failed start isn't fatal here the way it is for the CLI: the window reports
the problem in its own error line, because a desktop app that vanishes with a
message on a console nobody is looking at has told the user nothing.
"""

from ai_shell_gui.app import main

if __name__ == "__main__":
    main()
