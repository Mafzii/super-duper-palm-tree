"""Per-thread stateless crawl callable."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from .http_client import FetchError, HttpClient
from .parser import parse
from .rate_limiter import RateLimiter
from .url_utils import RobotsCache, normalize_url

if TYPE_CHECKING:
    from .url_queue import UrlQueue


@dataclass
class PageResult:
    url: str
    depth: int
    text: str
    links: list[str] = field(default_factory=list)
    score: float = 0.5
    error: str = ""
    summary: str = ""


class Worker:
    """Stateless worker — one instance per thread."""

    def __init__(
        self,
        url_queue: "UrlQueue",
        rate_limiter: RateLimiter,
        robots_cache: RobotsCache,
        stop_event: threading.Event,
        on_page_done,  # callable(PageResult)
        respect_robots: bool = True,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
        max_depth: int = 3,
        user_agent: str = "*",
    ):
        self._queue = url_queue
        self._rate_limiter = rate_limiter
        self._robots = robots_cache
        self._stop = stop_event
        self._on_page_done = on_page_done
        self._respect_robots = respect_robots
        self._max_depth = max_depth
        self._user_agent = user_agent
        self._http = HttpClient(min_delay=min_delay, max_delay=max_delay)

    def run(self) -> None:
        """Main worker loop — runs until stop_event or queue empty."""
        try:
            while not self._stop.is_set():
                item = self._queue.dequeue()
                if item is None:
                    break
                url, priority = item
                depth = int(priority // 1000) if priority >= 1000 else 0
                self._crawl(url, depth)
        finally:
            self._http.close()

    def _crawl(self, url: str, depth: int) -> None:
        if depth > self._max_depth:
            return

        if self._respect_robots and not self._robots.is_allowed(url, self._user_agent):
            return

        domain = urlparse(url).netloc
        self._rate_limiter.acquire(domain)

        if self._stop.is_set():
            return

        response = self._http.fetch(url)
        if isinstance(response, FetchError):
            error_msg = response.error_type
            if response.status_code:
                error_msg += f":{response.status_code}"
            self._on_page_done(PageResult(url=url, depth=depth, text="", error=error_msg))
            return

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return

        # Use final URL after redirects for correct relative link resolution
        final_url = str(response.url)
        links, text = parse(response.text, final_url)

        # Enqueue child links at next depth
        # Deprioritize same-site links so external content is crawled first
        page_host = urlparse(final_url).netloc
        for link in links:
            norm = normalize_url(link, final_url)
            if norm:
                link_host = urlparse(norm).netloc
                same_site = link_host == page_host
                # Within a depth band (e.g. 1000-1999), lower = higher urgency
                # External links get 100, same-site nav gets 800
                sub_priority = 800 if same_site else 100
                child_priority = (depth + 1) * 1000 + sub_priority
                self._queue.enqueue(norm, float(child_priority))

        result = PageResult(url=url, depth=depth, text=text, links=links)
        self._on_page_done(result)
