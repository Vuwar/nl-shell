"""ai_shell.updater - deciding what's newer, and what to do about it.

The parts worth pinning here are the ones with no second chance. A version
comparison that gets it backwards offers people a downgrade; a script that
moves the new app into place before moving the old one aside destroys a
working install; an extractor that trusts an archive's member names writes
wherever the archive says. None of those fail loudly at the time.

The download and the process-spawning aren't exercised - they're the network
and the OS - but everything that decides what those two are handed is.
"""

import os
import unittest
import zipfile
from unittest import mock

from ai_shell import fetch, updater
from tests.stubs import StubHTTP


class Versions(unittest.TestCase):
    def test_the_ordinary_forms(self):
        self.assertEqual(updater.parse_version("0.2.0"), (0, 2, 0, 1, ""))
        self.assertEqual(updater.parse_version("v0.2.0"), (0, 2, 0, 1, ""))
        self.assertEqual(updater.parse_version(" v1.10.3 "), (1, 10, 3, 1, ""))

    def test_junk_is_not_a_version(self):
        for text in ("", None, "latest", "0.2", "v", "nightly-2026-01-01"):
            with self.subTest(text=text):
                self.assertIsNone(updater.parse_version(text))

    def test_newer_is_newer(self):
        self.assertTrue(updater.is_newer("0.2.0", "0.1.0"))
        self.assertTrue(updater.is_newer("v0.1.1", "0.1.0"))
        self.assertTrue(updater.is_newer("0.10.0", "0.9.0"))  # not string order

    def test_same_or_older_is_not(self):
        self.assertFalse(updater.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(updater.is_newer("0.1.0", "0.2.0"))
        self.assertFalse(updater.is_newer("0.9.0", "0.10.0"))

    def test_a_prerelease_loses_to_its_own_release(self):
        # The one semver rule that a naive tuple comparison gets backwards, and
        # it matters: 0.2.0-rc1 must not be offered to somebody on 0.2.0.
        self.assertTrue(updater.is_newer("0.2.0", "0.2.0-rc1"))
        self.assertFalse(updater.is_newer("0.2.0-rc1", "0.2.0"))
        self.assertTrue(updater.is_newer("0.2.0-rc2", "0.2.0-rc1"))
        self.assertTrue(updater.is_newer("0.2.0-rc1", "0.1.9"))

    def test_an_unreadable_tag_is_never_newer(self):
        # This answer comes off the internet. "Couldn't read it" must not mean
        # "offer it anyway".
        self.assertFalse(updater.is_newer("garbage", "0.1.0"))
        self.assertFalse(updater.is_newer(None, "0.1.0"))


class Assets(unittest.TestCase):
    def test_each_channel_asks_for_its_own_build(self):
        self.assertEqual(
            updater.asset_suffix(updater.WINDOWS_INSTALLER), "-windows-x64-setup.exe"
        )
        self.assertEqual(updater.asset_suffix(updater.WINDOWS_PORTABLE), "-windows-x64.zip")
        self.assertEqual(updater.asset_suffix(updater.LINUX), "-linux-x64.tar.gz")
        self.assertEqual(updater.asset_suffix(updater.PIP), "-py3-none-any.whl")
        self.assertIsNone(updater.asset_suffix(updater.SOURCE))

    def test_the_installer_and_the_zip_are_told_apart(self):
        # Both end in "-windows-x64" plus an extension, and matching the wrong
        # one means running an installer that is actually a zip, or unpacking
        # an exe. The names really do come out of build.yml like this.
        names = [
            "AI-Shell-0.2.0-windows-x64-setup.exe",
            "AI-Shell-0.2.0-windows-x64.zip",
        ]
        portable = [n for n in names if n.endswith(updater.asset_suffix(updater.WINDOWS_PORTABLE))]
        installer = [n for n in names if n.endswith(updater.asset_suffix(updater.WINDOWS_INSTALLER))]
        self.assertEqual(portable, ["AI-Shell-0.2.0-windows-x64.zip"])
        self.assertEqual(installer, ["AI-Shell-0.2.0-windows-x64-setup.exe"])

    def test_the_version_is_read_back_out_of_a_file_name(self):
        # How an already-downloaded update is recognised on a later launch,
        # when GitHub isn't being asked. Both naming styles the release
        # produces: hyphens for the app, underscores for the wheel - and the
        # pre-release case, where the version itself contains the separator
        # that otherwise ends it.
        for name, suffix, want in [
            ("AI-Shell-0.2.0-windows-x64-setup.exe", "-windows-x64-setup.exe", "0.2.0"),
            ("AI-Shell-0.2.0-macos-arm64.zip", "-macos-arm64.zip", "0.2.0"),
            ("ai-shell-1.0.3-linux-x64.tar.gz", "-linux-x64.tar.gz", "1.0.3"),
            ("nl_shell-0.2.0-py3-none-any.whl", "-py3-none-any.whl", "0.2.0"),
            ("AI-Shell-0.2.0-rc1-windows-x64.zip", "-windows-x64.zip", "0.2.0-rc1"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(updater._version_from_asset(name, suffix), want)


class Checking(unittest.TestCase):
    """check() against a release page that isn't there."""

    def setUp(self):
        # Never let a test write the real settings file, and never let the
        # interval short-circuit the thing being tested.
        patches = [
            mock.patch.object(updater.config, "AUTO_UPDATE", True),
            mock.patch.object(updater.config, "LAST_UPDATE_CHECK", 0),
            mock.patch.object(updater.config, "VERSION", "0.1.0"),
            mock.patch.object(updater.config, "remember_update_check", lambda when: None),
            mock.patch.object(updater, "detect_channel", lambda: updater.WINDOWS_INSTALLER),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _release(self, tag, assets):
        return mock.patch.object(updater.fetch, "github_release", lambda url, **kw: (tag, assets))

    def test_a_newer_release_with_our_build(self):
        assets = {"AI-Shell-0.2.0-windows-x64-setup.exe": "https://example.invalid/setup.exe"}
        with self._release("v0.2.0", assets):
            update = updater.check(force=True)
        self.assertEqual(update["version"], "0.2.0")
        self.assertEqual(update["url"], "https://example.invalid/setup.exe")
        self.assertEqual(update["channel"], updater.WINDOWS_INSTALLER)

    def test_the_same_version_is_nothing_to_do(self):
        with self._release("v0.1.0", {"AI-Shell-0.1.0-windows-x64-setup.exe": "u"}):
            self.assertIsNone(updater.check(force=True))

    def test_a_release_missing_this_platforms_build(self):
        # A build that failed on one runner shouldn't put an error in front of
        # a user who can do nothing about it.
        with self._release("v0.2.0", {"ai-shell-0.2.0-linux-x64.tar.gz": "u"}):
            self.assertIsNone(updater.check(force=True))

    def test_a_checkout_never_updates_itself(self):
        with mock.patch.object(updater, "detect_channel", lambda: updater.SOURCE):
            with self._release("v9.9.9", {"AI-Shell-9.9.9-windows-x64-setup.exe": "u"}):
                self.assertIsNone(updater.check(force=True))

    def test_switched_off_means_nothing_is_asked(self):
        def explode(url, **kw):
            raise AssertionError("asked GitHub with auto-update off")

        with mock.patch.object(updater.config, "AUTO_UPDATE", False):
            with mock.patch.object(updater.fetch, "github_release", explode):
                self.assertIsNone(updater.check(force=True))

    def test_an_unreachable_release_page_is_an_UpdateError(self):
        def fail(url, **kw):
            raise fetch.FetchError("no network")

        with mock.patch.object(updater.fetch, "github_release", fail):
            with self.assertRaises(updater.UpdateError):
                updater.check(force=True)


class ApplyScripts(unittest.TestCase):
    """The script that replaces the app after this process exits.

    Read as text rather than run: what matters is the order of the moves and
    that the app is waited for, and both are visible in the script.
    """

    UPDATE = {
        "version": "0.2.0",
        "name": "AI-Shell-0.2.0-windows-x64.zip",
        "file": r"C:\Users\a b\AppData\Roaming\ai-shell\updates\AI-Shell-0.2.0-windows-x64.zip",
        "tree": r"C:\Users\a b\Programs\.ai-shell-update-0.2.0\AI Shell",
        "channel": updater.WINDOWS_PORTABLE,
    }
    ROOT = r"C:\Users\a b\Programs\AI Shell"

    def _windows(self, update):
        with mock.patch.object(updater, "install_root", lambda: self.ROOT):
            return updater._windows_script(update, [r"C:\Users\a b\Programs\AI Shell\AI Shell.exe"])

    def test_it_waits_for_this_process_to_go(self):
        script = self._windows(self.UPDATE)
        self.assertIn(f'"PID eq {os.getpid()}"', script)
        self.assertIn("goto wait", script)
        # timeout wants a console to read a keypress from and this script has
        # none, which is why the sleep is a ping.
        self.assertIn("ping -n 2", script)
        self.assertNotIn("timeout /t", script)

    def test_the_old_app_is_moved_aside_before_the_new_one_lands(self):
        # The other order deletes a working install and then finds out whether
        # the replacement was any good.
        script = self._windows(self.UPDATE)
        aside = script.index(f'move "{self.ROOT}" "{self.ROOT}.old"')
        lands = script.index(f'move "{self.UPDATE["tree"]}" "{self.ROOT}"')
        self.assertLess(aside, lands)
        # And if the new one won't move in, the old one goes back.
        self.assertIn(f'if errorlevel 1 move "{self.ROOT}.old" "{self.ROOT}"', script)

    def test_the_installer_channel_runs_setup_silently(self):
        update = dict(self.UPDATE, channel=updater.WINDOWS_INSTALLER)
        script = self._windows(update)
        self.assertIn("/SILENT", script)
        self.assertIn("/SUPPRESSMSGBOXES", script)
        # Nothing is moved by hand - Inno matches the AppId and upgrades.
        self.assertNotIn("move ", script)

    def test_the_pip_channel_installs_the_wheel_it_downloaded(self):
        update = dict(self.UPDATE, channel=updater.PIP, file="/tmp/nl_shell-0.2.0.whl")
        with mock.patch.object(updater, "install_root", lambda: None):
            script = updater._windows_script(update, [])
        # The argument pip is given has to be the wheel that was already
        # downloaded - installing by distribution name would go to an index and
        # could fetch something else entirely.
        self.assertIn('-m pip install --upgrade --no-input "/tmp/nl_shell-0.2.0.whl"', script)
        # Asserted against the install target rather than the whole script: the
        # script embeds sys.executable, so a plain "nl-shell" is not in it
        # fails for anyone whose interpreter lives under a path containing the
        # project's own name - a virtualenv in a checkout of this repository,
        # which is the ordinary way to work on it.
        self.assertNotIn('--no-input "nl-shell"', script)

    def test_posix_paths_with_spaces_survive_quoting(self):
        update = {
            "version": "0.2.0",
            "name": "AI-Shell-0.2.0-macos-arm64.zip",
            "file": "/Users/a b/Library/Application Support/ai-shell/updates/x.zip",
            "tree": "/Applications/.ai-shell-update-0.2.0/AI Shell.app",
            "channel": updater.MACOS,
        }
        with mock.patch.object(updater, "install_root", lambda: "/Applications/AI Shell.app"):
            script = updater._posix_script(update, ["open", "/Applications/AI Shell.app"])
        self.assertIn("mv '/Applications/AI Shell.app' '/Applications/AI Shell.app.old'", script)
        self.assertIn(f"kill -0 {os.getpid()}", script)
        self.assertIn("'open' '/Applications/AI Shell.app'", script)

    def test_no_relaunch_means_no_relaunch(self):
        # The console session's case: coming back as a window nobody asked for
        # would be worse than the user typing ai-shell again.
        with mock.patch.object(updater, "install_root", lambda: "/opt/ai-shell"):
            script = updater._posix_script(dict(self.UPDATE, channel=updater.LINUX), [])
        self.assertNotIn("&\n", script.replace("2>&1", ""))


class Staging(unittest.TestCase):
    """stage() - from a downloaded archive to a tree ready to be moved in.

    Run against a real zip and a real folder, because the things worth
    checking here are all about the disk: where the unpacked app lands, that a
    zip without an app in it is refused, and that abandoned downloads don't
    pile up.
    """

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.tmp.name

        self.downloads = os.path.join(base, "downloads")
        self.programs = os.path.join(base, "Programs")
        self.root = os.path.join(self.programs, "AI Shell")
        os.makedirs(self.downloads)
        os.makedirs(self.root)
        with open(os.path.join(self.root, "AI Shell.exe"), "w") as handle:
            handle.write("old")

        patches = [
            mock.patch.object(updater, "DOWNLOAD_DIR", self.downloads),
            mock.patch.object(updater, "install_root", lambda: self.root),
            mock.patch.object(updater.config, "VERSION", "0.1.0"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _archive(self, name, members):
        """A zip in a "downloaded" state, as if fetch.download had just run."""
        path = os.path.join(self.downloads, name)
        with zipfile.ZipFile(path, "w") as zf:
            for member, content in members.items():
                zf.writestr(member, content)
        return path

    def _update(self, name):
        return {
            "version": "0.2.0",
            "name": name,
            "url": None,  # already on disk
            "channel": updater.WINDOWS_PORTABLE,
            "notes_url": "",
        }

    def test_download_progress_still_counts_in_whole_percents(self):
        # fetch reports raw bytes five times a second now. What reaches the
        # updater's status dict, and from there the window, must still be a
        # percentage that changes at most a hundred times.
        import io

        name = "AI-Shell-0.2.0-windows-x64.zip"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("AI Shell/AI Shell.exe", "new" * 40000)
        body = buffer.getvalue()

        seen = []
        update = dict(self._update(name), url="https://example/app.zip")
        with mock.patch("urllib.request.urlopen", StubHTTP(body)):
            updater.stage(update, on_progress=seen.append)

        self.assertTrue(seen)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertTrue(all(isinstance(p, int) and 0 <= p <= 100 for p in seen))

    def test_the_new_app_is_unpacked_beside_the_one_it_replaces(self):
        # Beside it, so applying the update is a rename inside one directory
        # rather than a copy across a drive boundary that can fail halfway.
        name = "AI-Shell-0.2.0-windows-x64.zip"
        self._archive(name, {"AI Shell/AI Shell.exe": "new", "AI Shell/_internal/x": "y"})

        staged = updater.stage(self._update(name))

        self.assertEqual(os.path.dirname(os.path.dirname(staged["tree"])), self.programs)
        self.assertTrue(os.path.exists(os.path.join(staged["tree"], "AI Shell.exe")))
        # And the copy being replaced is still sitting there untouched.
        with open(os.path.join(self.root, "AI Shell.exe")) as handle:
            self.assertEqual(handle.read(), "old")

    def test_an_archive_without_an_app_in_it_is_refused(self):
        # Before anything is moved, which is the whole point: a corrupt
        # download found out about afterwards has already eaten the install.
        name = "AI-Shell-0.2.0-windows-x64.zip"
        self._archive(name, {"AI Shell/readme.txt": "no app here"})
        with self.assertRaises(updater.UpdateError):
            updater.stage(self._update(name))

    def test_a_download_that_was_never_installed_is_cleaned_up(self):
        # Closing the panel without clicking Restart is the normal case, so
        # without this every skipped release stays on the disk forever.
        stale = os.path.join(self.downloads, "AI-Shell-0.1.5-windows-x64.zip")
        with open(stale, "w") as handle:
            handle.write("last week's")

        name = "AI-Shell-0.2.0-windows-x64.zip"
        self._archive(name, {"AI Shell/AI Shell.exe": "new"})
        updater.stage(self._update(name))

        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(os.path.join(self.downloads, name)))

    def test_a_stale_unpacked_tree_is_cleaned_up_too(self):
        old_staging = os.path.join(self.programs, ".ai-shell-update-0.1.5")
        os.makedirs(old_staging)
        name = "AI-Shell-0.2.0-windows-x64.zip"
        self._archive(name, {"AI Shell/AI Shell.exe": "new"})

        updater.stage(self._update(name))

        self.assertFalse(os.path.exists(old_staging))

    def test_an_already_downloaded_update_is_found_without_asking_github(self):
        name = "AI-Shell-0.2.0-windows-x64.zip"
        self._archive(name, {"AI Shell/AI Shell.exe": "new"})
        found = updater._staged_update(updater.WINDOWS_PORTABLE)
        self.assertEqual(found["version"], "0.2.0")
        self.assertIsNone(found["url"])  # nothing left to download


class ArchiveSafety(unittest.TestCase):
    """fetch.extract, shared with ai_shell.runtime.

    An update archive is the one file this app unpacks over its own install
    folder, so an extractor that honours a member called "../../evil" is worth
    not having.
    """

    def test_a_member_pointing_outside_is_refused(self):
        for name in ("../evil.txt", "/etc/evil.txt", "ok/../../evil.txt"):
            with self.subTest(name=name):
                with self.assertRaises(fetch.FetchError):
                    fetch.check_members([name], os.path.join("some", "root"))

    def test_ordinary_members_are_fine(self):
        fetch.check_members(
            ["AI Shell/AI Shell.exe", "AI Shell/_internal/base_library.zip"],
            os.path.join("some", "root"),
        )

    def test_the_check_runs_before_anything_is_written(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bad.zip")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("good.txt", "fine")
                zf.writestr("../escaped.txt", "not fine")

            destination = os.path.join(tmp, "out")
            os.makedirs(destination)
            with self.assertRaises(fetch.FetchError):
                fetch.extract(archive, destination)
            # Not "the escape was blocked" - nothing was unpacked at all,
            # because the names are checked as a set before the first write.
            self.assertEqual(os.listdir(destination), [])
            self.assertFalse(os.path.exists(os.path.join(tmp, "escaped.txt")))


if __name__ == "__main__":
    unittest.main()
