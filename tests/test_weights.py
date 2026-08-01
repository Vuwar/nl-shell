"""ai_shell.weights — choosing the right file, and getting it onto disk.

Two things here have no second chance. Picking the wrong file downloads
several gigabytes of something that isn't what the user chose and fails at
load time; and a retry that appends to a file it shouldn't produces weights
that are subtly wrong rather than absent. Both are cheap to test and
expensive to discover.
"""

import hashlib
import os
import tempfile
import unittest
from unittest import mock

from ai_shell import fetch, weights
from tests.stubs import StubHTTP

# Real payload, trimmed to the Q6_K and Q4_K_M entries. The repository
# publishes BOTH packagings of the same weights, which is the case an
# earlier draft of this treated as an error.
SIBLINGS = [
    {"rfilename": "README.md"},
    {
        "rfilename": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        "size": 4683073536,
        "lfs": {"sha256": "509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c",
                "size": 4683073536},
    },
    {
        "rfilename": "qwen2.5-coder-7b-instruct-q6_k-00001-of-00002.gguf",
        "size": 3950642496,
        "lfs": {"sha256": "6b99ee26f4b1f887b25dbb45491ec158391ba7ba73dbc4c75ca9560d3da4493a",
                "size": 3950642496},
    },
    {
        "rfilename": "qwen2.5-coder-7b-instruct-q6_k-00002-of-00002.gguf",
        "size": 2303556416,
        "lfs": {"sha256": "5103917f06a316394b6766b69217c7af101dbb3c53f5a84a2a4c1747b53c5109",
                "size": 2303556416},
    },
    {
        "rfilename": "qwen2.5-coder-7b-instruct-q6_k.gguf",
        "size": 6254198784,
        "lfs": {"sha256": "46291ddea1bfb608fe63d9a1907eea6918bda87a7626593edc4bf97c5fd73f9d",
                "size": 6254198784},
    },
]

REVISION = "13fb94bfda8c8cf22497dc57b78f391a9acb426a"
REPO = "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
REF = f"{REPO}:Q6_K"


def api(siblings=None, sha=REVISION):
    """A stand-in for fetch.json_document returning this repo's listing."""
    return mock.Mock(
        return_value={"sha": sha, "siblings": SIBLINGS if siblings is None else siblings}
    )


def say(_message):
    """A status sink for tests that don't assert on the lines."""


class Resolve(unittest.TestCase):
    def test_the_unsplit_file_wins_when_both_are_published(self):
        with mock.patch.object(weights.fetch, "json_document", api()):
            revision, files = weights.resolve(REF)
        self.assertEqual(revision, REVISION)
        self.assertEqual([f.name for f in files], ["qwen2.5-coder-7b-instruct-q6_k.gguf"])
        self.assertEqual(files[0].size, 6254198784)
        self.assertEqual(
            files[0].sha256,
            "46291ddea1bfb608fe63d9a1907eea6918bda87a7626593edc4bf97c5fd73f9d",
        )

    def test_shards_are_used_when_nothing_else_is_published(self):
        only_shards = [s for s in SIBLINGS if "-of-" in s["rfilename"]]
        with mock.patch.object(weights.fetch, "json_document", api(only_shards)):
            _, files = weights.resolve(REF)
        self.assertEqual(
            [f.name for f in files],
            ["qwen2.5-coder-7b-instruct-q6_k-00001-of-00002.gguf",
             "qwen2.5-coder-7b-instruct-q6_k-00002-of-00002.gguf"],
        )

    def test_the_url_pins_the_revision(self):
        with mock.patch.object(weights.fetch, "json_document", api()):
            _, files = weights.resolve(REF)
        self.assertEqual(
            files[0].url,
            f"https://huggingface.co/{REPO}/resolve/{REVISION}/"
            "qwen2.5-coder-7b-instruct-q6_k.gguf",
        )

    def test_a_quantisation_is_not_matched_by_a_longer_one(self):
        # q6_k must not be answered by q6_k_l, nor q4_k by q4_k_m. The names
        # differ only by a suffix, so a substring test cannot tell them apart
        # and would hand back several gigabytes of the wrong quantisation.
        only_longer = [
            {"rfilename": "model-q6_k_l.gguf", "size": 1,
             "lfs": {"sha256": "a" * 64, "size": 1}},
        ]
        with mock.patch.object(weights.fetch, "json_document", api(only_longer)):
            with self.assertRaises(weights.WeightsError):
                weights.resolve(REF)

        # The same in the real listing: it has q4_k_m and no q4_k.
        with mock.patch.object(weights.fetch, "json_document", api()):
            with self.assertRaises(weights.WeightsError):
                weights.resolve(f"{REPO}:Q4_K")

    def test_nothing_matching_names_what_it_looked_for(self):
        with mock.patch.object(weights.fetch, "json_document", api()):
            with self.assertRaises(weights.WeightsError) as caught:
                weights.resolve(f"{REPO}:Q2_K")
        message = str(caught.exception)
        self.assertIn(REPO, message)
        self.assertIn("Q2_K", message)

    def test_a_file_without_a_checksum_is_refused(self):
        listing = [{"rfilename": "model-q6_k.gguf", "size": 10}]
        with mock.patch.object(weights.fetch, "json_document", api(listing)):
            with self.assertRaises(weights.WeightsError):
                weights.resolve(REF)

    def test_a_reference_that_isnt_repo_and_quant_is_refused(self):
        for bad in ("", "Qwen/Repo", "Qwen/Repo:", ":Q6_K", "noslash:Q6_K"):
            with self.subTest(ref=bad):
                with self.assertRaises(weights.WeightsError):
                    weights.resolve(bad)

    def test_an_unreachable_api_says_so(self):
        dead = mock.Mock(side_effect=fetch.FetchError("no route", OSError()))
        with mock.patch.object(weights.fetch, "json_document", dead):
            with self.assertRaises(weights.WeightsError) as caught:
                weights.resolve(REF)
        self.assertIn(REPO, str(caught.exception))


