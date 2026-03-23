#!/usr/bin/env python3
"""Interactive CLI for the AI-powered leads crawler."""
import csv
import json
import os
import readline
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Allow imports from app/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

# ── persistence paths ────────────────────────────────────────────────────────
_DATA_DIR = Path.home() / ".crawler"
_CONFIG_FILE = _DATA_DIR / "config.json"
_RESULTS_FILE = _DATA_DIR / "results.jsonl"
_INITIALIZED_FILE = _DATA_DIR / ".initialized"

from crawler.ai.claude_provider import ClaudeProvider
from crawler.ai.gemini_provider import GeminiProvider
from crawler.crawl4ai_engine import Crawl4AIEngine
from crawler.worker import PageResult

# ── terminal colours (graceful fallback if not a tty) ─────────────────────────
def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

BOLD   = lambda t: _c("1", t)
GREEN  = lambda t: _c("32", t)
YELLOW = lambda t: _c("33", t)
CYAN   = lambda t: _c("36", t)
DIM    = lambda t: _c("2", t)
RED    = lambda t: _c("31", t)


@dataclass
class Session:
    goal: str = ""
    config: dict = field(default_factory=lambda: {
        "provider":           "gemini",
        "max_depth":          1,
        "max_pages":          20,
        "min_delay":          1.0,
        "max_delay":          3.0,
        "strategy":           "bfs",
        "filter":             "bm25",
        "bm25_threshold":     1.2,
        "cache":              "bypass",
        "stealth":            False,
        "headless":           True,
        "score_threshold":    0.0,
        "include_external":   True,
    })
    results: list = field(default_factory=list)  # list[PageResult]
    last_plan: object = None                      # CrawlPlan | None
    active_engine: object = None                  # Crawl4AIEngine | None


# ── /set key aliases ──────────────────────────────────────────────────────────
_SET_KEYS = {
    "provider":          ("provider",         str),
    "max-pages":         ("max_pages",        int),
    "max-depth":         ("max_depth",        int),
    "min-delay":         ("min_delay",        float),
    "max-delay":         ("max_delay",        float),
    "strategy":          ("strategy",         str),
    "filter":            ("filter",           str),
    "bm25-threshold":    ("bm25_threshold",   float),
    "cache":             ("cache",            str),
    "stealth":           ("stealth",          str),   # parsed as bool
    "headless":          ("headless",         str),   # parsed as bool
    "score-threshold":   ("score_threshold",  float),
    "include-external":  ("include_external", str),   # parsed as bool
}

_COMMANDS = [
    "/goal", "/crawl", "/fetch", "/scrape", "/screenshot", "/plan",
    "/results", "/export", "/config", "/set", "/reset", "/clear",
    "/help", "/quit", "/exit",
]

# ── Validation rules ──────────────────────────────────────────────────────────
_VALID_PROVIDERS = ("claude", "gemini")
_VALID_STRATEGIES = ("bfs", "bestfirst", "dfs")
_VALID_FILTERS = ("bm25", "pruning", "none")
_VALID_CACHE = ("enabled", "bypass")
_BOOL_TRUE = ("true", "1", "yes")
_BOOL_FALSE = ("false", "0", "no")


def _parse_bool(raw: str) -> bool:
    low = raw.lower()
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    raise ValueError(f"expected true/false, got '{raw}'")


