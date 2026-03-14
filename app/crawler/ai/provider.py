"""AIProvider protocol and shared data types."""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ScoredUrl:
    url: str
    score: float  # 0.0 (irrelevant) to 1.0 (highly relevant)
    reason: str = ""


@dataclass
class CrawlPlan:
    summary: str
    prioritized_seeds: list[ScoredUrl] = field(default_factory=list)
    avoid_patterns: list[str] = field(default_factory=list)
    focus_patterns: list[str] = field(default_factory=list)


class AIProvider(Protocol):
    def plan(self, goal: str, seed_urls: list[str], max_depth: int) -> CrawlPlan:
        ...

    def rerank(
        self, goal: str, urls: list[str], context_summary: str
    ) -> list[ScoredUrl]:
        ...
