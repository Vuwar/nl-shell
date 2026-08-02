"""ai_shell.rules.sites - "open eminem on youtube" is an action, not a question.

The bug these exist for: the model read "finding a channel" in its search rule,
put the request in "search", and the shell answered with prose telling the user
to go and search YouTube themselves. A shell that explains how to do the thing
instead of doing it has failed at the only job it has.

The rejection tests carry the weight here. A rule that turned any sentence with
"youtube" in it into a URL would break every real file request that happens to
mention a website, and those are the requests where being wrong costs the most.

Everything goes through rules.resolve rather than calling the rule directly -
that's the path the app takes, including the tidying in rules.base, so a change
that breaks the wiring fails here rather than passing in isolation.
"""

import unittest

from ai_shell import rules


def _resolve(text, apps=()):
    return rules.resolve(text, rules.Machine(lambda: apps))


class ThingOnSite(unittest.TestCase):
    """The reported case: a named thing, on a named site."""

    def test_open_x_on_youtube_searches_youtube(self):
        answer = _resolve("open eminem on youtube")
        self.assertIn("https://www.youtube.com/results?search_query=eminem", answer.command)
        self.assertEqual(answer.explanation,
                         "Opening a YouTube search for eminem in your browser.")

    def test_in_reads_the_same_as_on(self):
        # What the user actually types about as often. Same request.
        answer = _resolve("open eminem in youtube")
        self.assertIn("https://www.youtube.com/results?search_query=eminem", answer.command)

    def test_play_is_a_launch_verb_too(self):
        self.assertIn("search_query=lofi", _resolve("play lofi on youtube").command)

    def test_a_site_named_first_still_resolves(self):
        answer = _resolve("search youtube for eminem")
        self.assertIn("https://www.youtube.com/results?search_query=eminem", answer.command)

    def test_two_verbs_in_one_sentence(self):
        # "open spotify and play rap" - the site is the first target and the
        # thing is the second, which is the one ordering that isn't "X on Y".
        answer = _resolve("open spotify and play rap")
        self.assertIn("https://open.spotify.com/search/rap", answer.command)

    def test_case_does_not_matter(self):
        self.assertIsNotNone(_resolve("Open Eminem On YouTube"))

    def test_trailing_punctuation_does_not_matter(self):
        self.assertIsNotNone(_resolve("open eminem on youtube!"))

    def test_a_politeness_prefix_does_not_matter(self):
        self.assertIn("search_query=eminem", _resolve("can you open eminem on youtube").command)


class Encoding(unittest.TestCase):
    """A query goes into a URL, and the two halves of a URL escape differently."""

    def test_spaces_in_a_query_string(self):
        answer = _resolve("play hip hop on youtube")
        self.assertIn("https://www.youtube.com/results?search_query=hip+hop", answer.command)

    def test_spaces_in_a_path_segment(self):
        # Spotify's web search is a path, where "+" is a literal plus and not
        # a space. Encoding both halves the same way is how a search for
        # "hip hop" quietly becomes a search for "hip+hop".
        answer = _resolve("open spotify and play hip hop")
        self.assertIn("https://open.spotify.com/search/hip%20hop", answer.command)

    def test_a_character_that_would_break_the_url(self):
        answer = _resolve("search google for c# generics")
        self.assertIn("https://www.google.com/search?q=c%23+generics", answer.command)


class BareSite(unittest.TestCase):
    """No thing to look for - just the site."""

    def test_open_youtube_is_the_home_page(self):
        answer = _resolve("open youtube")
        self.assertIn("https://www.youtube.com", answer.command)
        self.assertEqual(answer.explanation, "Opening YouTube in your browser.")

    def test_an_installed_app_beats_the_website(self):
        # "open spotify" with Spotify on the machine means the app. Opening
        # the website instead would be substituting something the user didn't
        # ask for - and the model plus the executor's app fallback already
        # handle this case properly.
        self.assertIsNone(_resolve("open spotify", apps=[("Spotify", "spotify.exe")]))

    def test_an_installed_app_does_not_beat_a_thing_on_the_website(self):
        # "open spotify and play rap" names something to play, which the
        # desktop app can't be told to do from a command line.
        answer = _resolve("open spotify and play rap", apps=[("Spotify", "spotify.exe")])
        self.assertIn("https://open.spotify.com/search/rap", answer.command)

    def test_an_unrelated_app_changes_nothing(self):
        answer = _resolve("open youtube", apps=[("Notepad", "notepad.exe")])
        self.assertIn("https://www.youtube.com", answer.command)

    def test_a_browser_is_not_the_google_app(self):
        # Google Chrome is not Google. Matching loosely here would send
        # "open google" off to launch a browser at whatever its home page is,
        # instead of to the search page the user asked for.
        answer = _resolve("open google", apps=[("Google Chrome", "chrome.exe")])
        self.assertIn("https://www.google.com", answer.command)


class LongestAliasWins(unittest.TestCase):
    """Sites whose names contain other sites' names."""

    def test_google_maps_is_not_google(self):
        self.assertIn("google.com/maps", _resolve("open google maps").command)

    def test_youtube_music_is_not_youtube(self):
        answer = _resolve("play jazz on youtube music")
        self.assertIn("https://music.youtube.com/search?q=jazz", answer.command)


class NotASiteLaunch(unittest.TestCase):
    """Everything this must keep its hands off. See the module docstring."""

    def _rejected(self, text):
        self.assertIsNone(_resolve(text), f"should not have matched: {text}")

    def test_a_folder_that_happens_to_be_called_youtube(self):
        self._rejected("open the youtube folder on my desktop")

    def test_a_file_opened_in_an_application(self):
        self._rejected("open resume.pdf in notepad")

    def test_a_site_this_does_not_know(self):
        self._rejected("open eminem on limewire")

    def test_a_plain_web_search(self):
        # No site named, so this is a real search - the model's job, not ours.
        self._rejected("search for cheap flights to istanbul")

    def test_a_pronoun_is_not_a_thing_to_search_for(self):
        # "it" refers to something earlier in the conversation, which the
        # rules cannot see. Searching YouTube for the word "it" is worse than
        # letting the model, which has the history, decide.
        self._rejected("open it on youtube")

    def test_a_question_about_a_site(self):
        self._rejected("how do i open eminem on youtube")

    def test_a_file_path_is_never_a_search_term(self):
        self._rejected("open C:\\Users\\Me\\clip.mp4 on youtube")

    def test_a_site_mentioned_in_passing(self):
        self._rejected("delete the youtube shortcut on my desktop")

    def test_a_photo_is_not_the_site_called_x(self):
        # "x" is an alias for x.com, and "open X photo" is a file request.
        self._rejected("open X photo")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
