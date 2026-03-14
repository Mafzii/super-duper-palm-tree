"""HTTP client with UA rotation, random delays, and referrer headers."""
import random
import time

import httpx

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]


class HttpClient:
    """Per-thread HTTP client. Create one per worker thread."""

    def __init__(
        self,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
        timeout: float = 15.0,
    ):
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._ua = random.choice(USER_AGENTS)
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": self._ua},
        )

    def fetch(self, url: str, referrer: str = "") -> httpx.Response | None:
        """Fetch URL with random delay. Returns response or None on error."""
        delay = random.uniform(self._min_delay, self._max_delay)
        time.sleep(delay)
        headers = {}
        if referrer:
            headers["Referer"] = referrer
        try:
            response = self._client.get(url, headers=headers)
            response.raise_for_status()
            return response
        except Exception:
            return None

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
