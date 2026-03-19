"""URL normalization and robots.txt caching."""
import time
import threading
import urllib.robotparser
from urllib.parse import urlparse, urlunparse, urljoin


def normalize_url(url: str, base: str = "") -> str:
    """Normalize URL: resolve relative, lowercase scheme/host, strip fragment."""
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    if not parsed.scheme:
        return ""
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=parsed.path or "/",
        fragment="",
    )
    return urlunparse(normalized)


class RobotsCache:
    """Thread-safe robots.txt cache with 24h TTL."""

    TTL = 86400  # seconds

    def __init__(self):
        self._cache: dict[str, tuple[urllib.robotparser.RobotFileParser, float]] = {}
        self._lock = threading.Lock()

    def _base_url(self, url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        base = self._base_url(url)
        with self._lock:
            entry = self._cache.get(base)
            now = time.monotonic()
            if entry is None or now - entry[1] > self.TTL:
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(f"{base}/robots.txt")
                try:
                    rp.read()
                except Exception:
                    # If we can't fetch robots.txt, allow by default
                    rp = None
                self._cache[base] = (rp, now)
                entry = self._cache[base]
            rp, _ = entry
            if rp is None:
                return True
            return rp.can_fetch(user_agent, url)
