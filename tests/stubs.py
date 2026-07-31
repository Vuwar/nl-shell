"""A stand-in for the OpenAI client, so the answer path can be tested without
a model.

Only the one shape ai_shell.llm uses is implemented — client.chat.completions
.create(...) returning something with .choices[0].message.content. Replies are
queued and handed out in order, which is what lets a test drive the retry path
by saying "answer badly, then answer well".
"""


class StubClient:
    """Returns `replies` in order, one per call, and counts the calls."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = 0
        self.messages = []      # what was sent, for asserting on the retry
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls += 1
        self.messages.append(kwargs.get("messages"))
        # The last reply repeats if the code asks more times than expected,
        # so a runaway loop shows up as a wrong call count rather than an
        # IndexError that says nothing about what went wrong.
        payload = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        return _Response(payload)


class DeadClient:
    """A model that can't be reached at all."""

    def __init__(self):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        raise RuntimeError("connection refused")


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Message:
    def __init__(self, content):
        self.content = content
