"""Everything that differs between Windows, macOS and Linux, in one place.

The rest of ai_shell is written against `current`, the platform object for the
machine it's running on, so no other module has to ask which OS this is. A
platform supplies three kinds of thing:

  * how to run something — which shell, how to quote, how to open a file
  * how to talk to the model about this OS — its shell's name, its path
    style, the conventions its commands are expected to follow
  * how to find and launch installed applications, which is the one part
    every OS does completely differently

Supporting another OS means adding a class here, not editing the core.
"""

import sys


def _select():
    if sys.platform == "win32":
        from ai_shell.platforms.windows import Windows

        return Windows()
    if sys.platform == "darwin":
        from ai_shell.platforms.macos import MacOS

        return MacOS()
    # Everything else that runs Python and has a POSIX shell: Linux, and the
    # BSDs close enough to it to be worth trying rather than refusing.
    from ai_shell.platforms.linux import Linux

    return Linux()


current = _select()

__all__ = ["current"]
