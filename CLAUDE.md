# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Flask web application (leads crawler) containerized with Docker. Currently minimal — single endpoint placeholder awaiting crawler implementation.

## Running the Application

**Via Docker (recommended):**
```bash
docker-compose up
```
App will be available at `http://localhost:8000`.

**Locally:**
```bash
pip install flask
python app/app.py
```

## Architecture

- `app/app.py` — Flask entry point, runs on `0.0.0.0:8000`
- `app/requirements.txt` — Python dependencies
- `app/Dockerfile` — Uses `python:3.13-alpine`, installs deps, runs app
- `docker-compose.yaml` — Orchestrates the web service, maps port 8000

All application code lives under `app/`.
