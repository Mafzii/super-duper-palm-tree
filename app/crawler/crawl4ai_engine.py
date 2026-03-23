"""Crawl engine backed by crawl4ai — replaces custom CrawlEngine for CLI use."""
from __future__ import annotations

import asyncio
import base64
import re
from typing import TYPE_CHECKING, Callable

from .worker import PageResult

if TYPE_CHECKING:
    from .ai.provider import AIProvider


class Crawl4AIEngine:
    # Safety cap: max chars kept after BM25 filtering, before sending to LLM
    MAX_TEXT_CHARS = 10_000

    def __init__(
        self,
        job_id: str,
        goal: str,
        seed_urls: list[str],
        ai_provider: "AIProvider",
        max_depth: int = 3,
        max_pages: int = 500,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
        on_status_change: Callable[[str], None] | None = None,
        on_page_done: Callable[[PageResult], None] | None = None,
        on_sse_event: Callable[[dict], None] | None = None,
        # Configurable engine parameters
        strategy: str = "bfs",
        content_filter: str = "bm25",
        bm25_threshold: float = 1.2,
        cache_mode: str = "bypass",
        stealth: bool = False,
        headless: bool = True,
        js_code: str | None = None,
        wait_for: str | None = None,
        extraction_strategy: object | None = None,
        score_threshold: float = 0.0,
        include_external: bool = True,
    ):
        self._job_id = job_id
        self._goal = goal
        self._seed_urls = seed_urls
        self._ai = ai_provider
        self._max_depth = max_depth
        self._max_pages = max_pages
        self._min_delay = min_delay
        self._max_delay = max_delay

        self._on_status_change = on_status_change or (lambda s: None)
        self._on_page_done_cb = on_page_done or (lambda r: None)
        self._on_sse = on_sse_event or (lambda e: None)

        self._cancelled = False
        self._ai_plan = None

        # Engine config
        self._strategy = strategy
        self._content_filter = content_filter
        self._bm25_threshold = bm25_threshold
        self._cache_mode = cache_mode
        self._stealth = stealth
        self._headless = headless
        self._js_code = js_code
        self._wait_for = wait_for
        self._extraction_strategy = extraction_strategy
        self._score_threshold = score_threshold
        self._include_external = include_external

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
        prefer_external = False
        crawl_seeds = list(self._seed_urls)

        try:
            plan = self._ai.plan(self._goal, self._seed_urls, self._max_depth)
            self._ai_plan = plan
            self._on_sse({"event": "plan", "summary": plan.summary})
            focus_patterns = plan.focus_patterns or []
            avoid_patterns = plan.avoid_patterns or []
            prefer_external = plan.prefer_external
            # Use AI-prioritized seed order when available
            if plan.prioritized_seeds:
                crawl_seeds = [s.url for s in plan.prioritized_seeds]
        except Exception as exc:
            self._on_sse({"event": "plan_error", "error": str(exc)})

        # Crawl phase
        self._on_status_change("running")
        self._on_sse({"event": "status", "status": "running"})

        asyncio.run(self._crawl_async(crawl_seeds, focus_patterns, avoid_patterns, prefer_external))

        if not self._cancelled:
            self._on_status_change("completed")
            self._on_sse({"event": "status", "status": "completed"})
        else:
            self._on_status_change("cancelled")
            self._on_sse({"event": "status", "status": "cancelled"})

    # Regex patterns for junk URLs that burn crawl budget.
    _DEFAULT_AVOID_PATTERNS = [
        r"/login\b", r"/logout\b", r"/signin\b", r"/signup\b", r"/register\b",
        r"/vote[?/]", r"/upvote\b", r"/downvote\b",
        r"/hide[?/]", r"/flag[?/]", r"/report\b",
        r"/user[?/]", r"/profile[?/]", r"/account[?/]",
        r"/from\?", r"/submit\b",
        r"/faq\b", r"/guidelines\b", r"/legal\b", r"/privacy\b", r"/terms\b",
        r"^mailto:",
    ]

    def _build_browser_config(self):
        from crawl4ai import BrowserConfig
        return BrowserConfig(headless=self._headless, enable_stealth=self._stealth)

    def _build_content_filter(self):
        if self._content_filter == "bm25":
            from crawl4ai.content_filter_strategy import BM25ContentFilter
            return BM25ContentFilter(
                user_query=self._goal,
                bm25_threshold=self._bm25_threshold,
            )
        elif self._content_filter == "pruning":
            from crawl4ai.content_filter_strategy import PruningContentFilter
            return PruningContentFilter()
        return None

    def _build_deep_crawl_strategy(self, url_filter, scorer):
        from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

        strategy_kwargs = {
            "max_depth": self._max_depth,
            "include_external": self._include_external,
            "max_pages": self._max_pages,
            "filter_chain": url_filter,
        }
        if scorer:
            strategy_kwargs["url_scorer"] = scorer

        if self._strategy == "bestfirst":
            from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
            return BestFirstCrawlingStrategy(**strategy_kwargs)
        elif self._strategy == "dfs":
            from crawl4ai.deep_crawling import DFSDeepCrawlStrategy
            return DFSDeepCrawlStrategy(**strategy_kwargs)
        else:
            return BFSDeepCrawlStrategy(**strategy_kwargs)

    def _build_run_config(self, strategy=None, screenshot: bool = False):
        from crawl4ai import CrawlerRunConfig
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

        cf = self._build_content_filter()
        md_generator = DefaultMarkdownGenerator(
            **({"content_filter": cf} if cf else {}),
            options={"ignore_links": True},
        )

        mean_delay = (self._min_delay + self._max_delay) / 2
        max_range = (self._max_delay - self._min_delay) / 2

        kwargs: dict = {
            "stream": True,
            "delay_before_return_html": self._min_delay,
            "mean_delay": mean_delay,
            "max_range": max_range,
            "markdown_generator": md_generator,
            "excluded_tags": ["nav", "footer", "header", "aside"],
        }

        if strategy:
            kwargs["deep_crawl_strategy"] = strategy
        if self._js_code:
            kwargs["js_code"] = [self._js_code]
        if self._wait_for:
            kwargs["wait_for"] = self._wait_for
        if self._cache_mode == "enabled":
            from crawl4ai import CacheMode
            kwargs["cache_mode"] = CacheMode.ENABLED
        else:
            from crawl4ai import CacheMode
            kwargs["cache_mode"] = CacheMode.BYPASS
        if self._extraction_strategy:
            kwargs["extraction_strategy"] = self._extraction_strategy
        if screenshot:
            kwargs["screenshot"] = True

        return CrawlerRunConfig(**kwargs)

    async def _crawl_async(
        self,
        seed_urls: list[str],
        focus_patterns: list[str],
        avoid_patterns: list[str],
        prefer_external: bool = False,
    ) -> None:
        from urllib.parse import urlparse

        from crawl4ai import AsyncWebCrawler
        from crawl4ai.deep_crawling.filters import FilterChain, URLFilter
        from crawl4ai.deep_crawling.scorers import URLScorer

        # Build URL exclusion filter from defaults + AI plan avoid patterns
        all_avoid = self._DEFAULT_AVOID_PATTERNS + [
            re.escape(p) for p in avoid_patterns
        ]
        compiled = [re.compile(p) for p in all_avoid]

        class _ExclusionFilter(URLFilter):
            """Rejects URLs matching any of the compiled regex patterns."""
            def apply(self, url: str) -> bool:
                for pat in compiled:
                    if pat.search(url):
                        self._update_stats(False)
                        return False
                self._update_stats(True)
                return True

        url_filter = FilterChain([_ExclusionFilter()])

        # Build URL scorer based on AI plan signals
        scorer = None
        compiled_focus = [re.compile(re.escape(p)) for p in focus_patterns] if focus_patterns else []

        if prefer_external:
            seed_domains = {urlparse(u).netloc.lower() for u in seed_urls}

            class _ExternalFirstScorer(URLScorer):
                def _calculate_score(self, url: str) -> float:
                    domain = urlparse(url).netloc.lower()
                    base = 0.2 if domain in seed_domains else 0.9
                    if compiled_focus and any(p.search(url) for p in compiled_focus):
                        base = min(base + 0.3, 1.0)
                    return base

            scorer = _ExternalFirstScorer()
        elif compiled_focus:
            class _FocusPatternScorer(URLScorer):
                def _calculate_score(self, url: str) -> float:
                    return 0.8 if any(p.search(url) for p in compiled_focus) else 0.4

            scorer = _FocusPatternScorer()

        strategy = self._build_deep_crawl_strategy(url_filter, scorer)
        run_config = self._build_run_config(strategy=strategy)
        browser_config = self._build_browser_config()
        pages_done = 0

        async with AsyncWebCrawler(config=browser_config) as crawler:
            for seed_url in seed_urls:
                if self._cancelled:
                    break

                async for result in await crawler.arun(
                    url=seed_url, config=run_config
                ):
                    if self._cancelled:
                        break

                    pages_done += 1
                    page = self._to_page_result(result)

                    if self._score_threshold > 0 and page.score < self._score_threshold:
                        continue

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

    def fetch_page(self, url: str) -> PageResult:
        """Fetch a single page without deep crawling. Blocking."""
        page, _ = asyncio.run(self._fetch_page_async(url))
        return page

    def fetch_page_with_html(self, url: str) -> tuple[PageResult, str]:
        """Fetch a single page, returning both PageResult and cleaned HTML."""
        return asyncio.run(self._fetch_page_async(url))

    async def _fetch_page_async(self, url: str) -> tuple[PageResult, str]:
        from crawl4ai import AsyncWebCrawler

        run_config = self._build_run_config()
        # Remove stream and deep_crawl_strategy for single-page fetch
        run_config.stream = False
        run_config.deep_crawl_strategy = None

        browser_config = self._build_browser_config()

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)
            html = getattr(result, "cleaned_html", "") or ""
            return self._to_page_result(result), html

    def screenshot_page(self, url: str) -> bytes:
        """Fetch a single page with screenshot. Returns PNG bytes. Blocking."""
        return asyncio.run(self._screenshot_page_async(url))

    async def _screenshot_page_async(self, url: str) -> bytes:
        from crawl4ai import AsyncWebCrawler

        run_config = self._build_run_config(screenshot=True)
        run_config.stream = False
        run_config.deep_crawl_strategy = None

        browser_config = self._build_browser_config()

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)
            screenshot_data = getattr(result, "screenshot", None) or ""
            return base64.b64decode(screenshot_data) if screenshot_data else b""

    @classmethod
    def _to_page_result(cls, result) -> PageResult:
        """Convert a crawl4ai CrawlResult into our PageResult."""
        # Extract text: fit_markdown (BM25-filtered) → raw_markdown → cleaned_html
        text = ""
        if result.markdown:
            fit = getattr(result.markdown, "fit_markdown", None)
            if fit:
                text = fit
            if not text:
                raw = getattr(result.markdown, "raw_markdown", None)
                if raw:
                    text = " ".join(raw.split())
        if not text:
            html = getattr(result, "cleaned_html", None) or ""
            if html:
                # Strip tags for a plain-text fallback
                text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
        text = text[:cls.MAX_TEXT_CHARS]

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
        score = abs(result.metadata.get("score", 0.0)) if result.metadata else 0.0

        # Title
        title = ""
        metadata = result.metadata or {}
        title = metadata.get("title", "") or getattr(result, "title", "") or ""

        # Status code
        status_code = getattr(result, "status_code", 0) or 0

        # Extracted content
        extracted = getattr(result, "extracted_content", "") or ""

        return PageResult(
            url=result.url,
            depth=depth,
            text=text,
            links=links,
            score=score,
            error=error,
            summary="",
            extracted_content=extracted,
            title=title,
            status_code=status_code,
        )
