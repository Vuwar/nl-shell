"""Looking something up on the internet — the one thing the model can't do itself.

The model is a local GGUF with no tools and no network: everything it knows is
frozen in its weights, and it has no way to find out that it doesn't know. Ask
it for today's news and it either refuses or invents something, and the two are
indistinguishable from the outside. This module is the missing half — the shell
does the fetching, and the model is only asked to read what came back.

Two halves to that, and they are not the same job:

  * search() finds out WHICH pages might answer the question. That needs an
    index of the whole web, which is a datacentre, so it's borrowed — one
    request to a search engine buys the link graph, the spam filtering and the
    ranking that decides what comes first.
  * read() finds out what a page actually SAYS. That needs nothing but an HTTP
    fetch, so it's ours.

The second is where the answers come from. A search result's snippet is one or
two sentences chosen to make someone click, not to answer anything, and a
model handed five snippets is being asked to do a much harder job than a model
handed the article. Borrow the judgement, own the reading.

Why a search engine's HTML rather than an API: an API key is a thing the user
would have to go and get, and this app's whole shape is that it works after one
launch with nothing configured. DuckDuckGo's HTML endpoints need no key and no
account, which makes them the only option that keeps that promise. The cost is
that this is scraping, and scraping breaks — so failure here is a normal
outcome with a plain-English message, never an exception the interfaces have to
handle.

Nothing above urllib is used, deliberately: the requirements file is two
packages, and "search the web" is not a good reason to make it three.
"""

import re
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

# Both are the same index with the ornament taken off. lite is tried first —
# it's a plain table of results, so there's less markup between us and the
# text, and it's the one more likely to still parse in a year. html is the
# fallback for when lite is the one having a bad day.
_ENDPOINTS = (
    "https://lite.duckduckgo.com/lite/",
    "https://html.duckduckgo.com/html/",
)

# A default urllib User-Agent is refused outright. This is a real browser
# string because the endpoint is a browser page — anything else is asking to be
# treated as the bot it technically is.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_TIMEOUT = 15

# Five is what a small model can actually hold in its head at once. The context
# window would take more, and the summary gets worse when it has to weigh ten
# half-relevant snippets instead of five good ones.
_MAX_RESULTS = 5

# Snippets are one or two sentences; anything much longer is the page's own
# boilerplate leaking in, and it costs context the answer needs.
_MAX_SNIPPET = 400

# The class names the two pages hang their results off. Matched as whole words
# because DuckDuckGo stacks several on one element ("result__a js-result-title-link").
_TITLE_CLASS = re.compile(r"\b(result__a|result-link)\b")
_SNIPPET_CLASS = re.compile(r"\b(result__snippet|result-snippet)\b")

# Both pages route clicks through a redirect that carries the real target in
# uddg=. An unredirected href is left alone — the shape has changed before.
_REDIRECT = re.compile(r"/l/\?|/l\.js\?")

# The "prove you're not a bot" page, which arrives as a perfectly ordinary
# HTTP 200 containing a picture puzzle and no results at all. Worth telling
# apart from an empty search: they look identical to a parser and mean
# opposite things to the user, and "nothing was found" sends someone off to
# rewrite a question that was fine.
_CHALLENGE = re.compile(r"anomaly-modal|anomaly\.js")

_WHITESPACE = re.compile(r"\s+")


class SearchError(RuntimeError):
    """The search couldn't be done — offline, blocked, or the page changed."""


