# super-duper-palm-tree

AI-powered multithreaded web crawler for lead generation. Give it a goal and seed URLs — it uses Claude or Gemini to plan the crawl, prioritize links, and continuously rerank the queue based on relevance.

## Features

- **AI-directed crawling** — Claude Sonnet (or Gemini 1.5 Pro) generates a crawl plan with seed priorities and URL patterns to focus on or avoid
- **Continuous reranking** — every 50 URLs buffered, Claude Haiku (or Gemini Flash) rescores the queue so the most relevant pages are fetched first
- **Multithreaded** — configurable thread count with one HTTP client per thread to avoid connection pool contention
- **Rate limiting** — per-domain token bucket keeps you within polite RPS limits
- **robots.txt respected** — cached with 24h TTL, can be disabled

---

## Usage

See **[USAGE.md](USAGE.md)** for the full guide — interactive CLI, all slash commands, settings, and the HTTP server API reference.
