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
  "focus_patterns": ["/pricing", "/product"]
}"""

_RERANK_SYSTEM = """You are a URL relevance ranker. Given a goal and list of URLs, score each URL 0.0-1.0 for relevance.
Return ONLY valid JSON array:
[{"url": "...", "score": 0.85, "reason": "..."}]"""


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
        )

    def rerank(
        self, goal: str, urls: list[str], context_summary: str
    ) -> list[ScoredUrl]:
        prompt = (
            f"Goal: {goal}\n"
            f"Context: {context_summary}\n"
            f"URLs to rank: {json.dumps(urls)}\n\n"
            "Return the scored JSON array."
        )
        response = self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_RERANK_SYSTEM,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "["},
            ],
        )
        raw = "[" + response.content[0].text
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return [ScoredUrl(url=u, score=0.5) for u in urls]
        return [
            ScoredUrl(
                url=item["url"],
                score=float(item.get("score", 0.5)),
                reason=item.get("reason", ""),
            )
            for item in data
            if "url" in item
        ]