class _Results(HTMLParser):
    """Pulls (title, url, snippet) out of a DuckDuckGo results page.

    The two pages disagree about tags — lite puts snippets in a <td>, html in
    an <a> — so this keys off class names and ignores the element they're on.
    Titles and snippets arrive strictly in pairs, in order, which is what lets
    a snippet attach to the result opened just before it without either page
    having to say so.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._collecting = None  # "title" | "snippet" | None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class") or ""
        if _TITLE_CLASS.search(classes):
            self._flush()
            self.results.append({"title": "", "url": _target(attributes.get("href")), "snippet": ""})
            self._collecting = "title"
        elif _SNIPPET_CLASS.search(classes) and self.results:
            self._flush()
            self._collecting = "snippet"

    def handle_endtag(self, tag):
        # Not checked against the tag that opened the span: the pages nest <b>
        # inside a title, and closing on the first end tag would truncate at
        # the first highlighted word.
        if self._collecting and tag in ("a", "td"):
            self._flush()

    def handle_data(self, data):
        if self._collecting:
            self._buffer.append(data)

    def close(self):
        """Whatever was still being collected when the page ended counts too —
        a truncated response shouldn't silently drop its last result."""
        super().close()
        self._flush()

    def _flush(self):
        if self._collecting and self.results:
            text = _WHITESPACE.sub(" ", "".join(self._buffer)).strip()
            if text:
                # A page can carry the same class twice for one result; the
                # first text wins rather than being appended to.
                self.results[-1][self._collecting] = (
                    self.results[-1][self._collecting] or text
                )[:_MAX_SNIPPET]
        self._buffer = []
        self._collecting = None


def _target(href):
    """The page a result actually points at, unwrapped from the redirect."""
    if not href:
        return ""
    if _REDIRECT.search(href):
        query = urllib.parse.urlparse(href).query
        wrapped = urllib.parse.parse_qs(query).get("uddg")
        if wrapped:
            return wrapped[0]
    if href.startswith("//"):
        return "https:" + href
    return href


