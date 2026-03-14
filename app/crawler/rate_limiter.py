"""Per-domain token bucket rate limiter (no external dependencies)."""
import time
import threading


class TokenBucket:
    """Token bucket for a single domain."""

    def __init__(self, rate_rps: float):
        self._rate = rate_rps  # tokens per second
        self._tokens = rate_rps  # start full
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


class RateLimiter:
    """Per-domain rate limiter registry."""

    def __init__(self, default_rps: float = 1.0):
        self._default_rps = default_rps
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def acquire(self, domain: str) -> None:
        with self._lock:
            if domain not in self._buckets:
                self._buckets[domain] = TokenBucket(self._default_rps)
            bucket = self._buckets[domain]
        bucket.acquire()
