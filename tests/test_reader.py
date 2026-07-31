"""ai_shell.web — turning a fetched page into text worth giving the model."""

import gzip
import random
import unittest
import zlib

from ai_shell import web

# Long enough to clear _MIN_TEXT, so these exercise extraction rather than the
# too-short rule.
BODY = "<p>" + ("Real article text about a real subject. " * 40) + "</p>"


class ExtractHtml(unittest.TestCase):
    def test_prefers_marked_up_article(self):
        page = f"""<html><head><title>The Page</title></head><body>
        <nav>Home About Contact Login Subscribe</nav>
        <header>Site Name</header>
        <script>var x = "should never appear";</script>
        <style>.a {{ color: red }}</style>
        <article>{BODY}</article>
        <footer>Copyright 2026 everyone</footer>
        </body></html>"""
        text = web._extract_html(page)
        self.assertIn("Real article text", text)
        for furniture in ("Contact", "should never appear", "color: red", "Copyright"):
            self.assertNotIn(furniture, text)

    def test_falls_back_to_body_without_article(self):
        text = web._extract_html(f"<html><body><nav>Menu Items</nav><div>{BODY}</div></body></html>")
        self.assertIn("Real article text", text)
        self.assertNotIn("Menu", text)

    def test_thin_article_does_not_starve_extraction(self):
        # A page that marks up two words and puts the story in a plain div.
        text = web._extract_html(f"<html><body><article>Hi</article><div>{BODY}</div></body></html>")
        self.assertIn("Real article text", text)

    def test_block_tags_keep_words_apart(self):
        self.assertIn("one", web._extract_html("<p>one</p><p>two</p>").split())

    def test_malformed_html_is_survivable(self):
        # An unclosed <nav> would otherwise swallow the rest of the document.
        self.assertIsInstance(web._extract_html("<nav><div>" + BODY), str)

    def test_void_tags_do_not_open_a_subtree(self):
        # <br> and <img> never close; counted as openers they'd leave the
        # depth counters stuck and drop everything after them.
        self.assertIn("Real article text", web._extract_html(f"<article><br><img src=x>{BODY}"))

    def test_entities_are_decoded(self):
        self.assertIn("Ben & Jerry's", web._extract_html("<article><p>Ben &amp; Jerry&#39;s</p>" + BODY))


class ReadableUrl(unittest.TestCase):
    def test_rejects_addresses_that_are_not_the_public_web(self):
        # A search result is a URL somebody else chose. Following one to
        # 127.0.0.1 would point the fetcher at whatever is running locally,
        # the model server included.
        for url in ("http://localhost:8080/x", "http://127.0.0.1:11434/api",
                    "http://192.168.1.5/", "http://10.0.0.1/", "http://172.16.0.1/",
                    "http://user@127.0.0.1/"):
            with self.subTest(url=url):
                self.assertFalse(web.readable_url(url))

    def test_allows_public_addresses(self):
        # 172.32 is outside the private 172.16-172.31 range.
        for url in ("https://en.wikipedia.org/wiki/Iceland", "http://172.32.0.1/",
                    "https://example.com/page?f=a.pdf"):
            with self.subTest(url=url):
                self.assertTrue(web.readable_url(url))

    def test_rejects_binaries_and_other_schemes(self):
        for url in ("https://example.com/a.pdf", "https://example.com/a.JPG",
                    "ftp://example.com/x", None):
            with self.subTest(url=url):
                self.assertFalse(web.readable_url(url))


