"""ThreadPoolExecutor orchestrator: main crawl loop."""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable

from .rate_limiter import RateLimiter
from .url_queue import UrlQueue
from .url_utils import RobotsCache
from .worker import PageResult, Worker

if TYPE_CHECKING:
    from .ai.provider import AIProvider

RERANK_BUFFER_SIZE = 50


class CrawlEngine:
    def __init__(
        self,
        job_id: str,
        goal: str,
        seed_urls: list[str],
        ai_provider: "AIProvider",
        max_depth: int = 3,
        max_pages: int = 500,
        thread_count: int = 8,
        rate_limit_rps: float = 1.0,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
        respect_robots: bool = True,
        on_status_change: Callable[[str], None] | None = None,
        on_page_done: Callable[[PageResult], None] | None = None,
        on_sse_event: Callable[[dict], None] | None = None,
    ):
        self._job_id = job_id
        self._goal = goal
        self._seed_urls = seed_urls
        self._ai = ai_provider
        self._max_depth = max_depth
        self._max_pages = max_pages
        self._thread_count = thread_count
        self._respect_robots = respect_robots
        self._min_delay = min_delay
        self._max_delay = max_delay

        self._on_status_change = on_status_change or (lambda s: None)
        self._on_page_done_cb = on_page_done or (lambda r: None)
        self._on_sse = on_sse_event or (lambda e: None)

        self._stop_event = threading.Event()
        self._queue = UrlQueue()
        self._rate_limiter = RateLimiter(default_rps=rate_limit_rps)
        self._robots_cache = RobotsCache()

        self._pages_done = 0
        self._pages_lock = threading.Lock()
        self._rerank_buffer: list[str] = []
        self._rerank_lock = threading.Lock()
        self._ai_plan = None

    def stop(self) -> None:
        self._stop_event.set()

    def start(self) -> None:
        """Entry point — run in a background thread."""
        self._on_status_change("planning")
        self._on_sse({"event": "status", "status": "planning"})

        # AI planning phase
        try:
            plan = self._ai.plan(self._goal, self._seed_urls, self._max_depth)
            self._ai_plan = plan
            self._on_sse({"event": "plan", "summary": plan.summary})
            # Enqueue seeds with AI scores (lower score → higher priority number → lower urgency)
            seeded = {s.url for s in plan.prioritized_seeds}
            for scored in plan.prioritized_seeds:
                priority = (1.0 - scored.score) * 1000  # high score → low priority num
                self._queue.enqueue(scored.url, priority)
            # Add any seed_urls not covered by AI
            for url in self._seed_urls:
                if url not in seeded:
                    self._queue.enqueue(url, 500.0)
        except Exception as e:
            # Fall back to enqueuing seeds directly
            for url in self._seed_urls:
                self._queue.enqueue(url, 500.0)

        self._on_status_change("running")
        self._on_sse({"event": "status", "status": "running"})

        def make_worker() -> Worker:
            return Worker(
                url_queue=self._queue,
                rate_limiter=self._rate_limiter,
                robots_cache=self._robots_cache,
                stop_event=self._stop_event,
                on_page_done=self._handle_page_done,
                respect_robots=self._respect_robots,
                min_delay=self._min_delay,
                max_delay=self._max_delay,
                max_depth=self._max_depth,
            )

        with ThreadPoolExecutor(max_workers=self._thread_count) as pool:
            futures: list[Future] = [pool.submit(make_worker().run) for _ in range(self._thread_count)]
            for f in futures:
                f.result()  # propagate exceptions

        if not self._stop_event.is_set():
            self._on_status_change("completed")
            self._on_sse({"event": "status", "status": "completed"})
        else:
            self._on_status_change("cancelled")
            self._on_sse({"event": "status", "status": "cancelled"})

    def _handle_page_done(self, result: PageResult) -> None:
        with self._pages_lock:
            self._pages_done += 1
            pages = self._pages_done
            if pages >= self._max_pages:
                self._stop_event.set()

        self._on_page_done_cb(result)
        self._on_sse({
            "event": "page",
            "url": result.url,
            "depth": result.depth,
            "pages_done": pages,
        })

        # Buffer URLs for periodic reranking
        with self._rerank_lock:
            self._rerank_buffer.extend(result.links[:20])
            if len(self._rerank_buffer) >= RERANK_BUFFER_SIZE:
                batch = self._rerank_buffer[:RERANK_BUFFER_SIZE]
                self._rerank_buffer = self._rerank_buffer[RERANK_BUFFER_SIZE:]
            else:
                batch = []

        if batch:
            self._rerank_batch(batch, result.text)

    def _rerank_batch(self, urls: list[str], context: str) -> None:
        try:
            scored = self._ai.rerank(self._goal, urls, context)
            for item in scored:
                if self._queue.is_seen(item.url):
                    new_priority = (1.0 - item.score) * 1000
                    self._queue.requeue(item.url, new_priority)
        except Exception:
            pass

    @property
    def ai_plan(self):
        return self._ai_plan
