# Usage Guide

## Interactive CLI

The CLI is a persistent interactive session — set your goal once, crawl multiple sites, inspect and export results, all without re-specifying flags.

```bash
pip install -r app/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # or GEMINI_API_KEY for Gemini
python cli.py
```

```
╭─────────────────────────────────────────────────────────────╮
│  Leads Crawler  ·  type /help for commands                  │
╰─────────────────────────────────────────────────────────────╯

you   /goal Find pricing pages for DevTools SaaS companies
      ✓ Goal set: Find pricing pages for DevTools SaaS companies

you   /crawl https://example.com https://another.com

      Planning with CLAUDE...
      AI plan: Focusing on /pricing and /plans, avoiding /blog

      ✓ [   1] depth=0  https://example.com
      ✓ [   2] depth=1  https://example.com/pricing
      ✗ [   3] depth=1  https://example.com/login  (fetch_failed)
      ...
      Completed: 47 pages crawled, 3 errors

you   /results 5

      1.  https://example.com/pricing          score=0.95
          Simple, transparent pricing for teams of all sizes...

      2.  https://another.com/plans            score=0.87
          Choose the plan that works for you...

you   /export leads.csv
      ✓ Saved 44 results → leads.csv

you   /quit
      Bye!
```

### Commands

| Command | Description |
|---------|-------------|
| `/goal <text>` | Set the crawl goal (natural language) |
| `/crawl <url> [url…]` | Start a crawl against one or more seed URLs |
| `/status` | Show whether a crawl is active |
| `/results [n]` | Show top n results sorted by relevance score (default 10) |
| `/export [file]` | Save results to CSV (default: `results.csv`) |
| `/config` | Show current settings |
| `/set <key> <value>` | Change a setting (see table below) |
| `/clear` | Clear the screen |
| `/help` | Show command list |
| `/quit` | Exit |

### Settings (`/set`)

| Key | Default | Type | Description |
|-----|---------|------|-------------|
| `provider` | `claude` | `claude` \| `gemini` | AI provider |
| `max-pages` | `200` | int | Stop after N pages |
| `max-depth` | `3` | int | Max link depth from seed URLs |
| `threads` | `4` | int | Concurrent crawler threads |
| `rps` | `1.0` | float | Max requests/sec per domain |
| `min-delay` | `1.0` | float | Min random delay between requests (sec) |
| `max-delay` | `3.0` | float | Max random delay between requests (sec) |
| `robots` | `on` | `on` \| `off` | Respect robots.txt |

### Tips

- **Tab completion** — type `/` then press Tab to see all commands
- **Command history** — use ↑ / ↓ to navigate previous commands
- **Ctrl+C during a crawl** — stops the engine and returns you to the prompt cleanly
- **State persists** — `/results` and `/export` work on the last crawl without re-running it

---

## HTTP Server (for integrations)

If you need a REST API with real-time SSE streaming:

```bash
# Via Docker
docker-compose up
```

Or locally:

```bash
pip install -r app/requirements.txt
python app/app.py
```

Server runs at `http://localhost:8000`.

### Start a crawl

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
# → { "job_id": "abc-123", "status": "pending" }
```

### Check status

```bash
curl http://localhost:8000/api/v1/jobs/abc-123
```

Status progresses: `pending → planning → running → completed`

### Stream progress live

```bash
curl -N http://localhost:8000/api/v1/jobs/abc-123/stream
# data: {"event": "status", "status": "planning"}
# data: {"event": "plan", "summary": "Focusing on /pricing ..."}
# data: {"event": "page", "url": "https://...", "depth": 1, "pages_done": 42}
# data: {"event": "done", "status": "completed"}
```

### Get results (paginated)

```bash
curl "http://localhost:8000/api/v1/jobs/abc-123/results?page=1&per_page=50"
```

### Cancel

```bash
curl -X DELETE http://localhost:8000/api/v1/jobs/abc-123
```

### API reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/jobs` | Start a crawl |
| `GET` | `/api/v1/jobs` | List all jobs |
| `GET` | `/api/v1/jobs/{id}` | Job detail + AI plan |
| `DELETE` | `/api/v1/jobs/{id}` | Cancel job |
| `GET` | `/api/v1/jobs/{id}/results` | Paginated crawled pages |
| `GET` | `/api/v1/jobs/{id}/stream` | SSE real-time events |
