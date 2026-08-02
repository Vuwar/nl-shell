"""Well-known websites, and what "open eminem on youtube" means for each.

Opening something on a site is an action, and the model kept reading it as a
question. Its search rule mentioned "finding a website or a channel", which is
close enough to "open X on youtube" that a 3B model routed the request into a
web lookup - and the user, who asked for a thing to be opened, got a paragraph
explaining that they could search YouTube for it. A shell that describes the
action instead of taking it has failed at the only job it has.

So this rule answers the ones it can answer exactly. The site is named, the
thing is named, and the address of a YouTube search is a fact rather than
something to reason about.

The table is deliberately short and deliberately incomplete. Sites not in it
fall through to the model, which the prompt now tells to build a URL and open
it - worse odds than a table lookup, but the table can't be everything and a
half-remembered address still beats prose telling the user to go and search.

What this does NOT do is guess. Every pattern below needs a launch verb at the
front and a site from the table, and anything that could plausibly be about a
file, a folder, or an app on this machine is handed back. A rule that turned
every sentence containing "youtube" into a URL would break real file requests
that happen to mention a website, and those are where being wrong costs most.

Addresses are the .com ones. A user in another country gets the global site
rather than their local one, which is the same thing typing the name into a
browser's address bar mostly does.
"""

import re
from urllib.parse import quote, quote_plus

from ai_shell.rules import base

# name, home page, search URL with {q} where the query goes, then the aliases
# a user might type. The search URL is the site's own search, not a search
# engine's: "open eminem on youtube" wants YouTube's results, and handing the
# request to Google would be answering a different question.
TABLE = (
    ("YouTube", "https://www.youtube.com",
     "https://www.youtube.com/results?search_query={q}", ("youtube", "yt", "you tube")),
    ("YouTube Music", "https://music.youtube.com",
     "https://music.youtube.com/search?q={q}", ("youtube music", "yt music")),
    ("Spotify", "https://open.spotify.com",
     "https://open.spotify.com/search/{q}", ("spotify",)),
    ("Google", "https://www.google.com",
     "https://www.google.com/search?q={q}", ("google",)),
    ("Google Maps", "https://www.google.com/maps",
     "https://www.google.com/maps/search/{q}", ("google maps", "maps")),
    ("Google Images", "https://images.google.com",
     "https://www.google.com/search?tbm=isch&q={q}", ("google images",)),
    ("Google Drive", "https://drive.google.com",
     "https://drive.google.com/drive/search?q={q}", ("google drive",)),
    ("Gmail", "https://mail.google.com",
     "https://mail.google.com/mail/u/0/#search/{q}", ("gmail",)),
    # x.com rather than twitter.com, and both names, because the rename is
    # years old and the old name is still what half the world says.
    ("X", "https://x.com", "https://x.com/search?q={q}", ("x", "twitter")),
    ("Reddit", "https://www.reddit.com",
     "https://www.reddit.com/search/?q={q}", ("reddit",)),
    ("GitHub", "https://github.com", "https://github.com/search?q={q}", ("github",)),
    ("Wikipedia", "https://www.wikipedia.org",
     "https://en.wikipedia.org/w/index.php?search={q}", ("wikipedia", "wiki")),
    ("Amazon", "https://www.amazon.com", "https://www.amazon.com/s?k={q}", ("amazon",)),
    ("eBay", "https://www.ebay.com",
     "https://www.ebay.com/sch/i.html?_nkw={q}", ("ebay",)),
    ("Netflix", "https://www.netflix.com",
     "https://www.netflix.com/search?q={q}", ("netflix",)),
    ("Twitch", "https://www.twitch.tv",
     "https://www.twitch.tv/search?term={q}", ("twitch",)),
    ("Instagram", "https://www.instagram.com",
     "https://www.instagram.com/explore/search/keyword/?q={q}", ("instagram", "insta")),
    ("TikTok", "https://www.tiktok.com",
     "https://www.tiktok.com/search?q={q}", ("tiktok", "tik tok")),
    ("Facebook", "https://www.facebook.com",
     "https://www.facebook.com/search/top?q={q}", ("facebook", "fb")),
    ("LinkedIn", "https://www.linkedin.com",
     "https://www.linkedin.com/search/results/all/?keywords={q}", ("linkedin",)),
    ("Stack Overflow", "https://stackoverflow.com",
     "https://stackoverflow.com/search?q={q}", ("stack overflow", "stackoverflow")),
    ("ChatGPT", "https://chatgpt.com", "https://chatgpt.com/?q={q}", ("chatgpt",)),
    ("DuckDuckGo", "https://duckduckgo.com",
     "https://duckduckgo.com/?q={q}", ("duckduckgo", "ddg")),
)

