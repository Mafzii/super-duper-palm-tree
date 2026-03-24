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
  "focus_patterns": ["/pricing", "/product"],
  "prefer_external": false
}}
Set "prefer_external" to true ONLY if the seed site is a link aggregator (e.g. Hacker News, Reddit, Lobsters) where the valuable content lives on external domains. For blogs, documentation, wikis, and other content sites, set it to false.

Goal: {goal}
Seed URLs: {seed_urls}
Max depth: {max_depth}"""

_SUMMARIZE_PROMPT_TEMPLATE = """You summarize web pages in the context of a specific crawl goal.
Given a goal, URL, and page text, produce a 2-3 sentence summary focused on relevance to the goal.
If the page is not relevant, say so briefly.

Goal: {goal}
URL: {url}

Page text:
{text}"""

_EXTRACTION_PROMPT_TEMPLATE = """You generate CSS extraction schemas for structured data extraction from web pages.
Given a URL, a description of what data to extract, and the actual page HTML, produce a JSON schema compatible with crawl4ai's JsonCssExtractionStrategy.

IMPORTANT: Use the provided HTML to identify the real CSS selectors, classes, and structure. Do NOT guess — base your selectors on the actual DOM.

Return ONLY valid JSON with this structure:
{{
  "name": "extracted_data",
  "baseSelector": "css selector for repeating container element",
  "fields": [
    {{"name": "field_name", "selector": "css selector relative to base", "type": "text"}},
    {{"name": "field_name", "selector": "css selector", "type": "attribute", "attribute": "href"}}
  ]
}}

Field types: "text" (innerText), "attribute" (specific HTML attribute), "html" (innerHTML).
Use semantic, descriptive field names. The baseSelector should target the repeating row/item element.

Goal: {goal}
URL: {url}
Extract: {description}
{{html_section}}"""

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
            prefer_external=bool(data.get("prefer_external", False)),
        )

    def summarize(self, goal: str, url: str, text: str) -> str:
        prompt = _SUMMARIZE_PROMPT_TEMPLATE.format(
            goal=goal, url=url, text=text
        )
        response = self._client.models.generate_content(
            model=_MODEL,
            contents=prompt,
        )
        return response.text.strip()

    def generate_extraction_schema(self, goal: str, url: str, description: str, html: str = "") -> dict:
        html_section = ""
        if html:
            html_section = f"\nPage HTML:\n{html[:15_000]}"
        prompt = _EXTRACTION_PROMPT_TEMPLATE.format(
            goal=goal, url=url, description=description,
            html_section=html_section,
        )
        response = self._client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        return json.loads(response.text)