def _fetch(url, query):
    """The results page for `query`, as text.

    POST rather than GET because that's the form these two endpoints publish;
    a GET is answered with a redirect to an interstitial on some of them.
    """
    data = urllib.parse.urlencode({"q": query}).encode()
    request = urllib.request.Request(url, data=data, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def search(query, limit=_MAX_RESULTS):
    """Web results for `query` as [{"title", "url", "snippet"}], best first.

    Raises SearchError when the search couldn't be run — nothing reachable, or
    every endpoint answering with a "prove you're not a bot" page. An endpoint
    that answers with a page this can't read is treated the same as one that
    didn't answer: the next endpoint gets a turn, and only when both are
    exhausted is it a failure, so a markup change on one page isn't an outage.

    An empty list means the search really did run and really found nothing,
    which is a different thing from any of the above and is not an error.
    """
    query = (query or "").strip()
    if not query:
        raise SearchError("There was nothing to search for.")

    reachable = False
    challenged = False
    for url in _ENDPOINTS:
        try:
            page = _fetch(url, query)
        except (urllib.error.URLError, OSError, ValueError):
            continue
        reachable = True
        if _CHALLENGE.search(page):
            challenged = True
            continue
        parser = _Results()
        parser.feed(page)
        parser.close()
        results = [r for r in parser.results if r["url"] and r["title"]]
        if results:
            return results[:limit]

    if not reachable:
        raise SearchError("Couldn't reach the internet to look that up.")
    if challenged:
        # Normally self-inflicted by searching several times quickly, and it
        # clears itself, so the message says to wait rather than suggesting
        # anything is wrong with the machine or the question.
        raise SearchError(
            "The search engine wants to check this computer isn't a robot, so "
            "the search didn't go through. It usually clears in a few minutes."
        )
    # Reached the engine and understood nothing it said. Which of the two it
    # is — a genuinely empty search or a page we can no longer read — isn't
    # knowable from here, and the honest message covers both.
    return []


# --- reading a page -------------------------------------------------------
#
# Everything below is the half that isn't scraping. Fetching one article
# because a person just asked a question about it is what a browser does, and
# it's the traffic a content site exists to serve — so unlike search(), this
# is not an uninvited guest, and it says who it is.
#
# It still fails, just differently and much less severely. A page can be
# behind a paywall, behind a bot check, or built entirely by JavaScript so the
# HTML arrives empty. None of that is fatal here: read() returns None, the
# caller keeps the search snippet it already had, and the next result gets a
# turn. Needing one of five pages to work is a completely different bet from
# needing one search engine to work.
#
# Where this grows later, without touching a caller:
#   * _EXTRACTORS dispatches on content type — a PDF or plain-text reader
#     plugs in beside the HTML one rather than inside it.
#   * _extract_html is a heuristic and is meant to be replaced by a better one
#     (density scoring, or a real readability port). MIN_TEXT below is what
#     makes that safe to attempt: an extractor that comes back with too little
#     is treated as having failed, so a bad rewrite degrades to the snippet
#     instead of feeding the model rubbish.
#   * A JavaScript-rendering backend would slot in as another extractor for
#     pages that come back empty — at the cost of a browser dependency this
#     app deliberately doesn't have yet.

# Honest, and different from the browser string search() has to send. That
# asymmetry is deliberate: the search endpoint refuses anything that doesn't
# look like a browser, so passing as one is the price of using it at all —
# while a site being read has no such gate, and there's no reason not to say
# what we are and let it decide.
_READER_HEADERS = {
    "User-Agent": "ai-shell/1.0 (local AI shell; fetches a page when its user asks a question)",
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    # Asked for because an article is mostly repeated markup and compresses to
    # a fraction of itself, and this is time a person spends watching a
    # prompt. Servers send it unasked anyway — python.org does — so the
    # decompression path below is not optional either way.
    "Accept-Encoding": "gzip, deflate",
}

# Short, because a person is watching a prompt. A slow page is not worth the
# wait when four other results are sitting there.
_READ_TIMEOUT = 8

# Stop reading a response after this much. Nothing legitimate needs more, and
# it's the difference between a mislabelled video file costing a moment and
# costing the whole session.
_MAX_PAGE_BYTES = 2_000_000

# Below this much extracted text, treat the read as failed. This is the line
# that catches the JavaScript shell and the paywall teaser — both of which
# come back as a valid page containing nothing worth reading, and both of
# which would otherwise be handed to the model as though they were the article.
#
# 250 was too low, and the way it failed is worth keeping written down. A
# JavaScript weather page extracted to 322 characters reading "Now------ Feels
# Like HHigh LLow Chance of Rain Wind Humidity" — every label the page renders,
# with the numbers left out because a script fills those in later. It cleared
# 250 comfortably and went to the model as though it were a forecast.
#
# Measured rather than guessed, because the obvious tighter tests are wrong:
# requiring sentences rejects python.org/downloads, which is a table and was
# the best source we had, and rejecting runs of "---" throws out RFCs, which
# use them as rules. Extracted length separates the two cleanly on its own —
# the two shells came to 322 and 359 characters, while the smallest page with
# anything real on it came to 3,594. 1000 sits in that gap with an order of
# magnitude of room either side.
#
# A genuinely short page is the cost, and a cheap one: it falls back to its
# search snippet, which for a page with only a few hundred characters on it is
# most of what was there anyway.
_MIN_TEXT = 1000

# How much marked-up <article> is enough to prefer it over the whole body.
# Deliberately not _MIN_TEXT: this one is choosing between two readings of a
# page that will be judged on its own afterwards, and a short <article> on a
# long page is a reason to keep looking, not a reason to fail.
_MIN_MAIN = 250

# The other way a read can be worthless: plenty of text, none of it text.
# _MIN_TEXT only ever asked how MUCH came back, so a body that decoded into
# thousands of characters of mojibake passed it and went to the model as
# though it were the article. That is what a compressed page looked like
# before the branch above existed, and it's what a mislabelled binary or a
# lie about the charset still looks like. Anything above this share of
# replacement characters and control bytes is not prose in any encoding.
_MAX_GIBBERISH = 0.05

# Cap on what decompresses out of a response, not just what arrives. Without
# it, asking for gzip would mean a few compressed kilobytes could insist on
# becoming gigabytes of memory, which is a thing hostile servers do on purpose.
_MAX_DECOMPRESSED_BYTES = 8_000_000

# A rules file is a few hundred lines. Anything claiming to be much more isn't
# one, and is being read before we've decided to trust the site at all.
_MAX_ROBOTS_BYTES = 500_000

# What one page contributes to the model's context. The window is 8k tokens
# and several pages have to share it with the question and the answer, so this
# is a budget rather than a preference. The top of an article is also where
# articles say what they're about.
_MAX_PAGE_CHARS = 2500

# How many read pages reach the model. Three at _MAX_PAGE_CHARS is roughly 2k
# tokens, which is what an 8k window can spare once the question, the prompt
# and room to answer are taken out. Note this caps what's *sent*, not what's
# *fetched* — see read_results.
_MAX_READ = 3

# Never fetched: their content is not text, and the cost of finding that out
# is a download.
_UNREADABLE = re.compile(r"\.(pdf|zip|gz|tar|exe|dmg|mp[34]|avi|mkv|jpe?g|png|gif|webp|svg|ico)$", re.I)

# Whole subtrees that are never the article — chrome, scripts, and the
# navigation furniture every page wraps its content in.
_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "svg", "canvas", "template", "iframe",
    "nav", "header", "footer", "aside", "form", "button", "select", "option",
})

