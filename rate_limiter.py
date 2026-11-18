"""Small in-memory guard for model-assisted automation planning.

The guard keeps automation cheap and predictable: deterministic commands never
touch it, duplicate planning requests reuse a short-lived plan, and bursts are
stopped locally before they can hit a provider limit.  Nothing is persisted.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Callable


Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: float = 0.0


class AutomationPlanningGuard:
    """Bound and cache model calls used only for automation planning."""

    def __init__(
        self,
        *,
        max_calls: int = 6,
        window_seconds: float = 60.0,
        cache_ttl_seconds: float = 300.0,
        max_cache_entries: int = 64,
        clock: Clock = time.monotonic,
    ) -> None:
        self.max_calls = max(1, int(max_calls))
        self.window_seconds = max(1.0, float(window_seconds))
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self.max_cache_entries = max(1, int(max_cache_entries))
        self._clock = clock
        self._calls: deque[float] = deque()
        self._cache: OrderedDict[str, tuple[float, tuple[Any, ...]]] = OrderedDict()
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _key(message: str) -> str:
        normalized = re.sub(r"\s+", " ", str(message)).strip().casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()
        expired = [
            key
            for key, (created_at, _value) in self._cache.items()
            if now - created_at > self.cache_ttl_seconds
        ]
        for key in expired:
            self._cache.pop(key, None)

    def lookup(self, message: str) -> tuple[bool, tuple[Any, ...]]:
        """Return a cached immutable plan without consuming call budget."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            key = self._key(message)
            cached = self._cache.get(key)
            if cached is None:
                return False, ()
            self._cache.move_to_end(key)
            return True, cached[1]

    def acquire(self) -> RateLimitDecision:
        """Reserve one provider call when the local sliding window permits it."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            if now < self._blocked_until:
                return RateLimitDecision(False, self._blocked_until - now)
            if len(self._calls) >= self.max_calls:
                retry_after = self.window_seconds - (now - self._calls[0])
                return RateLimitDecision(False, max(0.0, retry_after))
            self._calls.append(now)
            return RateLimitDecision(True)

    def store(self, message: str, plan: tuple[Any, ...]) -> None:
        """Cache one validated plan; user text itself is never stored as a key."""
        with self._lock:
            if self.cache_ttl_seconds <= 0:
                return
            now = self._clock()
            self._prune(now)
            key = self._key(message)
            self._cache[key] = (now, tuple(plan))
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_cache_entries:
                self._cache.popitem(last=False)

    def block_for(self, seconds: float) -> None:
        """Apply a local cooldown after a provider-side throttle response."""
        with self._lock:
            self._blocked_until = max(
                self._blocked_until,
                self._clock() + max(0.0, float(seconds)),
            )

    def status(self) -> dict[str, int | float]:
        with self._lock:
            now = self._clock()
            self._prune(now)
            return {
                "calls_in_window": len(self._calls),
                "max_calls": self.max_calls,
                "window_seconds": self.window_seconds,
                "cache_entries": len(self._cache),
                "blocked_seconds": max(0.0, self._blocked_until - now),
            }


__all__ = ["AutomationPlanningGuard", "RateLimitDecision"]
