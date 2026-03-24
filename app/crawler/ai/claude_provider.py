"""Claude AI provider using Anthropic SDK."""
import json
import os

import anthropic

from .provider import AIProvider, CrawlPlan, ScoredUrl

_PLAN_SYSTEM = """You are a web crawling strategist. Given a goal and seed URLs, produce a JSON crawl plan.
Return ONLY valid JSON with this structure:
{
  "summary": "...",
  "prioritized_seeds": [{"url": "...", "score": 0.9, "reason": "..."}],
  "avoid_patterns": ["/login", "/cart"],
  "focus_patterns": ["/pricing", "/product"],
  "prefer_external": false
}
Set "prefer_external" to true ONLY if the seed site is a link aggregator (e.g. Hacker News, Reddit, Lobsters) where the valuable content lives on external domains. For blogs, documentation, wikis, and other content sites, set it to false."""

_SUMMARIZE_SYSTEM = """You summarize web pages in the context of a specific crawl goal.
Given a goal, URL, and page text, produce a 2-3 sentence summary focused on relevance to the goal.
If the page is not relevant, say so briefly."""

_EXTRACTION_SYSTEM = """You generate CSS extraction schemas for structured data extraction from web pages.
Given a URL, a description of what data to extract, and the actual page HTML, produce a JSON schema compatible with crawl4ai's JsonCssExtractionStrategy.

IMPORTANT: Use the provided HTML to identify the real CSS selectors, classes, and structure. Do NOT guess — base your selectors on the actual DOM.

Return ONLY valid JSON with this structure:
{
  "name": "extracted_data",
  "baseSelector": "css selector for repeating container element",
  "fields": [
    {"name": "field_name", "selector": "css selector relative to base", "type": "text"},
    {"name": "field_name", "selector": "css selector", "type": "attribute", "attribute": "href"}
  ]
}

Field types: "text" (innerText), "attribute" (specific HTML attribute), "html" (innerHTML).
Use semantic, descriptive field names. The baseSelector should target the repeating row/item element."""


class ClaudeProvider:
    def __init__(self, api_key: str | None = None):
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )

    def plan(self, goal: str, seed_urls: list[str], max_depth: int) -> CrawlPlan:
        prompt = (
            f"Goal: {goal}\n"
            f"Seed URLs: {json.dumps(seed_urls)}\n"
            f"Max depth: {max_depth}\n\n"
            "Produce the crawl plan JSON."
        )
        response = self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_PLAN_SYSTEM,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + response.content[0].text
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return CrawlPlan(summary="AI plan unavailable", prioritized_seeds=[
                ScoredUrl(url=u, score=0.5) for u in seed_urls
            ])
        return CrawlPlan(
            summary=data.get("summary", ""),
            prioritized_seeds=[
                ScoredUrl(
                    url=s["url"],
                    score=float(s.get("score", 0.5)),
                    reason=s.get("reason", ""),
                )
                for s in data.get("prioritized_seeds", [])
            ],
            avoid_patterns=data.get("avoid_patterns", []),
            focus_patterns=data.get("focus_patterns", []),
            prefer_external=bool(data.get("prefer_external", False)),
        )

    def summarize(self, goal: str, url: str, text: str) -> str:
        prompt = f"Goal: {goal}\nURL: {url}\n\nPage text:\n{text}"
        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                system=_SUMMARIZE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception:
            return ""

    def generate_extraction_schema(self, goal: str, url: str, description: str, html: str = "") -> dict:
        parts = [
            f"Goal: {goal}",
            f"URL: {url}",
            f"Extract: {description}",
        ]
        if html:
            # Truncate HTML to avoid token limits
            truncated = html[:15_000]
            parts.append(f"\nPage HTML:\n{truncated}")
        parts.append("\nProduce the extraction schema JSON.")
        prompt = "\n".join(parts)
        response = self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_EXTRACTION_SYSTEM,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + response.content[0].text
        return json.loads(raw)