PAYLOAD = bytes(range(256)) * 400  # 102,400 bytes
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def one_file(size=len(PAYLOAD), sha256=DIGEST):
    """An API listing with a single unsplit file of our test payload."""
    return [{"rfilename": "model-q6_k.gguf", "size": size,
             "lfs": {"sha256": sha256, "size": size}}]


class Ensure(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patch = mock.patch.object(weights.config, "MODEL_DIR", self.dir.name)
        patch.start()
        self.addCleanup(patch.stop)
        # Nothing here should ever wait; the backoff is asserted on directly.
        sleep = mock.patch.object(weights.time, "sleep")
        self.slept = sleep.start()
        self.addCleanup(sleep.stop)

    def path(self, name="model-q6_k.gguf"):
        return os.path.join(self.dir.name, name)

    def run_ensure(self, http, listing=None):
        with mock.patch.object(weights.fetch, "json_document", api(listing or one_file())):
            with mock.patch("urllib.request.urlopen", http):
                return weights.ensure(REF, "7B — test", say)

    def test_it_downloads_verifies_and_returns_the_path(self):
        http = StubHTTP(PAYLOAD)
        result = self.run_ensure(http)
        self.assertEqual(result, self.path())
        with open(result, "rb") as handle:
            self.assertEqual(handle.read(), PAYLOAD)
        self.assertFalse(os.path.exists(self.path() + ".partial"))

    def test_a_file_already_there_is_not_fetched_again(self):
        with open(self.path(), "wb") as handle:
            handle.write(PAYLOAD)
        http = StubHTTP(PAYLOAD)
        self.run_ensure(http)
        self.assertEqual(http.requests, [])

    def test_a_dropped_connection_backs_off_resumes_and_succeeds(self):
        http = StubHTTP(PAYLOAD, fail_after=40000, failures=2)
        result = self.run_ensure(http)
        with open(result, "rb") as handle:
            self.assertEqual(handle.read(), PAYLOAD)
        self.assertEqual(len(http.requests), 3)
        # Second and third attempts continue rather than start over.
        self.assertIsNone(http.requests[0].headers.get("Range"))
        self.assertEqual(http.requests[1].headers.get("Range"), "bytes=40000-")
        self.assertEqual([c.args[0] for c in self.slept.call_args_list],
                         list(weights.BACKOFF[:2]))

    def test_running_out_of_attempts_says_what_was_kept(self):
        # A connection that dies before delivering anything new, every time —
        # so the attempts are genuinely exhausted rather than inching to the
        # end. What arrived earlier has to survive that.
        with open(self.path() + ".partial", "wb") as handle:
            handle.write(PAYLOAD[:40000])
        http = StubHTTP(PAYLOAD, fail_after=0, failures=99)
        with self.assertRaises(weights.WeightsError) as caught:
            self.run_ensure(http)
        message = str(caught.exception)
        self.assertIn(self.dir.name, message)
        self.assertIn("again", message)
        self.assertEqual(len(http.requests), weights.ATTEMPTS)
        self.assertEqual(os.path.getsize(self.path() + ".partial"), 40000)

    def test_a_404_is_not_retried(self):
        http = StubHTTP(PAYLOAD, status=404)
        with self.assertRaises(weights.WeightsError):
            self.run_ensure(http)
        self.assertEqual(len(http.requests), 1)
        self.assertEqual(self.slept.call_count, 0)

    def test_a_bad_checksum_is_re_fetched_once_and_then_refused(self):
        http = StubHTTP(PAYLOAD)
        with self.assertRaises(weights.WeightsError) as caught:
            self.run_ensure(http, one_file(sha256="0" * 64))
        self.assertIn("checksum", str(caught.exception))
        self.assertEqual(len(http.requests), 2)     # one clean retry, no more
        self.assertFalse(os.path.exists(self.path() + ".partial"))
        self.assertFalse(os.path.exists(self.path()))

    def test_too_little_free_space_fails_before_any_request(self):
        http = StubHTTP(PAYLOAD)
        usage = mock.Mock(return_value=mock.Mock(free=1000))
        with mock.patch.object(weights.shutil, "disk_usage", usage):
            with self.assertRaises(weights.WeightsError) as caught:
                self.run_ensure(http)
        self.assertIn("free", str(caught.exception))
        self.assertEqual(http.requests, [])

    def test_progress_names_the_model_and_reaches_a_hundred(self):
        lines = []
        http = StubHTTP(PAYLOAD)
        with mock.patch.object(weights.fetch, "json_document", api(one_file())):
            with mock.patch("urllib.request.urlopen", http):
                weights.ensure(REF, "7B — test", lines.append)
        self.assertTrue(any("7B — test" in line for line in lines))
        self.assertTrue(any("100%" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
