# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered web crawler for lead generation. Uses crawl4ai (headless Chrome) for crawling and Claude or Gemini for intelligent crawl planning and content summarization. Two interfaces: REST API (Flask) and interactive CLI.

## Running the Application

**REST API via Docker (recommended):**
```bash
docker-compose up
```
App will be available at `http://localhost:8000`. Requires `ANTHROPIC_API_KEY` and/or `GEMINI_API_KEY` env vars.

**REST API locally:**
```bash
pip install -r app/requirements.txt
python app/app.py
```

**CLI:**
```bash
pip install -r app/requirements.txt
python cli.py
```

## Architecture

- `app/app.py` — Flask REST API with job CRUD, paginated results, and SSE streaming
- `app/crawler/crawl4ai_engine.py` — Core crawl orchestrator using crawl4ai's AsyncWebCrawler with BFS strategy and BM25 content filtering
- `app/crawler/job_manager.py` — In-memory job registry with thread-safe lifecycle management
- `app/crawler/worker.py` — `PageResult` dataclass
- `app/crawler/ai/provider.py` — `AIProvider` protocol and `CrawlPlan`/`ScoredUrl` dataclasses
- `app/crawler/ai/claude_provider.py` — Claude integration (sonnet for planning, haiku for summarization)
- `app/crawler/ai/gemini_provider.py` — Gemini integration (2.5-flash for both)
- `cli.py` — Interactive REPL with slash commands
- `app/Dockerfile` — Uses `python:3.13-slim`, runs with gunicorn (1 worker, 4 threads)
- `docker-compose.yaml` — Orchestrates the web service, maps port 8000, passes API keys

All application code lives under `app/`. The CLI entry point is `cli.py` at the repo root.
