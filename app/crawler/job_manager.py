"""In-memory job registry with thread-safe create/get/cancel."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .ai.claude_provider import ClaudeProvider
from .ai.gemini_provider import GeminiProvider
from .engine import CrawlEngine
from .worker import PageResult


@dataclass
class Job:
    job_id: str
    goal: str
    seed_urls: list[str]
    config: dict
    status: str = "pending"  # pending|planning|running|completed|cancelled|error
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    results: list[dict] = field(default_factory=list)
    sse_events: list[dict] = field(default_factory=list)
    ai_plan: dict | None = None
    error: str = ""

    # Internal
    _engine: CrawlEngine | None = field(default=None, repr=False)
    _results_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _stats_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _sse_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _pages_crawled: int = 0
    _pages_error: int = 0

    def stats(self) -> dict:
        with self._stats_lock:
            return {
                "pages_crawled": self._pages_crawled,
                "pages_error": self._pages_error,
                "results_count": len(self.results),
            }

    def to_dict(self, include_results: bool = False) -> dict:
        d = {
            "job_id": self.job_id,
            "goal": self.goal,
            "seed_urls": self.seed_urls,
            "config": self.config,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stats": self.stats(),
            "ai_plan": self.ai_plan,
            "error": self.error,
        }
        if include_results:
            with self._results_lock:
                d["results"] = list(self.results)
        return d


class JobManager:
    def __init__(self):
        self._registry: dict[str, Job] = {}
        self._lock = threading.RLock()

    def create_job(self, payload: dict) -> Job:
        job_id = str(uuid.uuid4())
        config = {
            "max_depth": payload.get("max_depth", 3),
            "max_pages": payload.get("max_pages", 500),
            "thread_count": payload.get("thread_count", 8),
            "rate_limit_rps": payload.get("rate_limit_rps", 1.0),
            "min_delay_seconds": payload.get("min_delay_seconds", 1.0),
            "max_delay_seconds": payload.get("max_delay_seconds", 3.0),
            "respect_robots": payload.get("respect_robots", True),
            "ai_provider": payload.get("ai_provider", "claude"),
        }
        job = Job(
            job_id=job_id,
            goal=payload.get("goal", ""),
            seed_urls=payload.get("seed_urls", []),
            config=config,
        )
        with self._lock:
            self._registry[job_id] = job

        # Build AI provider
        provider_name = config["ai_provider"]
        if provider_name == "gemini":
            ai = GeminiProvider()
        else:
            ai = ClaudeProvider()

        # Build engine
        engine = CrawlEngine(
            job_id=job_id,
            goal=job.goal,
            seed_urls=job.seed_urls,
            ai_provider=ai,
            max_depth=config["max_depth"],
            max_pages=config["max_pages"],
            thread_count=config["thread_count"],
            rate_limit_rps=config["rate_limit_rps"],
            min_delay=config["min_delay_seconds"],
            max_delay=config["max_delay_seconds"],
            respect_robots=config["respect_robots"],
            on_status_change=lambda s, j=job: self._set_status(j, s),
            on_page_done=lambda r, j=job: self._on_page_done(j, r),
            on_sse_event=lambda e, j=job: self._push_sse(j, e),
        )
        job._engine = engine

        # Launch in daemon thread
        t = threading.Thread(target=self._run_engine, args=(job, engine), daemon=True)
        t.start()
        return job

    def _run_engine(self, job: Job, engine: CrawlEngine) -> None:
        try:
            engine.start()
            # Capture AI plan after run
            if engine.ai_plan:
                plan = engine.ai_plan
                job.ai_plan = {
                    "summary": plan.summary,
                    "prioritized_seeds": [
                        {"url": s.url, "score": s.score, "reason": s.reason}
                        for s in plan.prioritized_seeds
                    ],
                    "avoid_patterns": plan.avoid_patterns,
                    "focus_patterns": plan.focus_patterns,
                }
        except Exception as e:
            self._set_status(job, "error")
            job.error = str(e)

    def _set_status(self, job: Job, status: str) -> None:
        job.status = status
        job.updated_at = time.time()

    def _on_page_done(self, job: Job, result: PageResult) -> None:
        with job._stats_lock:
            if result.error:
                job._pages_error += 1
            else:
                job._pages_crawled += 1
        if not result.error:
            with job._results_lock:
                job.results.append({
                    "url": result.url,
                    "depth": result.depth,
                    "text_snippet": result.text[:500],
                    "links_count": len(result.links),
                    "score": result.score,
                })

    def _push_sse(self, job: Job, event: dict) -> None:
        with job._sse_lock:
            event["ts"] = time.time()
            job.sse_events.append(event)

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._registry.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._registry.values())

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._registry.get(job_id)
        if job and job._engine:
            job._engine.stop()
            return True
        return False
