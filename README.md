# super-duper-palm-tree

AI-powered multithreaded web crawler for lead generation. Give it a goal and seed URLs — it uses Claude or Gemini to plan the crawl, prioritize links, and continuously rerank the queue based on relevance.

## Features

- **AI-directed crawling** — Claude Sonnet (or Gemini 1.5 Pro) generates a crawl plan with seed priorities and URL patterns to focus on or avoid
- **Continuous reranking** — every 50 URLs buffered, Claude Haiku (or Gemini Flash) rescores the queue so the most relevant pages are fetched first
- **Multithreaded** — configurable thread count with one HTTP client per thread to avoid connection pool contention
- **Rate limiting** — per-domain token bucket keeps you within polite RPS limits
- **robots.txt respected** — cached with 24h TTL, can be disabled
- **Real-time SSE stream** — watch crawl progress live without polling
- **Paginated results** — results endpoint returns crawled pages with AI relevance scores

## Quick start

```bash
# 1. Set your AI key
export ANTHROPIC_API_KEY=sk-ant-...   # or GEMINI_API_KEY for Gemini

# 2. Start the server
docker-compose up
```

The API is available at `http://localhost:8000`.

## Start a crawl

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Find pricing pages for DevTools SaaS companies",
    "seed_urls": ["https://example.com"],
    "max_depth": 3,
    "max_pages": 200,
    "thread_count": 4,
    "ai_provider": "claude"
  }'
```

Response:
```json
{ "job_id": "abc-123", "status": "pending" }
```

## Check status

```bash
curl http://localhost:8000/api/v1/jobs/abc-123
```

Status progresses: `pending → planning → running → completed`

The response includes `ai_plan` once the planning phase finishes — the AI's summary, prioritized seed scores, and URL patterns it chose to focus on or avoid.

## Stream progress live

```bash
curl -N http://localhost:8000/api/v1/jobs/abc-123/stream
```

Emits SSE events:
```
data: {"event": "status", "status": "planning"}
data: {"event": "plan", "summary": "Focusing on /pricing and /plans paths..."}
data: {"event": "page", "url": "https://...", "depth": 1, "pages_done": 42}
data: {"event": "done", "status": "completed"}
```

## Get results

```bash
curl "http://localhost:8000/api/v1/jobs/abc-123/results?page=1&per_page=50"
```

Each result includes `url`, `depth`, `text_snippet`, `links_count`, and `score`.

## Cancel a crawl

```bash
curl -X DELETE http://localhost:8000/api/v1/jobs/abc-123
```

## All POST options

| Field | Default | Description |
|-------|---------|-------------|
| `goal` | required | Natural language description of what you're looking for |
| `seed_urls` | required | List of starting URLs |
| `ai_provider` | `"claude"` | `"claude"` or `"gemini"` |
| `max_depth` | `3` | Max link depth from seed URLs |
| `max_pages` | `500` | Stop after this many pages crawled |
| `thread_count` | `8` | Concurrent crawler threads |
| `rate_limit_rps` | `1.0` | Requests per second per domain |
| `min_delay_seconds` | `1.0` | Minimum random delay between requests |
| `max_delay_seconds` | `3.0` | Maximum random delay between requests |
| `respect_robots` | `true` | Whether to check robots.txt |

## Running locally (no Docker)

```bash
pip install -r app/requirements.txt
ANTHROPIC_API_KEY=sk-ant-... python app/app.py
```

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/jobs` | Start a crawl |
| `GET` | `/api/v1/jobs` | List all jobs |
| `GET` | `/api/v1/jobs/{id}` | Job detail + AI plan |
| `DELETE` | `/api/v1/jobs/{id}` | Cancel job |
| `GET` | `/api/v1/jobs/{id}/results` | Paginated crawled pages |
| `GET` | `/api/v1/jobs/{id}/stream` | SSE real-time events |
