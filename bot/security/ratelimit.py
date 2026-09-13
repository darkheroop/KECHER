"""In-process sliding-window rate limiting.

Single-instance deployments use this directly. For multi-instance deployments,
swap :class:`SlidingWindowLimiter` for a shared (e.g. Redis) implementation
behind the same :meth:`allow` interface.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """Allow at most ``limit`` events per ``window`` seconds per key."""

    def __init__(
        self,
        limit: int,
        *,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = max(0, int(limit))
        self.window = float(window)
        self._clock = clock
        self._hits: dict[int, deque[float]] = {}

    def _prune(self, key: int, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        return hits

    def allow(self, key: int) -> bool:
        """Record an event and return True if it is within the limit."""
        if self.limit == 0:
            return True
        now = self._clock()
        hits = self._prune(key, now)
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: int) -> float:
        """Seconds until the next event for ``key`` would be allowed."""
        now = self._clock()
        hits = self._prune(key, now)
        if len(hits) < self.limit:
            return 0.0
        return max(0.0, self.window - (now - hits[0]))

    def reset(self, key: int | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)