_BY_ALIAS = {alias: entry for entry in TABLE for alias in entry[3]}

# Longest alias first, so "youtube music" is matched as itself rather than as
# "youtube" with a stray word left over, and "google maps" doesn't resolve to
# Google. Regex alternation takes the first branch that matches, not the best
# one, so the ordering here is the whole mechanism.
_SITES = "|".join(re.escape(alias) for alias in sorted(_BY_ALIAS, key=len, reverse=True))

# Verbs that mean "do this", as opposed to asking about it. "search" and "find"
# are in here because "search youtube for eminem" is an instruction; they can't
# turn a plain "search for cheap flights" into a site launch, since every
# pattern below also needs a site from the table.
_VERB = (r"(?:open|launch|start|run|play|watch|listen to|go to|goto|take me to|"
         r"pull up|bring up|put on|show me|search for|search|look up|find)")

# 1. "open eminem on youtube" - the reported case, and the common one.
_ON_SITE = re.compile(
    rf"^{_VERB}\s+(?P<thing>.+?)\s+(?:on|in|at|with|using)\s+(?P<site>{_SITES})$", re.I)

# 2. "open spotify and play rap" - site first, thing second. The one ordering
#    where the thing isn't introduced by a preposition.
_AND_THEN = re.compile(
    rf"^{_VERB}\s+(?P<site>{_SITES})\s*(?:,|and|then|and then)\s+{_VERB}\s+(?P<thing>.+)$", re.I)

# 3. "search youtube for eminem" - the site as the thing being searched.
_SEARCH_FOR = re.compile(
    rf"^(?:search|look up|look in|find)\s+(?:on|in)?\s*(?P<site>{_SITES})\s+for\s+(?P<thing>.+)$",
    re.I)

# 4. "open youtube" - nothing to look for, just the site.
_BARE = re.compile(rf"^{_VERB}\s+(?P<site>{_SITES})$", re.I)

# Most specific first: a bare site is the fallback, and the two-verb pattern
# has to be tried before the preposition one can mistake "and play rap" for
# part of a name.
_PATTERNS = (_SEARCH_FOR, _AND_THEN, _ON_SITE, _BARE)


def resolve(text, machine):
    """`text` as a website to open, or None if it isn't one."""
    if base.is_question(text):
        return None

    for pattern in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        name, home, search, _ = _BY_ALIAS[match.group("site").lower()]
        thing = (match.groupdict().get("thing") or "").strip(" .!?,")
        if not thing:
            return _home(name, home, machine)
        if base.doubtful(thing):
            return None
        return base.open_url(
            _fill(search, thing), f"Opening a {name} search for {thing} in your browser.")
    return None


def _home(name, home, machine):
    """The site's front page - unless an app of the same name is installed.

    "Open spotify" on a machine with Spotify on it means the app, and opening
    the website instead would be substituting something the user didn't ask
    for. The model and the executor's app fallback already handle that case
    properly, so this hands it back rather than competing with it.

    Only bare requests defer. "Open spotify and play rap" names something to
    play, which a desktop app can't be told from a command line.
    """
    if machine.has_app(name):
        return None
    return base.open_url(home, f"Opening {name} in your browser.")


def _fill(template, query):
    """`template` with the query escaped for the half of the URL it lands in.

    Not one escaping function, because the two halves of a URL don't agree on
    what a space is. In a query string it's "+"; in a path "+" is a literal
    plus sign, so encoding a path the query-string way turns a search for
    "hip hop" into a search for "hip+hop". Spotify's search is a path and
    YouTube's is a query string, which is how one table needs both.
    """
    head, _, tail = template.partition("{q}")
    escaped = quote_plus(query) if "?" in head else quote(query, safe="")
    return head + escaped + tail
