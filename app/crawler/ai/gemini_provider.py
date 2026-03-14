"""Gemini AI provider using google-generativeai SDK."""
import json
import os

import google.generativeai as genai

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


class GeminiProvider:
    def __init__(self, api_key: str | None = None):
        genai.configure(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
        self._plan_model = genai.GenerativeModel(
            "gemini-1.5-pro",
            generation_config={"response_mime_type": "application/json"},
        )
        self._rerank_model = genai.GenerativeModel(
            "gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"},
        )

    def plan(self, goal: str, seed_urls: list[str], max_depth: int) -> CrawlPlan:
        prompt = _PLAN_PROMPT_TEMPLATE.format(
            goal=goal,
            seed_urls=json.dumps(seed_urls),
            max_depth=max_depth,
        )
        try:
            response = self._plan_model.generate_content(prompt)
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
            response = self._rerank_model.generate_content(prompt)
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