class Decompression(unittest.TestCase):
    """python.org sends Content-Encoding: gzip whether or not it was asked
    for. Decoded as text, those bytes became thousands of characters of
    mojibake that passed every length check and went to the model as the
    article."""

    def setUp(self):
        self.body = BODY.encode()

    def test_gzip(self):
        self.assertEqual(web._decompress(gzip.compress(self.body), "gzip"), self.body)

    def test_gzip_aliases_and_case(self):
        packed = gzip.compress(self.body)
        self.assertEqual(web._decompress(packed, "x-gzip"), self.body)
        self.assertEqual(web._decompress(packed, "GZIP"), self.body)

    def test_deflate(self):
        self.assertEqual(web._decompress(zlib.compress(self.body), "deflate"), self.body)

    def test_raw_deflate_labelled_deflate(self):
        packer = zlib.compressobj(wbits=-15)
        raw = packer.compress(self.body) + packer.flush()
        self.assertEqual(web._decompress(raw, "deflate"), self.body)

    def test_gzip_body_mislabelled_deflate(self):
        # Servers do this, and being strict about it would cost real pages.
        self.assertEqual(web._decompress(gzip.compress(self.body), "deflate"), self.body)

    def test_uncompressed_passes_through(self):
        self.assertEqual(web._decompress(self.body, None), self.body)
        self.assertEqual(web._decompress(self.body, ""), self.body)

    def test_undecompressable_is_a_page_that_did_not_read(self):
        self.assertIsNone(web._decompress(b"not actually gzipped", "gzip"))

    def test_compression_bomb_is_capped(self):
        out = web._decompress(gzip.compress(b"A" * 50_000_000), "gzip")
        self.assertIsNotNone(out)
        self.assertLessEqual(len(out), web._MAX_DECOMPRESSED_BYTES)


class IsText(unittest.TestCase):
    """_MIN_TEXT only ever asked HOW MUCH text came back. Compressed bytes
    decoded to plenty of it."""

    def test_rejects_mojibake(self):
        # Seeded rather than os.urandom so a failure here is reproducible, and
        # incompressible so the gzip blob is the size a real page's would be —
        # repetitive bytes pack down to a few hundred characters and wouldn't
        # clear _MIN_TEXT on their own, which is the whole point being made.
        noise = random.Random(1).randbytes(30_000)
        mojibake = gzip.compress(noise).decode("utf-8", errors="replace")
        self.assertGreater(len(mojibake), web._MIN_TEXT)   # would have passed on length
        self.assertFalse(web._is_text(mojibake))

    def test_accepts_prose(self):
        self.assertTrue(web._is_text("Iceland is a Nordic island country. " * 20))

    def test_accepts_accented_prose(self):
        self.assertTrue(web._is_text("Reykjavík is the capital. " * 20 + "café naïve — é"))

    def test_tolerates_a_stray_replacement_character(self):
        self.assertTrue(web._is_text("A perfectly fine sentence about things. " * 20 + "�"))

    def test_rejects_empty(self):
        self.assertFalse(web._is_text(""))


class Context(unittest.TestCase):
    def setUp(self):
        self.results = [
            {"title": "A", "url": "https://a.example/x", "snippet": "snip A",
             "text": "PAGE TEXT A\nsecond line"},
            {"title": "B", "url": "https://b.example/y", "snippet": "snip B", "text": ""},
        ]

    def test_page_text_preferred_snippet_used_as_fallback(self):
        block = web.as_context(self.results)
        self.assertIn("PAGE TEXT A", block)
        self.assertNotIn("snip A", block)
        self.assertIn("snip B", block)

    def test_numbered_for_both_sides(self):
        block = web.as_context(self.results)
        self.assertIn("[1]", block)
        self.assertIn("[2]", block)

    def test_multi_line_body_stays_indented_under_its_number(self):
        # Several thousand characters between results; the indent is what
        # keeps a paragraph attached to the [2] it belongs to.
        self.assertIn("\n    second line", web.as_context(self.results))

    def test_tolerates_a_raw_search_result(self):
        self.assertIn("snip C", web.as_context(
            [{"title": "C", "url": "https://c.example", "snippet": "snip C"}]))


class Sources(unittest.TestCase):
    def setUp(self):
        self.results = [
            {"title": "A", "url": "https://a.example", "snippet": "s", "text": "page text"},
            {"title": "B", "url": "https://b.example", "snippet": "s", "text": ""},
        ]
        self.sources = web.as_sources(self.results)

    def test_page_text_does_not_cross_to_the_interfaces(self):
        # Thousands of characters per result, over the GUI bridge, to be
        # thrown away on the other side.
        for source in self.sources:
            self.assertNotIn("text", source)

    def test_read_flag_reflects_whether_the_page_was_opened(self):
        self.assertTrue(self.sources[0]["read"])
        self.assertFalse(self.sources[1]["read"])

    def test_console_marks_only_the_read_ones(self):
        lines = web.format_sources(self.sources).splitlines()
        self.assertIn("· read", lines[1])
        self.assertNotIn("read", lines[3])


if __name__ == "__main__":
    unittest.main()