# Tags whose content is a block, so the text either side of them shouldn't run
# together into one word.
_BLOCK_TAGS = frozenset({
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section",
    "article", "main", "blockquote", "pre", "figcaption", "dd", "dt",
    "h1", "h2", "h3", "h4", "h5", "h6",
})

# Where an article says it lives. When a page marks its own content this way,
# that marking beats any guess we could make.
_MAIN_TAGS = frozenset({"article", "main"})

# Tags that never close, so they must not open a subtree either — a <br> or an
# <img> counted as an opening tag would leave the depth counters stuck.
_VOID_TAGS = frozenset({
    "br", "img", "input", "hr", "meta", "link", "source", "track", "area",
    "base", "col", "embed", "param", "wbr",
})

# Addresses that aren't the public web. A search result is a URL chosen by
# somebody else, and following one to 127.0.0.1 would point this app's fetcher
# at whatever the user happens to be running locally — including the model
# server. Literal-only: a hostname that resolves to a private address gets
# past this, which is a real gap and a much less likely one.
_PRIVATE_HOST = re.compile(
    r"^(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?|\[?fc|\[?fd)",
    re.I,
)


class _Text(HTMLParser):
    """Readable text out of an HTML page.

    A heuristic, and knowingly so: it drops the subtrees that are never the
    article, prefers whatever the page marked as <article> or <main>, and
    keeps the rest. It does not try to work out which of five <div>s is the
    story — that's what a real readability implementation does, and it's the
    upgrade this class is shaped to accept later.

    Real HTML is also malformed constantly, and an unclosed <nav> would
    otherwise swallow the rest of the document. Depth counters are clamped at
    zero and the whole thing is backstopped by _MIN_TEXT, so the failure mode
    of every misparse is "returned too little" — which the caller already
    treats as a page that didn't read.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._chunks = []      # (inside_main, text)
        self._skip_depth = 0
        self._main_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            if tag == "br":
                self._chunks.append((self._main_depth > 0, "\n"))
            return
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _MAIN_TAGS:
            self._main_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self._chunks.append((self._main_depth > 0, "\n"))

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _MAIN_TAGS:
            self._main_depth = max(0, self._main_depth - 1)
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._chunks.append((self._main_depth > 0, "\n"))

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = " ".join(data.split())
        if self._skip_depth:
            return
        if data.strip():
            self._chunks.append((self._main_depth > 0, data))

    def text(self):
        """The page's readable text — the marked-up article if the page had
        one, otherwise everything that survived the skipping."""
        marked = [chunk for in_main, chunk in self._chunks if in_main]
        chosen = marked if _joined_length(marked) >= _MIN_MAIN else [c for _, c in self._chunks]
        return _tidy("".join(chosen))


def _joined_length(chunks):
    return sum(len(chunk) for chunk in chunks)


# Runs of blank lines, and the leading/trailing space every block boundary
# leaves behind.
_BLANK_RUN = re.compile(r"\n\s*\n\s*")
_SPACES = re.compile(r"[^\S\n]+")


def _tidy(text):
    """Collapse the whitespace an HTML-to-text pass always produces, without
    losing the line breaks that keep paragraphs apart."""
    text = _SPACES.sub(" ", text)
    text = _BLANK_RUN.sub("\n", text)
    lines = [line.strip() for line in text.split("\n")]
    # One- and two-character lines are almost always the remains of an icon,
    # a bullet or a separator, never prose.
    return "\n".join(line for line in lines if len(line) > 2).strip()


def _decompress(raw, encoding):
    """`raw` as plain bytes, whatever Content-Encoding says it's wrapped in.

    Not optional and not only about the header we send: servers compress
    unbidden, and the symptom is silent — gzip bytes decoded as text produce
    thousands of characters of mojibake, which looks to every length check
    like a page that read perfectly.

    Capped on the way out, because the whole point of a compression bomb is
    that the size you agreed to receive is not the size you end up holding.
    Anything that won't decompress returns None, which the caller reads as a
    page that didn't read.
    """
    encoding = (encoding or "").strip().lower()
    if encoding not in ("gzip", "deflate", "x-gzip"):
        return raw
    # Negative window bits accept a raw deflate stream; 16+MAX accepts gzip's
    # framing. Trying gzip first and falling back covers the servers that say
    # deflate and send one when they mean the other, which is common enough
    # that being strict here would cost real pages.
    for window in ((16 + zlib.MAX_WBITS, -zlib.MAX_WBITS) if "gzip" in encoding
                   else (-zlib.MAX_WBITS, 16 + zlib.MAX_WBITS, zlib.MAX_WBITS)):
        try:
            return zlib.decompressobj(window).decompress(raw, _MAX_DECOMPRESSED_BYTES)
        except zlib.error:
            continue
    return None


def _is_text(value):
    """Whether a decoded body is prose rather than bytes that survived being
    decoded. Cheap, and only ever asked to catch the obvious: a page whose
    every other character is a replacement mark or a control byte is not an
    article in some encoding we guessed wrong, it's not an article."""
    if not value:
        return False
    sample = value[:4000]
    bad = sum(1 for ch in sample if ch == "�" or (ord(ch) < 32 and ch not in "\t\n\r"))
    return bad / len(sample) <= _MAX_GIBBERISH


