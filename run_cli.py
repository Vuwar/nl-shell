"""Console REPL. Starts the model server first, so the shell is usable the
moment the prompt appears rather than failing on the first request."""

import sys

from ai_shell import server
from cli.app import main

if __name__ == "__main__":
    try:
        server.ensure_running(on_status=print)
    except server.ServerError as error:
        print(error)
        sys.exit(1)
    main()
