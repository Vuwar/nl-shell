#!/bin/sh
# Install the AI Shell desktop app on macOS or Linux.
#
#     curl -fsSL https://raw.githubusercontent.com/Vuwar/nl-shell/main/packaging/install.sh | sh
#
# It downloads the latest release build for this machine and puts it where the
# OS expects: /Applications on macOS, ~/.local on Linux. Nothing is compiled,
# nothing needs root, and nothing is written outside your home directory unless
# /Applications happens to be writable by you.
#
# Two knobs, both optional:
#
#     AI_SHELL_VERSION=0.1.0   install a specific release instead of the latest
#     AI_SHELL_PREFIX=~/apps   Linux only: where to put it
#
# What this does NOT download is the model — several gigabytes that the app
# fetches into its own config folder the first time you run it, so that
# reinstalling the app doesn't mean downloading the weights again.

set -eu

REPO="Vuwar/nl-shell"
API="https://api.github.com/repos/${REPO}/releases"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- what are we installing on? ---------------------------------------------
os="$(uname -s)"
arch="$(uname -m)"

case "$arch" in
  arm64 | aarch64) arch="arm64" ;;
  x86_64 | amd64) arch="x64" ;;
  *) die "no build is published for $arch. Install from source instead: https://github.com/${REPO}#or-run-from-source" ;;
esac

case "$os" in
  Darwin) suffix="macos-${arch}.zip" ;;
  Linux)
    [ "$arch" = "x64" ] || die "the Linux build is x86_64 only for now (this is $(uname -m))."
    suffix="linux-x64.tar.gz"
    ;;
  *) die "$os isn't one of the platforms this installs. Try running from source." ;;
esac

command -v curl >/dev/null 2>&1 || die "curl is needed and isn't installed."

# --- find the download ------------------------------------------------------
if [ -n "${AI_SHELL_VERSION:-}" ]; then
  release_url="${API}/tags/v${AI_SHELL_VERSION}"
else
  release_url="${API}/latest"
fi

say "Looking up the release..."
release="$(curl -fsSL "$release_url")" || die "couldn't reach the releases page for ${REPO}."

# Pulling the URL out with sed rather than jq, which isn't installed as often as
# this script would like to assume.
download="$(printf '%s' "$release" \
  | sed -n 's/.*"browser_download_url": *"\([^"]*'"$suffix"'\)".*/\1/p' \
  | head -n 1)"

[ -n "$download" ] || die "that release has no ${suffix} build. See https://github.com/${REPO}/releases"

tmp="$(mktemp -d)"
# Cleaned up however this exits, including a failed download partway through.
trap 'rm -rf "$tmp"' EXIT INT TERM

archive="${tmp}/$(basename "$download")"
say "Downloading $(basename "$download")..."
curl -fL --progress-bar -o "$archive" "$download" || die "the download failed."

# --- put it somewhere -------------------------------------------------------
if [ "$os" = "Darwin" ]; then
  # /Applications when it's writable without sudo, which it is on a normal
  # single-user Mac; ~/Applications otherwise, rather than asking for a password.
  if [ -w /Applications ]; then
    target="/Applications"
  else
    target="${HOME}/Applications"
    mkdir -p "$target"
    say "/Applications isn't writable, using ${target} instead."
  fi

  ditto -xk "$archive" "$tmp/unpacked" || die "couldn't unpack the download."
  app="$(find "$tmp/unpacked" -maxdepth 1 -name '*.app' | head -n 1)"
  [ -n "$app" ] || die "no .app inside the download."

  rm -rf "${target}/$(basename "$app")"
  mv "$app" "$target/"
  installed="${target}/$(basename "$app")"

  # The build is ad-hoc signed, not notarized, so Gatekeeper would otherwise
  # refuse it outright on first open. Clearing the quarantine flag here is the
  # same decision as right-clicking → Open, made once and in the open: you are
  # trusting a binary downloaded from that releases page.
  xattr -dr com.apple.quarantine "$installed" 2>/dev/null || true

  say ""
  say "Installed to ${installed}"
  say "Open it from Launchpad, or: open \"${installed}\""
else
  prefix="${AI_SHELL_PREFIX:-${XDG_DATA_HOME:-${HOME}/.local/share}}"
  target="${prefix}/ai-shell"
  bindir="${HOME}/.local/bin"

  mkdir -p "$prefix" "$bindir"
  rm -rf "$target"
  tar -xzf "$archive" -C "$prefix" || die "couldn't unpack the download."
  [ -x "${target}/ai-shell" ] || die "no ai-shell executable inside the download."

  ln -sf "${target}/ai-shell" "${bindir}/ai-shell-gui"

  say ""
  say "Installed to ${target}"
  say "Run it with: ai-shell-gui"

  case ":${PATH}:" in
    *":${bindir}:"*) ;;
    *) say ""
       say "${bindir} isn't on your PATH — add this to your shell profile:"
       say "    export PATH=\"\$PATH:${bindir}\"" ;;
  esac

  # Checked rather than installed: which package manager, and whether the user
  # wants this script touching it, are not this script's decisions to make.
  if ! ldconfig -p 2>/dev/null | grep -q webkit2gtk; then
    say ""
    say "Heads up: WebKit2GTK doesn't look installed, and the window needs it."
    say "    Debian/Ubuntu:  sudo apt install libwebkit2gtk-4.1-0 gir1.2-webkit2-4.1"
    say "    Fedora:         sudo dnf install webkit2gtk4.1"
  fi
fi

say ""
say "First run downloads the inference engine and a model (a few GB) into your"
say "config folder. The window opens straight away and says what it's waiting for."
