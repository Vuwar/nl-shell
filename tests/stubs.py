"""Stand-ins for the two things the tests can't have: a model, and a network.

The model stub implements only the one shape ai_shell.llm uses - client.chat
.completions.create(...) returning something with .choices[0].message.content.
Replies are queued and handed out in order, which is what lets a test drive the
retry path by saying "answer badly, then answer well".

The HTTP stub is the same idea one layer down. ai_shell.fetch and
ai_shell.weights exist to survive a connection that dies mid-download, and that
failure can't be provoked against a real server on demand - so StubHTTP can be
told to drop the body after N bytes, to ignore a Range request, or to answer
with a status code, and the tests drive the recovery from there.
"""

import urllib.error


class StubClient:
    """Returns `replies` in order, one per call, and counts the calls."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = 0
        self.messages = []      # what was sent, for asserting on the retry
        # What the server would report having generated. None is a backend
        # that reports no usage at all, which the speed check has to survive.
        self.usage_tokens = 100
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls += 1
        self.messages.append(kwargs.get("messages"))
        # The last reply repeats if the code asks more times than expected,
        # so a runaway loop shows up as a wrong call count rather than an
        # IndexError that says nothing about what went wrong.
        payload = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        return _Response(payload, self.usage_tokens)


class DeadClient:
    """A model that can't be reached at all."""

    def __init__(self):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        raise RuntimeError("connection refused")


class _Response:
    def __init__(self, content, usage_tokens=100):
        self.choices = [_Choice(content)]
        self.usage = _Usage(usage_tokens) if usage_tokens is not None else None


class _Usage:
    def __init__(self, completion_tokens):
        self.completion_tokens = completion_tokens


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Message:
    def __init__(self, content):
        self.content = content


class StubResponse:
    """What urlopen returns: a readable body, a status, and headers.

    `fail_after` makes the body stop short, which is the failure this whole
    feature exists for - a connection that dies mid-download.
    """

    def __init__(self, body, status=200, headers=None, fail_after=None):
        self._body = body
        self._read = 0
        self._fail_after = fail_after
        self.status = status
        self.headers = headers or {}

    def read(self, size=-1):
        if self._fail_after is not None and self._read >= self._fail_after:
            raise ConnectionResetError("connection reset by peer")
        end = len(self._body) if size is None or size < 0 else self._read + size
        if self._fail_after is not None:
            end = min(end, self._fail_after)
        chunk = self._body[self._read:end]
        self._read += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StubHTTP:
    """Stands in for urllib.request.urlopen, serving one body.

    `ranges=False` is a server that ignores a Range request and sends the whole
    file with a 200 - the case that corrupts a naive resume. `failures` is how
    many of the next calls die after `fail_after` bytes.
    """

    def __init__(self, body, ranges=True, fail_after=None, failures=0, status=200):
        self.body = body
        self.ranges = ranges
        self.fail_after = fail_after
        self.failures = failures
        self.status = status
        self.requests = []      # every Request handed over, for asserting on Range

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.status >= 400:
            raise urllib.error.HTTPError(request.full_url, self.status, "no", {}, None)

        wanted = request.headers.get("Range")
        start = int(wanted.split("=")[1].split("-")[0]) if wanted and self.ranges else 0
        body = self.body[start:]

        dying = self.failures > 0
        if dying:
            self.failures -= 1

        return StubResponse(
            body,
            206 if (wanted and self.ranges) else 200,
            {"Content-Length": str(len(body))},
            self.fail_after if dying else None,
        )