def _extract_html(page):
    parser = _Text()
    parser.feed(page)
    parser.close()
    return parser.text()


def _extract_plain(page):
    return _tidy(page)


# Content type (before any ";charset=") to the function that turns that body
# into text. The dispatch point: a PDF reader is a new entry here and nothing
# else changes.
_EXTRACTORS = {
    "text/html": _extract_html,
    "application/xhtml+xml": _extract_html,
    "text/plain": _extract_plain,
}

# One RobotFileParser per site, kept for the life of the process. Without this
# a five-page read is five extra requests, and the same host comes up
# constantly across a session.
#
# Unlocked, though read_all writes to it from several threads. Two results on
# one host can therefore both fetch the same robots.txt before either has
# stored it — one wasted request, and then whichever finishes last wins with
# an answer identical to the one it replaced. A lock would remove a duplicate
# request at the cost of making every read wait on one host's rules file.
_robots_cache = {}


def _robots_rules(root):
    """This site's parsed robots.txt, or None if it didn't produce one.

    The fetch is done here rather than by RobotFileParser.read(), which is the
    obvious way to write this and is wrong in a way that hides. read() fetches
    with urllib's default User-Agent, and sites that refuse that agent answer
    403 — whereupon the stdlib records "disallow everything" and returns
    normally, with nothing raised for a caller to notice. Wikipedia is one of
    those sites. Left alone, this function's own docstring about failing open
    was false, and the single best source on the web was the one page the
    reader would never open.

    So the request is ours, with the honest User-Agent the rules should be
    judged against, and every failure is an exception we can see and treat as
    silence.
    """
    request = urllib.request.Request(root + "/robots.txt", headers=_READER_HEADERS)
    with urllib.request.urlopen(request, timeout=_READ_TIMEOUT) as response:
        raw = _decompress(response.read(_MAX_ROBOTS_BYTES), response.headers.get("Content-Encoding"))
    parser = urllib.robotparser.RobotFileParser()
    parser.parse((raw or b"").decode("utf-8", errors="replace").splitlines())
    return parser