class REPL:
    def __init__(self) -> None:
        self.session = Session()
        self._hints_shown: set[str] = set()

    # ── persistence ─────────────────────────────────────────────────────────
    def _load_config(self) -> None:
        """Load config from disk, merging into session defaults."""
        try:
            data = json.loads(_CONFIG_FILE.read_text())
            for k, v in data.items():
                if k in self.session.config:
                    self.session.config[k] = v
        except Exception:
            pass

    def _save_config(self) -> None:
        """Persist current config to disk."""
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            _CONFIG_FILE.write_text(json.dumps(self.session.config, indent=2))
        except Exception:
            pass

    def _append_result(self, r: "PageResult") -> None:
        """Append one result as a JSON line to the results file."""
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            entry = {
                "url": r.url,
                "depth": r.depth,
                "score": r.score,
                "title": r.title,
                "summary": r.summary,
                "error": r.error,
                "links_count": len(r.links),
                "text_snippet": (r.text[:500] if r.text else ""),
                "status_code": r.status_code,
                "extracted_content": r.extracted_content,
            }
            with open(_RESULTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _load_results(self) -> None:
        """Load persisted results from JSONL file."""
        if not _RESULTS_FILE.exists():
            return
        loaded = []
        try:
            for line in _RESULTS_FILE.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    loaded.append(PageResult(
                        url=d.get("url", ""),
                        depth=d.get("depth", 0),
                        text=d.get("text_snippet", ""),
                        score=d.get("score", 0.0),
                        error=d.get("error", ""),
                        summary=d.get("summary", ""),
                        extracted_content=d.get("extracted_content", ""),
                        title=d.get("title", ""),
                        status_code=d.get("status_code", 0),
                    ))
                except Exception:
                    continue
        except Exception:
            return
        if loaded:
            self.session.results = loaded
            self._out(DIM(f"Restored {len(loaded)} results from previous session"))

    # ── provider auto-detect ──────────────────────────────────────────────
    def _detect_provider(self) -> str:
        """Auto-detect provider from env. Returns status string for banner."""
        has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
        has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))

        if has_gemini and has_claude:
            return f"{self.session.config['provider']} ✓"
        elif has_gemini:
            self.session.config["provider"] = "gemini"
            self._save_config()
            return "gemini ✓"
        elif has_claude:
            self.session.config["provider"] = "claude"
            self._save_config()
            return "claude ✓"
        else:
            return YELLOW("no API key")

    # ── interactive prompting ─────────────────────────────────────────────
    def _ensure_goal(self) -> bool:
        """Prompt for goal if not set. Returns True if goal is now set."""
        if self.session.goal:
            return True
        # Disable completer during goal input
        old_completer = readline.get_completer()
        readline.set_completer(None)
        try:
            text = input(f"      {YELLOW('Goal not set.')} Enter your crawl goal: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            readline.set_completer(old_completer)
            return False
        readline.set_completer(old_completer)
        text = text.strip('"').strip("'")
        if not text:
            self._err("Goal cannot be empty.")
            return False
        self.session.goal = text
        self._ok(f"Goal set: {DIM(text)}")
        return True

    def _confirm(self, prompt: str) -> bool:
        """Ask user for y/N confirmation."""
        try:
            answer = input(f"      {YELLOW(prompt)} [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return answer in ("y", "yes")

    # ── hints ─────────────────────────────────────────────────────────────
    def _hint(self, key: str, text: str) -> None:
        """Show a one-time contextual hint."""
        if key not in self._hints_shown:
            self._hints_shown.add(key)
            self._out(DIM(text))

    # ── error formatting ──────────────────────────────────────────────────
    @staticmethod
    def _format_error(error: str) -> str:
        """Map common error codes to human-readable text."""
        _MAP = {
            "403": "forbidden",
            "404": "not found",
            "429": "rate limited",
            "500": "server error",
            "503": "service unavailable",
            "timeout": "timed out",
            "fetch_failed": "connection failed",
        }
        for code, label in _MAP.items():
            if code in error.lower():
                return label
        return error

    # ── readline tab completion ───────────────────────────────────────────────
    def complete(self, text: str, state: int):
        options = [c for c in _COMMANDS if c.startswith(text)]
        return options[state] if state < len(options) else None

    # ── main loop ─────────────────────────────────────────────────────────────
    def run(self) -> None:
        readline.set_completer(self.complete)
        readline.set_completer_delims(" ")
        readline.parse_and_bind("tab: complete")

        self._load_config()
        self._load_results()
        provider_status = self._detect_provider()

        print(f"\n{BOLD('╭─────────────────────────────────────────────────────────────╮')}")
        print(f"{BOLD('│')}  {CYAN('Leads Crawler')}  ·  type {BOLD('/help')} for commands                  {BOLD('│')}")
        print(f"{BOLD('│')}  Provider: {provider_status:<50}{BOLD('│')}")
        print(f"{BOLD('╰─────────────────────────────────────────────────────────────╯')}\n")

        # First-run onboarding
        if not _INITIALIZED_FILE.exists():
            print(f"  {BOLD('Quick start:')}")
            print(f'    1. /goal "find SaaS companies with pricing pages"')
            print(f"    2. /crawl https://example.com")
            print(f"    3. /results to see what was found")
            print(f"    4. /export results.csv")
            print()
            try:
                _DATA_DIR.mkdir(parents=True, exist_ok=True)
                _INITIALIZED_FILE.write_text("")
            except Exception:
                pass

        while True:
            try:
                line = input(f"{BOLD('you')}   ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            self.dispatch(line)

    # ── dispatch ──────────────────────────────────────────────────────────────
    def dispatch(self, line: str) -> None:
        if not line.startswith("/"):
            print(f"      {YELLOW('Commands start with /')}  — type {BOLD('/help')} for a list.\n")
            return

        parts = line.split(None, 1)
        cmd   = parts[0].lower()
        rest  = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/goal":       self.cmd_goal,
            "/crawl":      self.cmd_crawl,
            "/fetch":      self.cmd_fetch,
            "/scrape":     self.cmd_scrape,
            "/screenshot": self.cmd_screenshot,
            "/plan":       self.cmd_plan,
            "/results":    self.cmd_results,
            "/export":     self.cmd_export,
            "/config":     self.cmd_config,
            "/set":        self.cmd_set,
            "/reset":      self.cmd_reset,
            "/clear":      self.cmd_clear,
            "/help":       self.cmd_help,
            "/quit":       self.cmd_quit,
            "/exit":       self.cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler is None:
            print(f"      {RED('Unknown command:')} {cmd}  — type {BOLD('/help')} for a list.\n")
        else:
            handler(rest)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _out(self, text: str) -> None:
        """Print an indented output line."""
        print(f"      {text}")

    def _ok(self, text: str) -> None:
        self._out(f"{GREEN('✓')} {text}")

    def _err(self, text: str) -> None:
        self._out(f"{RED('✗')} {text}")

    def _get_ai_provider(self):
        """Build an AI provider from current config."""
        name = self.session.config["provider"]
        return GeminiProvider() if name == "gemini" else ClaudeProvider()

    def _check_api_key(self) -> bool:
        """Check that the required API key is set. Returns True if OK."""
        provider_name = self.session.config["provider"]
        if provider_name == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
            self._err("ANTHROPIC_API_KEY environment variable not set")
            print()
            return False
        if provider_name == "gemini" and not os.environ.get("GEMINI_API_KEY"):
            self._err("GEMINI_API_KEY environment variable not set")
            print()
            return False
        return True

    def _build_engine(self, goal: str, seed_urls: list[str], ai, **overrides) -> Crawl4AIEngine:
        """Build a Crawl4AIEngine from current session config."""
        cfg = self.session.config
        return Crawl4AIEngine(
            job_id="cli",
            goal=goal,
            seed_urls=seed_urls,
            ai_provider=ai,
            max_depth=cfg["max_depth"],
            max_pages=cfg["max_pages"],
            min_delay=cfg["min_delay"],
            max_delay=cfg["max_delay"],
            strategy=cfg["strategy"],
            content_filter=cfg["filter"],
            bm25_threshold=cfg["bm25_threshold"],
            cache_mode=cfg["cache"],
            stealth=cfg["stealth"],
            headless=cfg["headless"],
            score_threshold=cfg["score_threshold"],
            include_external=cfg["include_external"],
            **overrides,
        )

    # ── command handlers ──────────────────────────────────────────────────────
    def cmd_goal(self, args: str) -> None:
        text = args.strip().strip('"').strip("'")
        if not text:
            self._err("Usage: /goal <text>")
        else:
            self.session.goal = text
            self._ok(f"Goal set: {DIM(text)}")
            self._hint("after_goal", "Tip: now run /crawl <url> or /plan <url>")
        print()

    def cmd_crawl(self, args: str) -> None:
        urls = args.split()
        if not urls:
            self._err("Usage: /crawl <url> [url...]")
            print()
            return
        if not self._ensure_goal():
            print()
            return
        if not self._check_api_key():
            return

        cfg = self.session.config
        provider_name = cfg["provider"]
        ai = self._get_ai_provider()

        page_results: list[PageResult] = []
        t_start = time.time()

        def on_status(s: str) -> None:
            if s == "planning":
                self._out(f"{BOLD('Planning')} with {provider_name.upper()}...")
            elif s == "running":
                self._out(f"{GREEN('Running')} — press Ctrl+C to stop early\n")
            elif s == "completed":
                elapsed = time.time() - t_start
                self._out(f"\n{GREEN('Completed')} in {elapsed:.1f}s")
            elif s == "cancelled":
                elapsed = time.time() - t_start
                self._out(f"\n{YELLOW('Cancelled')} after {elapsed:.1f}s")

        def on_page(r: PageResult) -> None:
            page_results.append(r)
            self._append_result(r)
            n = len(page_results)
            if r.error:
                sym   = RED("✗")
                label = DIM(r.url[:80])
                extra = f"  {DIM('(' + self._format_error(r.error) + ')')}"
            else:
                sym   = GREEN("✓")
                label = r.url[:80]
                extra = ""
            self._out(f"{sym} [{n:>3}] depth={r.depth} score={r.score:.2f}  {label}{extra}")

        def on_sse(event: dict) -> None:
            if event.get("event") == "plan":
                summary = event.get("summary", "")
                if summary:
                    self._out(f"{CYAN('AI plan')}: {summary}\n")
            elif event.get("event") == "plan_error":
                self._out(f"{YELLOW('AI planning failed')}: {event.get('error', 'unknown')} — crawling without plan\n")

        engine = self._build_engine(self.session.goal, urls, ai,
                                    on_status_change=on_status,
                                    on_page_done=on_page,
                                    on_sse_event=on_sse)
        self.session.active_engine = engine

        try:
            engine.start()
        except KeyboardInterrupt:
            engine.stop()
            self._out(f"{YELLOW('Stopping...')}")
            time.sleep(1)
        finally:
            self.session.active_engine = None

        # Store AI plan for /plan command
        if engine.ai_plan:
            self.session.last_plan = engine.ai_plan

        good = [r for r in page_results if not r.error]
        bad  = [r for r in page_results if r.error]
        self.session.results.extend(page_results)
        self._out(f"\n{BOLD(str(len(good)))} pages crawled, {len(bad)} errors")
        if len(self.session.results) > len(page_results):
            self._out(DIM(f"Session has {len(self.session.results)} results across crawls. /reset to clear."))
        self._hint("after_crawl", "Tip: /results to view, /export to save")
        print()

    def cmd_fetch(self, args: str) -> None:
        url = args.strip()
        if not url:
            self._err("Usage: /fetch <url>")
            print()
            return
        if not self._ensure_goal():
            print()
            return
        if not self._check_api_key():
            return

        ai = self._get_ai_provider()
        engine = self._build_engine(self.session.goal, [url], ai)

        self._out(f"{BOLD('Fetching')} {url}...")
        try:
            page = engine.fetch_page(url)
        except Exception as e:
            self._err(f"Fetch failed: {e}")
            print()
            return

        if page.error:
            self._err(f"Error: {page.error}")
            print()
            return

        # AI-summarize against current goal
        self._out(f"{DIM('Summarizing...')}")
        try:
            page.summary = ai.summarize(self.session.goal, page.url, page.text)
        except Exception:
            pass

        self.session.results.append(page)
        self._append_result(page)

        print()
        if page.title:
            self._out(f"{BOLD('Title')}: {page.title}")
        self._out(f"{BOLD('Score')}: {page.score:.2f}")
        self._out(f"{BOLD('Links')}: {len(page.links)}")
        if page.summary:
            self._out(f"{BOLD('Summary')}: {page.summary}")
        elif page.text:
            snippet = page.text[:200].replace("\n", " ")
            self._out(f"{BOLD('Text')}: {DIM(snippet)}")
        print()

    def cmd_scrape(self, args: str) -> None:
        # Parse: /scrape <url> "<description>"
        parts = args.strip().split(None, 1)
        if len(parts) < 2:
            self._err('Usage: /scrape <url> "<description>"')
            print()
            return
        url = parts[0]
        description = parts[1].strip().strip('"').strip("'")
        if not description:
            self._err('Usage: /scrape <url> "<description>"')
            print()
            return
        if not self._check_api_key():
            return

        goal = self.session.goal or description
        ai = self._get_ai_provider()
        engine = self._build_engine(goal, [url], ai)

        # Step 1: Fetch the page to get actual HTML
        self._out(f"{BOLD('Fetching')} {url}...")
        try:
            page, html = engine.fetch_page_with_html(url)
        except Exception as e:
            self._err(f"Fetch failed: {e}")
            print()
            return

        if page.error:
            self._err(f"Error: {page.error}")
            print()
            return

        if not html:
            self._err("No HTML content returned from page.")
            print()
            return

        # Step 2: AI generates extraction schema from actual HTML
        self._out(f"{BOLD('Generating')} extraction schema from page structure...")
        try:
            schema = ai.generate_extraction_schema(goal, url, description, html=html)
        except Exception as e:
            self._err(f"Schema generation failed: {e}")
            print()
            return

        self._out(f"{DIM('Schema')}: baseSelector={DIM(schema.get('baseSelector', '?'))}, "
                  f"{len(schema.get('fields', []))} fields")

        # Step 3: Re-fetch with the extraction strategy
        from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
        extraction = JsonCssExtractionStrategy(schema)

        engine2 = self._build_engine(goal, [url], ai, extraction_strategy=extraction)
        self._out(f"{BOLD('Extracting')} structured data...")

        try:
            page = engine2.fetch_page(url)
        except Exception as e:
            self._err(f"Extraction failed: {e}")
            print()
            return

        # Display extracted content
        print()
        if page.extracted_content:
            try:
                data = json.loads(page.extracted_content)
                formatted = json.dumps(data, indent=2, ensure_ascii=False)
                self._out(f"{BOLD('Extracted data')}:")
                for line in formatted.split("\n"):
                    self._out(f"  {line}")
            except json.JSONDecodeError:
                self._out(f"{BOLD('Extracted data')}:")
                self._out(f"  {page.extracted_content[:2000]}")
        else:
            self._out(f"{YELLOW('No structured data extracted.')} The page may not match the schema.")

        self.session.results.append(page)
        self._append_result(page)
        print()

    def cmd_screenshot(self, args: str) -> None:
        parts = args.strip().split()
        if not parts:
            self._err("Usage: /screenshot <url> [filename]")
            print()
            return

        url = parts[0]
        filename = parts[1] if len(parts) > 1 else "screenshot.png"
        if not filename.endswith(".png"):
            filename += ".png"

        ai = self._get_ai_provider()
        engine = self._build_engine(self.session.goal or "screenshot", [url], ai)

        self._out(f"{BOLD('Capturing')} {url}...")
        try:
            png_bytes = engine.screenshot_page(url)
        except Exception as e:
            self._err(f"Screenshot failed: {e}")
            print()
            return

        if not png_bytes:
            self._err("No screenshot data returned.")
            print()
            return

        with open(filename, "wb") as f:
            f.write(png_bytes)

        self._ok(f"Saved screenshot ({len(png_bytes):,} bytes) -> {filename}")
        print()

    def cmd_plan(self, args: str) -> None:
        urls = args.split()

        # If URLs provided, run AI planning without crawling
        if urls:
            if not self._ensure_goal():
                print()
                return
            if not self._check_api_key():
                return

            ai = self._get_ai_provider()
            cfg = self.session.config

            self._out(f"{BOLD('Planning')} with {cfg['provider'].upper()}...")
            try:
                plan = ai.plan(self.session.goal, urls, cfg["max_depth"])
            except Exception as e:
                self._err(f"Planning failed: {e}")
                print()
                return

            self.session.last_plan = plan
            self._display_plan(plan)
            return

        # No URLs — show last plan
        plan = self.session.last_plan
        if plan is None:
            self._out("No plan yet — run /plan <url> or /crawl first.")
            print()
            return
        self._display_plan(plan)

    def _display_plan(self, plan) -> None:
        print()
        self._out(f"{BOLD('Summary')}: {plan.summary}")
        if plan.focus_patterns:
            self._out(f"{CYAN('Focus')}: {', '.join(plan.focus_patterns)}")
        if plan.avoid_patterns:
            self._out(f"{CYAN('Avoid')}: {', '.join(plan.avoid_patterns)}")
        if plan.prefer_external:
            self._out(f"{CYAN('Mode')}: external-first (aggregator site)")
        if plan.prioritized_seeds:
            self._out(f"{BOLD('Seeds')}:")
            for s in plan.prioritized_seeds:
                reason = f"  {DIM(s.reason)}" if s.reason else ""
                self._out(f"  {s.score:.1f}  {s.url}{reason}")
        print()

    def cmd_results(self, args: str) -> None:
        # Parse arguments: /results [n] [--min-score <f>] [--sort score|depth]
        tokens = args.split()
        n = 10
        min_score = 0.0
        sort_by = "score"  # default sort by score descending

        i = 0
        while i < len(tokens):
            if tokens[i] == "--min-score" and i + 1 < len(tokens):
                try:
                    min_score = float(tokens[i + 1])
                except ValueError:
                    self._err(f"Invalid --min-score value: {tokens[i + 1]}")
                    print()
                    return
                i += 2
            elif tokens[i] == "--sort" and i + 1 < len(tokens):
                if tokens[i + 1] in ("score", "depth"):
                    sort_by = tokens[i + 1]
                else:
                    self._err(f"Invalid --sort value: {tokens[i + 1]} (use 'score' or 'depth')")
                    print()
                    return
                i += 2
            else:
                try:
                    n = int(tokens[i])
                except ValueError:
                    self._err("Usage: /results [n] [--min-score <f>] [--sort score|depth]")
                    print()
                    return
                i += 1

        # Deduplicate by URL, keeping first occurrence
        seen: dict[str, PageResult] = {}
        for r in self.session.results:
            if r.error:
                continue
            if r.url not in seen:
                seen[r.url] = r

        good = list(seen.values())

        # Filter by min score
        if min_score > 0:
            good = [r for r in good if r.score >= min_score]

        # Sort
        if sort_by == "score":
            good.sort(key=lambda r: r.score, reverse=True)
        elif sort_by == "depth":
            good.sort(key=lambda r: r.depth)

        good = good[:n]

        if not good:
            self._out("No results yet — run /crawl first.")
            print()
            return

        # Generate summaries on demand for results that don't have one
        needs_summary = [r for r in good if not r.summary and r.text]
        if needs_summary and self.session.goal:
            total_s = len(needs_summary)
            failed = 0
            try:
                ai = self._get_ai_provider()
            except Exception as e:
                self._err(f"Could not initialise AI provider: {e}")
                ai = None

            if ai:
                for idx, r in enumerate(needs_summary, 1):
                    self._out(DIM(f"Summarizing {idx}/{total_s}: {r.url[:70]}..."))
                    try:
                        r.summary = ai.summarize(self.session.goal, r.url, r.text)
                        if not r.summary:
                            failed += 1
                            self._out(DIM(f"  ⚠ empty summary for {r.url}"))
                    except Exception as e:
                        failed += 1
                        self._out(DIM(f"  ⚠ summary failed for {r.url}: {e}"))

                if failed == len(needs_summary):
                    self._err("All summaries failed — check your API key and provider config.")

        print()
        for i, r in enumerate(good, 1):
            self._out(f"{BOLD(f'{i}.')}  {CYAN(r.url)}")
            self._out(f"    score={BOLD(f'{r.score:.2f}')}  depth={r.depth}  links={len(r.links)}")
            if r.summary:
                self._out(f"    {r.summary}")
            elif r.text:
                snippet = r.text[:120].replace("\n", " ")
                self._out(f"    {DIM(snippet)}")
            print()
        self._hint("after_results", "Tip: /export results.json for JSON, /export results.md for Markdown")

    def cmd_export(self, args: str) -> None:
        path = args.strip() or "results.csv"
        good = [r for r in self.session.results if not r.error]
        if not good:
            self._err("No results to export.")
            print()
            return

        if os.path.exists(path):
            if not self._confirm(f"Overwrite {path}?"):
                print()
                return

        ext = os.path.splitext(path)[1].lower()

        if ext == ".json":
            self._export_json(path, good)
        elif ext == ".md":
            self._export_markdown(path, good)
        else:
            self._export_csv(path, good)

    def _export_csv(self, path: str, results: list[PageResult]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["url", "depth", "score", "links_count", "title", "summary", "text_snippet"]
            )
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "url":          r.url,
                    "depth":        r.depth,
                    "score":        r.score,
                    "links_count":  len(r.links),
                    "title":        r.title,
                    "summary":      r.summary,
                    "text_snippet": r.text[:500].replace("\n", " ") if r.text else "",
                })
        self._ok(f"Saved {len(results)} results -> {path}")
        print()

    def _export_json(self, path: str, results: list[PageResult]) -> None:
        data = []
        for r in results:
            entry = {
                "url": r.url,
                "depth": r.depth,
                "score": r.score,
                "title": r.title,
                "links_count": len(r.links),
                "links": r.links,
                "summary": r.summary,
                "text": r.text,
                "status_code": r.status_code,
            }
            if r.extracted_content:
                try:
                    entry["extracted_content"] = json.loads(r.extracted_content)
                except json.JSONDecodeError:
                    entry["extracted_content"] = r.extracted_content
            data.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._ok(f"Saved {len(results)} results -> {path}")
        print()

    def _export_markdown(self, path: str, results: list[PageResult]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Crawl Results\n\n")
            if self.session.goal:
                f.write(f"**Goal:** {self.session.goal}\n\n")
            f.write(f"**Total pages:** {len(results)}\n\n---\n\n")
            for i, r in enumerate(results, 1):
                title = r.title or r.url
                f.write(f"## {i}. {title}\n\n")
                f.write(f"- **URL:** {r.url}\n")
                f.write(f"- **Score:** {r.score:.2f}\n")
                f.write(f"- **Depth:** {r.depth}\n")
                f.write(f"- **Links:** {len(r.links)}\n\n")
                if r.summary:
                    f.write(f"{r.summary}\n\n")
                elif r.text:
                    f.write(f"{r.text[:500]}\n\n")
                f.write("---\n\n")
        self._ok(f"Saved {len(results)} results -> {path}")
        print()

    def cmd_config(self, _args: str) -> None:
        print()
        for k, v in self.session.config.items():
            self._out(f"  {CYAN(k):<18} {v}")
        if self.session.goal:
            self._out(f"  {CYAN('goal'):<18} {DIM(self.session.goal)}")
        print()

    def cmd_set(self, args: str) -> None:
        parts = args.split(None, 1)
        if len(parts) != 2:
            self._err("Usage: /set <key> <value>")
            self._out(f"  Keys: {', '.join(_SET_KEYS)}")
            print()
            return

        key, raw_value = parts[0].lower(), parts[1].strip()
        if key not in _SET_KEYS:
            self._err(f"Unknown key '{key}'.  Valid keys: {', '.join(_SET_KEYS)}")
            print()
            return

        field_name, coerce = _SET_KEYS[key]

        # Bool fields need special handling
        if field_name in ("stealth", "headless", "include_external"):
            try:
                value = _parse_bool(raw_value)
            except ValueError as e:
                self._err(f"Invalid value for '{key}': {e}")
                print()
                return
        else:
            try:
                value = coerce(raw_value)
            except (ValueError, TypeError) as e:
                self._err(f"Invalid value for '{key}': {e}")
                print()
                return

        # Validation
        error = self._validate_config(field_name, value)
        if error:
            self._err(error)
            print()
            return

        self.session.config[field_name] = value
        self._ok(f"{field_name} = {value}")
        self._save_config()
        print()

    def _validate_config(self, field_name: str, value) -> str | None:
        """Return an error string if the value is invalid, else None."""
        if field_name == "provider" and value not in _VALID_PROVIDERS:
            return f"provider must be one of: {', '.join(_VALID_PROVIDERS)}"
        if field_name == "strategy" and value not in _VALID_STRATEGIES:
            return f"strategy must be one of: {', '.join(_VALID_STRATEGIES)}"
        if field_name == "filter" and value not in _VALID_FILTERS:
            return f"filter must be one of: {', '.join(_VALID_FILTERS)}"
        if field_name == "cache" and value not in _VALID_CACHE:
            return f"cache must be one of: {', '.join(_VALID_CACHE)}"
        if field_name == "max_depth":
            if not (0 <= value <= 10):
                return "max_depth must be between 0 and 10"
        if field_name == "max_pages":
            if not (1 <= value <= 10000):
                return "max_pages must be between 1 and 10000"
        if field_name == "min_delay":
            if not (0 <= value <= 60):
                return "min_delay must be between 0 and 60"
            if value > self.session.config.get("max_delay", 60):
                return "min_delay must be <= max_delay"
        if field_name == "max_delay":
            if not (0 <= value <= 60):
                return "max_delay must be between 0 and 60"
            if value < self.session.config.get("min_delay", 0):
                return "max_delay must be >= min_delay"
        if field_name == "bm25_threshold":
            if value <= 0:
                return "bm25_threshold must be > 0"
        if field_name == "score_threshold":
            if not (0.0 <= value <= 1.0):
                return "score_threshold must be between 0.0 and 1.0"
        return None

    def cmd_reset(self, _args: str) -> None:
        count = len(self.session.results)
        if count > 0 and not self._confirm(f"Clear {count} results and persisted data?"):
            print()
            return
        self.session.results.clear()
        self.session.last_plan = None
        try:
            _RESULTS_FILE.write_text("")
        except Exception:
            pass
        self._ok(f"Cleared {count} results")
        print()

    def cmd_clear(self, _args: str) -> None:
        os.system("clear")

    def cmd_help(self, _args: str) -> None:
        print()
        lines = [
            ("/goal <text>",              "Set the crawl goal"),
            ("/crawl <url> [url...]",     "Start a deep crawl"),
            ("/fetch <url>",              "Fetch and summarize a single page"),
            ("/scrape <url> \"<desc>\"",  "AI-guided structured extraction"),
            ("/screenshot <url> [file]",  "Capture page as PNG"),
            ("/plan [url...]",            "Preview AI crawl plan (or show last)"),
            ("/results [n] [--opts]",     "Show results (--min-score, --sort)"),
            ("/export [file]",            "Export to CSV/JSON/Markdown"),
            ("/config",                   "Show current settings"),
            ("/set <key> <value>",        "Change a setting"),
            ("/reset",                    "Clear all results"),
            ("/clear",                    "Clear the screen"),
            ("/help",                     "Show this message"),
            ("/quit",                     "Exit"),
        ]
        self._out("Commands:")
        for cmd, desc in lines:
            self._out(f"  {CYAN(f'{cmd:<30}')} {desc}")
        print()
        self._out(f"Settings ({BOLD('/set')}):")
        setting_docs = [
            ("provider",         "claude, gemini"),
            ("max-depth",        "0-10"),
            ("max-pages",        "1-10000"),
            ("min-delay",        "0-60s"),
            ("max-delay",        "0-60s"),
            ("strategy",         "bfs, bestfirst, dfs"),
            ("filter",           "bm25, pruning, none"),
            ("bm25-threshold",   "> 0.0"),
            ("cache",            "enabled, bypass"),
            ("stealth",          "true, false"),
            ("headless",         "true, false"),
            ("score-threshold",  "0.0-1.0"),
            ("include-external", "true, false"),
        ]
        for k, v in setting_docs:
            self._out(f"  {CYAN(f'{k:<20}')} {DIM(v)}")
        print()
        self._out(f"{BOLD('Examples:')}")
        self._out(f'  /goal "find B2B SaaS pricing pages"')
        self._out(f"  /crawl https://www.ycombinator.com/companies")
        self._out(f"  /fetch https://stripe.com/pricing")
        self._out(f'  /scrape https://example.com/pricing "extract plan names and prices"')
        print()

    def cmd_quit(self, _args: str) -> None:
        self._out("Bye!")
        sys.exit(0)


def main() -> None:
    REPL().run()


if __name__ == "__main__":
    main()
