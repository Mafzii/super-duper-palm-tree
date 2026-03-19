"""Crawl engine backed by crawl4ai — replaces custom CrawlEngine for CLI use."""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Callable

from bs4 import BeautifulSoup

from .parser import _extract_main_content
from .worker import PageResult

if TYPE_CHECKING:
    from .ai.provider import AIProvider


class Crawl4AIEngine:
    def __init__(
        self,
        job_id: str,
        goal: str,
        seed_urls: list[str],
        ai_provider: "AIProvider",
        max_depth: int = 3,
        max_pages: int = 500,
        thread_count: int = 8,  # accepted but ignored; crawl4ai is async
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
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._respect_robots = respect_robots

        self._on_status_change = on_status_change or (lambda s: None)
        self._on_page_done_cb = on_page_done or (lambda r: None)
        self._on_sse = on_sse_event or (lambda e: None)

        self._cancelled = False
        self._ai_plan = None

    def stop(self) -> None:
        self._cancelled = True

    @property
    def ai_plan(self):
        return self._ai_plan

    def start(self) -> None:
        """Blocking entry point — bridges async crawl4ai into sync CLI."""
        # Planning phase
        self._on_status_change("planning")
        self._on_sse({"event": "status", "status": "planning"})

        focus_patterns: list[str] = []
        avoid_patterns: list[str] = []

        try:
            plan = self._ai.plan(self._goal, self._seed_urls, self._max_depth)
            self._ai_plan = plan
            self._on_sse({"event": "plan", "summary": plan.summary})
            focus_patterns = plan.focus_patterns or []
            avoid_patterns = plan.avoid_patterns or []
        except Exception:
            pass

        # Crawl phase
        self._on_status_change("running")
        self._on_sse({"event": "status", "status": "running"})

        asyncio.run(self._crawl_async(focus_patterns, avoid_patterns))

        if not self._cancelled:
            self._on_status_change("completed")
            self._on_sse({"event": "status", "status": "completed"})
        else:
            self._on_status_change("cancelled")
            self._on_sse({"event": "status", "status": "cancelled"})

    async def _crawl_async(
        self,
        focus_patterns: list[str],
        avoid_patterns: list[str],
    ) -> None:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

        # Build URL filter from AI plan patterns
        url_filter = None
        if avoid_patterns:
            try:
                from crawl4ai.deep_crawling import FilterChain, URLPatternFilter
                # Use avoid_patterns as an exclusion filter (reverse=True)
                url_filter = FilterChain([
                    URLPatternFilter(avoid_patterns, reverse=True),
                ])
            except ImportError:
                pass

        strategy = BFSDeepCrawlStrategy(
            max_depth=self._max_depth,
            include_external=True,
            max_pages=self._max_pages,
            **({"filter_chain": url_filter} if url_filter else {}),
        )

        run_config = CrawlerRunConfig(
            deep_crawl_strategy=strategy,
            stream=True,
            delay_before_return_html=self._min_delay,
        )

        browser_config = BrowserConfig(headless=True)
        pages_done = 0

        async with AsyncWebCrawler(config=browser_config) as crawler:
            for seed_url in self._seed_urls:
                if self._cancelled:
                    break

                async for result in await crawler.arun(
                    url=seed_url, config=run_config
                ):
                    if self._cancelled:
                        break

                    pages_done += 1
                    page = self._to_page_result(result)
                    self._on_page_done_cb(page)
                    self._on_sse({
                        "event": "page",
                        "url": page.url,
                        "depth": page.depth,
                        "pages_done": pages_done,
                    })

                    if pages_done >= self._max_pages:
                        self._cancelled = True
                        break

    @staticmethod
    def _to_page_result(result) -> PageResult:
        """Convert a crawl4ai CrawlResult into our PageResult."""
        # Extract text: prefer HTML through _extract_main_content for clean output
        text = ""
        html = getattr(result, "cleaned_html", None) or getattr(result, "html", None)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            text = _extract_main_content(soup)
        elif result.markdown:
            # Fallback: strip markdown image/link syntax
            raw = (
                result.markdown.raw_markdown
                if hasattr(result.markdown, "raw_markdown")
                else str(result.markdown)
            )
            raw = re.sub(r"!\[([^\]]*)\]\([^)]*\)", "", raw)  # images
            raw = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw)  # links → text
            text = " ".join(raw.split())[:6000]

        # Collect links
        links: list[str] = []
        if result.links:
            for link_dict in result.links.get("internal", []):
                href = link_dict.get("href", "")
                if href:
                    links.append(href)
            for link_dict in result.links.get("external", []):
                href = link_dict.get("href", "")
                if href:
                    links.append(href)

        # Error handling
        error = ""
        if not result.success:
            error = result.error_message or "unknown_error"
            if result.status_code:
                error += f":{result.status_code}"

        depth = result.metadata.get("depth", 0) if result.metadata else 0

        return PageResult(
            url=result.url,
            depth=depth,
            text=text,
            links=links,
            score=0.5,
            error=error,
            summary="",
        )
