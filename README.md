# super-duper-palm-tree

AI-powered web crawler for lead generation. Give it a goal and seed URLs — it uses Claude or Gemini to plan the crawl, prioritize links, and filter content by relevance.

## Features

- **AI-directed crawling** — Claude Sonnet or Gemini 2.5 Flash generates a crawl plan with seed priorities and URL patterns to focus on or avoid
- **Browser-based crawling** — uses crawl4ai with headless Chrome for JavaScript-rendered pages
- **BM25 content filtering** — extracts the most relevant text from each page based on the crawl goal
- **URL scoring** — prioritizes links matching focus patterns; supports aggregator mode (prefer external links for sites like HN/Reddit)
- **Real-time streaming** — SSE endpoint for live crawl progress
- **Dual interface** — interactive CLI for local use, REST API for integrations

---

## Usage

See **[USAGE.md](USAGE.md)** for the full guide — interactive CLI, all slash commands, settings, and the HTTP server API reference.
