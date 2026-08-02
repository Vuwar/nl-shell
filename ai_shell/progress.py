"""How fast a download is going, and how long is left.

A rate taken from the last chunk is useless: chunks arrive in bursts, and a
number that reads "40 MB/s" and then "0.2 MB/s" a second later is worse than no
number at all. So this weights recent samples against the ones before them, and
says nothing until it has watched for long enough to be worth reading.

Nothing here touches the network or the disk. It is fed byte counts and a
clock, which is what makes it testable without either.
"""


class Smoother:
    """Byte counts in, a readable rate out.

    `started_at` is what was already on disk when this download began. Those
    bytes are not counted as having arrived, which is the difference between
    "2 MB/s" and "two gigabytes in forty milliseconds" on every resumed
    download.
    """

    # How long to watch before answering at all. Under this, the answer says
    # more about chunk timing than about the connection.
    MIN_SECONDS = 2.0

    # Weight given to the newest observation. Low enough that one slow chunk
    # doesn't halve the displayed rate, high enough to follow a connection
    # that genuinely drops.
    ALPHA = 0.25

    def __init__(self, started_at=None):
        self._base = started_at or 0
        self._first = None      # (bytes, time) of the first sample
        self._last = None       # (bytes, time) of the previous sample
        self._rate = None

    def sample(self, bytes_done, now):
        """Record `bytes_done` at time `now`, in seconds from any fixed clock."""
        if self._first is None:
            self._first = (bytes_done, now)
            self._last = (bytes_done, now)
            return

        last_bytes, last_time = self._last
        elapsed = now - last_time
        if elapsed <= 0:
            return  # the same instant twice; there is no rate in that

        instant = (bytes_done - last_bytes) / elapsed
        self._rate = instant if self._rate is None else (
            self.ALPHA * instant + (1 - self.ALPHA) * self._rate
        )
        self._last = (bytes_done, now)

    @property
    def rate(self):
        """Bytes per second, or None while that would be a guess."""
        if self._first is None or self._last is None or self._rate is None:
            return None
        if self._last[1] - self._first[1] < self.MIN_SECONDS:
            return None
        return self._rate if self._rate > 0 else None

    def eta_for(self, bytes_total):
        """Seconds left to reach `bytes_total`, or None when unanswerable."""
        rate = self.rate
        if not rate or not bytes_total:
            return None
        remaining = bytes_total - self._last[0]
        if remaining <= 0:
            return 0
        return int(remaining / rate)
