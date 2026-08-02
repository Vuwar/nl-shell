"""ai_shell.fetch - the download half, where resuming is the whole point.

A model is several gigabytes over a connection that may not survive it. What
matters here is that an interrupted download is worth something afterwards,
and that a server which ignores the resume request cannot be allowed to
produce a file made of two overlapping copies.
"""

import os
import tempfile
import unittest
from unittest import mock

from ai_shell import fetch
from tests.stubs import StubHTTP

BODY = bytes(range(256)) * 400  # 102,400 bytes, and every byte checkable


class Download(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "payload.bin")

    def test_a_plain_download_writes_the_body(self):
        http = StubHTTP(BODY)
        with mock.patch("urllib.request.urlopen", http):
            fetch.download("https://example/x", self.path)
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), BODY)
        self.assertIsNone(http.requests[0].headers.get("Range"))

    def test_resume_asks_for_the_rest_and_appends(self):
        with open(self.path, "wb") as handle:
            handle.write(BODY[:40000])
        http = StubHTTP(BODY)
        with mock.patch("urllib.request.urlopen", http):
            fetch.download("https://example/x", self.path, resume=True)
        self.assertEqual(http.requests[0].headers.get("Range"), "bytes=40000-")
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), BODY)

    def test_progress_counts_what_was_already_on_disk(self):
        with open(self.path, "wb") as handle:
            handle.write(BODY[:51200])  # exactly half
        seen = []
        http = StubHTTP(BODY)
        with mock.patch("urllib.request.urlopen", http):
            fetch.download(
                "https://example/x", self.path,
                lambda read, total: seen.append((read, total)),
                resume=True,
            )
        # A resumed download reports from where it restarted, not from zero.
        self.assertTrue(seen)
        self.assertGreaterEqual(seen[0][0], 51200)
        self.assertEqual(seen[-1], (len(BODY), len(BODY)))

    def test_progress_reports_the_end_even_when_the_throttle_would_not(self):
        # A body this small transfers well inside one throttle window, so the
        # only report it can produce is the closing one. A download that says
        # nothing at all leaves a progress bar frozen at zero forever.
        seen = []
        http = StubHTTP(BODY)
        with mock.patch("urllib.request.urlopen", http):
            fetch.download(
                "https://example/x", self.path,
                lambda read, total: seen.append((read, total)),
            )
        self.assertEqual(seen[-1], (len(BODY), len(BODY)))

    def test_progress_is_throttled_by_time_not_by_percentage(self):
        # Ten percent of this body is 10KB, which is 40 chunks. If the old
        # percentage step were still in charge there would be ten reports; on
        # a clock that never advances there is exactly one, at the end.
        seen = []
        http = StubHTTP(BODY)
        with mock.patch("urllib.request.urlopen", http):
            with mock.patch("time.monotonic", return_value=1000.0):
                fetch.download(
                    "https://example/x", self.path,
                    lambda read, total: seen.append((read, total)),
                )
        self.assertEqual(len(seen), 1)

    def test_a_server_ignoring_range_starts_over_instead_of_corrupting(self):
        with open(self.path, "wb") as handle:
            handle.write(BODY[:40000])
        http = StubHTTP(BODY, ranges=False)
        with mock.patch("urllib.request.urlopen", http):
            fetch.download("https://example/x", self.path, resume=True)
        with open(self.path, "rb") as handle:
            body = handle.read()
        self.assertEqual(body, BODY)          # not 40000 bytes longer
        self.assertEqual(len(body), len(BODY))

    def test_without_resume_an_existing_file_is_replaced(self):
        with open(self.path, "wb") as handle:
            handle.write(b"stale")
        http = StubHTTP(BODY)
        with mock.patch("urllib.request.urlopen", http):
            fetch.download("https://example/x", self.path)
        self.assertIsNone(http.requests[0].headers.get("Range"))
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), BODY)

    def test_a_dropped_connection_keeps_what_arrived(self):
        http = StubHTTP(BODY, fail_after=30000, failures=1)
        with mock.patch("urllib.request.urlopen", http):
            with self.assertRaises(fetch.FetchError) as caught:
                fetch.download("https://example/x", self.path, resume=True)
        self.assertIsInstance(caught.exception.cause, OSError)
        self.assertEqual(os.path.getsize(self.path), 30000)


class JsonDocument(unittest.TestCase):
    def test_it_parses_and_sends_a_user_agent(self):
        http = StubHTTP(b'{"sha": "abc", "siblings": []}')
        with mock.patch("urllib.request.urlopen", http):
            data = fetch.json_document("https://example/api")
        self.assertEqual(data["sha"], "abc")
        self.assertEqual(http.requests[0].headers.get("User-agent"), fetch.USER_AGENT)

    def test_a_dead_endpoint_is_a_FetchError_carrying_its_cause(self):
        http = StubHTTP(b"", status=503)
        with mock.patch("urllib.request.urlopen", http):
            with self.assertRaises(fetch.FetchError) as caught:
                fetch.json_document("https://example/api")
        self.assertEqual(caught.exception.cause.code, 503)


if __name__ == "__main__":
    unittest.main()