def _robots_allow(url):
    """Whether this site's robots.txt permits fetching `url`.

    Respected even though a single fetch a user just asked for is closer to a
    browser than to a crawler, and the rules are written for crawlers. It
    costs a handful of sites, and it's the difference between a tool whose
    behaviour you can describe out loud and one you can't.

    Fails open, and now genuinely: a robots.txt that can't be fetched, or that
    the site won't serve us, is the site declining to say — which is not the
    same as declining. A file that loads and says no is obeyed.
    """
    parts = urllib.parse.urlparse(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in _robots_cache:
        try:
            _robots_cache[root] = _robots_rules(root)
        except Exception:
            _robots_cache[root] = None  # asked, got nothing
    parser = _robots_cache[root]
    if parser is None:
        return True
    try:
        return parser.can_fetch(_READER_HEADERS["User-Agent"], url)
    except Exception:
        return True


def readable_url(url):
    """Whether `url` is worth even trying: a public web address, not an
    obvious binary. Checked before fetching, because the cheapest download is
    the one that doesn't happen."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    host = urllib.parse.urlparse(url).netloc.split("@")[-1]
    if not host or _PRIVATE_HOST.match(host):
        return False
    return not _UNREADABLE.search(urllib.parse.urlparse(url).path)


def read(url, max_chars=_MAX_PAGE_CHARS):
    """The readable text of the page at `url`, or None.

    None is an ordinary answer, not an error, and it covers every way this
    doesn't work: refused by robots.txt, unreachable, timed out, not a text
    document, or a page whose HTML contains nothing worth reading — the
    JavaScript shell and the paywall teaser both land here. Every caller is
    expected to have something to fall back on, which is what makes this safe
    to attempt on any URL at all.
    """
    if not readable_url(url) or not _robots_allow(url):
        return None

    request = urllib.request.Request(url, headers=_READER_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=_READ_TIMEOUT) as response:
            content_type = (response.headers.get_content_type() or "").lower()
            extract = _EXTRACTORS.get(content_type)
            if not extract:
                return None
            # Capped read rather than .read(): a body with no Content-Length
            # is otherwise a promise to download whatever arrives.
            raw = _decompress(response.read(_MAX_PAGE_BYTES), response.headers.get("Content-Encoding"))
            charset = response.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, OSError, ValueError):
        return None

    if raw is None:
        return None

    try:
        page = raw.decode(charset, errors="replace")
    except LookupError:
        # A charset nothing has heard of. The label is wrong, not the page.
        page = raw.decode("utf-8", errors="replace")

    # Checked before extraction rather than after: run the parser over binary
    # and it finds no tags, hands back the whole thing as one long "line", and
    # every length check downstream agrees it's a fine article.
    if not _is_text(page):
        return None

    try:
        text = extract(page)
    except Exception:
        # A malformed document is a page that didn't read, not a crash. This
        # is also the guard that makes swapping in a new extractor a low-risk
        # change rather than one that can take the app down.
        return None

    if len(text) < _MIN_TEXT or not _is_text(text):
        return None
    return text[:max_chars]


def read_all(urls, max_chars=_MAX_PAGE_CHARS):
    """{url: text} for the pages that could be read, skipping those that
    couldn't.

    Concurrent because this is latency the user is sitting through: read one
    after another and a slow page adds its whole timeout to the wait, while
    together the cost is the slowest single page. Small pool — this is a
    handful of URLs, and it should look like a few browser tabs opening, not
    like a crawl.
    """
    urls = [u for u in dict.fromkeys(urls) if readable_url(u)]
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=min(5, len(urls))) as pool:
        texts = pool.map(lambda u: read(u, max_chars), urls)
    return {url: text for url, text in zip(urls, texts) if text}


def read_results(results, max_pages=_MAX_READ, max_chars=_MAX_PAGE_CHARS):
    """`results` again, with each page's text attached where it could be read.

    This is where the two halves meet. The search said which pages might
    answer the question; this goes and finds out what they say, so the model
    is handed articles instead of the one-line teasers a search engine prints
    to make someone click.

    Every result is attempted, not just the first few. The reads run together,
    so trying five costs the same wait as trying three, and which three come
    back isn't knowable in advance — that's the whole reliability argument for
    reading rather than searching harder. The cap is applied afterwards, to
    what reaches the model: the first `max_pages` that succeeded keep their
    text and everything else keeps its snippet, because the scarce thing is
    the context window, not the fetching.

    A result whose page didn't read is not dropped and not marked as broken.
    It carries the snippet it always had, which is exactly the app's previous
    behaviour — so the worst case of this whole feature is the old one.
    """
    pages = read_all([result["url"] for result in results], max_chars)
    enriched = []
    kept = 0
    for result in results:
        text = pages.get(result["url"]) if kept < max_pages else None
        if text:
            kept += 1
        enriched.append({**result, "text": text or ""})
    return enriched


def as_sources(results):
    """The results as the interfaces show them: what to display, what to open,
    and whether the answer was read out of the page or off its snippet.

    Page text is deliberately dropped here rather than passed along. The
    interfaces have no use for it — they show a title and a link — and it's
    thousands of characters per result that would otherwise cross the GUI's
    bridge on every search to be thrown away on the other side.
    """
    return [
        {
            "title": result["title"],
            "url": result["url"],
            "snippet": result.get("snippet", ""),
            "read": bool(result.get("text")),
        }
        for result in results
    ]


def format_sources(sources):
    """The sources as two lines each, for a console.

    Numbered to match as_context, so the [2] in the model's answer is the [2]
    the user can read for themselves — which is the whole reason the sources
    are printed at all rather than being an appendix nobody looks at.

    The read ones say so. It's a small mark for a real distinction: an answer
    drawn from the article and an answer drawn from a search engine's teaser
    are not equally trustworthy, and the user is the one who should get to
    weigh that rather than being shown both as though they were the same.
    """
    lines = []
    for index, source in enumerate(sources, 1):
        lines.append(f"[{index}] {source['title']}")
        mark = "  · read" if source.get("read") else ""
        lines.append(f"    {source['url']}{mark}")
    return "\n".join(lines)


def as_context(results):
    """The results as the numbered block the model is asked to answer from.

    Numbered because the answer refers back to them by number, and that only
    works if both sides are looking at the same list.

    An entry is the page's text when it could be read and the search snippet
    when it couldn't, and it isn't labelled as either. The model's job is to
    answer from what's in front of it, and telling it that [1] is a full
    article while [3] is a fragment invites it to rank the sources — which is
    a judgement a 3B model makes badly, and one the numbering already lets the
    user make for themselves.
    """
    blocks = []
    for index, result in enumerate(results, 1):
        body = result.get("text") or result.get("snippet") or "(no summary text)"
        # Every line indented under its own number, page text included: with
        # several thousand characters between one result and the next, the
        # indent is what keeps a paragraph visibly attached to the [2] it
        # belongs to instead of drifting into [3].
        body = "\n".join(f"    {line}" for line in body.splitlines())
        blocks.append(f"[{index}] {result['title']}\n    {result['url']}\n{body}")
    return "\n\n".join(blocks)
