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
    prefer_external: bool = False  # True for aggregators (HN, Reddit, etc.)


class AIProvider(Protocol):
    def plan(self, goal: str, seed_urls: list[str], max_depth: int) -> CrawlPlan:
        ...

    def summarize(self, goal: str, url: str, text: str) -> str:
        ...

    def generate_extraction_schema(self, goal: str, url: str, description: str, html: str = "") -> dict:
        """Generate a JSON CSS extraction schema from a natural language description.

        When html is provided, the AI uses the actual page structure to write
        accurate CSS selectors instead of guessing from the URL alone.

        Returns a dict compatible with crawl4ai's JsonCssExtractionStrategy schema format:
        {
            "name": "...",
            "baseSelector": "css selector",
            "fields": [
                {"name": "field_name", "selector": "css selector", "type": "text|attribute|html", ...}
            ]
        }
        """
        ...
