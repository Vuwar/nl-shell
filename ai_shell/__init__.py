# The one place the version lives. pyproject.toml reads it from here (as a
# literal, without importing this module), and the packaged builds are named
# after it.
#
# Don't edit it by hand. release-please owns this line — the trailing comment is
# the marker it looks for — and works the number out from the commit messages
# since the last release. See "Versioning and releases" in the README.
__version__ = "0.3.0"  # x-release-please-version

from ai_shell.session import Session

__all__ = ["Session", "__version__"]
