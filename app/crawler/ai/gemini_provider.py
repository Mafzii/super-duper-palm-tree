"""Gemini AI provider using google-genai SDK."""
import json
import os

from google import genai
from google.genai import types

from .provider import AIProvider, CrawlPlan, ScoredUrl

_PLAN_PROMPT_TEMPLATE = """You are a web crawling strategist. Given a goal and seed URLs, produce a JSON crawl plan.
Return ONLY valid JSON with this structure:
{{
  "summary": "...",
  "prioritized_seeds": [{{"url": "...", "score": 0.9, "reason": "..."}}],
  "avoid_patterns": ["/login", "/cart"],
  "focus_patterns": ["/pricing", "/product"]
}}

Goal: {goal}
Seed URLs: {seed_urls}
Max depth: {max_depth}"""

_RERANK_PROMPT_TEMPLATE = """You are a URL relevance ranker. Given a goal and list of URLs, score each URL 0.0-1.0.
Return ONLY valid JSON array:
[{{"url": "...", "score": 0.85, "reason": "..."}}]

Goal: {goal}
Context: {context_summary}
URLs to rank: {urls}"""

_SUMMARIZE_PROMPT_TEMPLATE = """You summarize web pages in the context of a specific crawl goal.
Given a goal, URL, and page text, produce a 2-3 sentence summary focused on relevance to the goal.
If the page is not relevant, say so briefly.

Goal: {goal}
URL: {url}

Page text:
{text}"""

_MODEL = "gemini-2.5-flash"


class GeminiProvider:
    def __init__(self, api_key: str | None = None):
        self._client = genai.Client(
            api_key=api_key or os.environ.get("GEMINI_API_KEY"),
        )

    def plan(self, goal: str, seed_urls: list[str], max_depth: int) -> CrawlPlan:
        prompt = _PLAN_PROMPT_TEMPLATE.format(
            goal=goal,
            seed_urls=json.dumps(seed_urls),
            max_depth=max_depth,
        )
        try:
            response = self._client.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(response.text)
        except Exception:
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
        prompt = _RERANK_PROMPT_TEMPLATE.format(
            goal=goal,
            context_summary=context_summary,
            urls=json.dumps(urls),
        )
        try:
            response = self._client.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(response.text)
        except Exception:
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

    def summarize(self, goal: str, url: str, text: str) -> str:
        prompt = _SUMMARIZE_PROMPT_TEMPLATE.format(
            goal=goal, url=url, text=text[:4000]
        )
        response = self._client.models.generate_content(
            model=_MODEL,
            contents=prompt,
        )
        return response.text.strip()
