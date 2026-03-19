#!/usr/bin/env python3
"""Interactive CLI for the AI-powered leads crawler."""
import csv
import os
import readline
import sys
import time
from dataclasses import dataclass, field

# Allow imports from app/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

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
        "provider":       "gemini",
        "max_depth":      1,
        "max_pages":      20,
        "threads":        4,
        "rps":            1.0,
        "min_delay":      1.0,
        "max_delay":      3.0,
        "respect_robots": True,
    })
    results: list = field(default_factory=list)  # list[PageResult]
    active_engine: object = None                  # CrawlEngine | None


# ── /set key aliases ──────────────────────────────────────────────────────────
_SET_KEYS = {
    "provider":  ("provider",       str),
    "max-pages": ("max_pages",      int),
    "max-depth": ("max_depth",      int),
    "threads":   ("threads",        int),
    "rps":       ("rps",            float),
    "min-delay": ("min_delay",      float),
    "max-delay": ("max_delay",      float),
    "robots":    ("respect_robots", lambda v: v.lower() in ("on", "true", "1", "yes")),
}

_COMMANDS = [
    "/goal", "/crawl", "/status", "/results",
    "/export", "/config", "/set", "/clear", "/help", "/quit", "/exit",
]


class REPL:
    def __init__(self) -> None:
        self.session = Session()

    # ── readline tab completion ───────────────────────────────────────────────
    def complete(self, text: str, state: int):
        options = [c for c in _COMMANDS if c.startswith(text)]
        return options[state] if state < len(options) else None

    # ── main loop ─────────────────────────────────────────────────────────────
    def run(self) -> None:
        readline.set_completer(self.complete)
        readline.set_completer_delims(" ")
        readline.parse_and_bind("tab: complete")

        print(f"\n{BOLD('╭─────────────────────────────────────────────────────────────╮')}")
        print(f"{BOLD('│')}  {CYAN('Leads Crawler')}  ·  type {BOLD('/help')} for commands                  {BOLD('│')}")
        print(f"{BOLD('╰─────────────────────────────────────────────────────────────╯')}\n")

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
            "/goal":    self.cmd_goal,
            "/crawl":   self.cmd_crawl,
            "/status":  self.cmd_status,
            "/results": self.cmd_results,
            "/export":  self.cmd_export,
            "/config":  self.cmd_config,
            "/set":     self.cmd_set,
            "/clear":   self.cmd_clear,
            "/help":    self.cmd_help,
            "/quit":    self.cmd_quit,
            "/exit":    self.cmd_quit,
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

    # ── command handlers ──────────────────────────────────────────────────────
    def cmd_goal(self, args: str) -> None:
        text = args.strip().strip('"').strip("'")
        if not text:
            self._err("Usage: /goal <text>")
        else:
            self.session.goal = text
            self._ok(f"Goal set: {DIM(text)}")
        print()

    def cmd_crawl(self, args: str) -> None:
        urls = args.split()
        if not urls:
            self._err("Usage: /crawl <url> [url...]")
            print()
            return
        if not self.session.goal:
            self._err("Set a goal first with /goal <text>")
            print()
            return

        cfg = self.session.config
        provider_name = cfg["provider"]

        # API key check
        if provider_name == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
            self._err("ANTHROPIC_API_KEY environment variable not set")
            print()
            return
        if provider_name == "gemini" and not os.environ.get("GEMINI_API_KEY"):
            self._err("GEMINI_API_KEY environment variable not set")
            print()
            return

        ai = GeminiProvider() if provider_name == "gemini" else ClaudeProvider()

        page_results: list[PageResult] = []

        def on_status(s: str) -> None:
            if s == "planning":
                self._out(f"{BOLD('Planning')} with {provider_name.upper()}...")
            elif s == "running":
                self._out(f"{GREEN('Running')} — press Ctrl+C to stop early\n")
            elif s == "completed":
                self._out(f"\n{GREEN('Completed.')}")
            elif s == "cancelled":
                self._out(f"\n{YELLOW('Cancelled.')}")

        def on_page(r: PageResult) -> None:
            page_results.append(r)
            n = len(page_results)
            if r.error:
                sym   = RED("✗")
                label = DIM(r.url[:80])
                extra = f"  {DIM('(' + r.error + ')')}"
            else:
                sym   = GREEN("✓")
                label = r.url[:80]
                extra = ""
            self._out(f"{sym} [{n:>4}] depth={r.depth}  {label}{extra}")

        def on_sse(event: dict) -> None:
            if event.get("event") == "plan":
                summary = event.get("summary", "")
                if summary:
                    self._out(f"{CYAN('AI plan')}: {summary}\n")

        engine = Crawl4AIEngine(
            job_id="cli",
            goal=self.session.goal,
            seed_urls=urls,
            ai_provider=ai,
            max_depth=cfg["max_depth"],
            max_pages=cfg["max_pages"],
            thread_count=cfg["threads"],
            rate_limit_rps=cfg["rps"],
            min_delay=cfg["min_delay"],
            max_delay=cfg["max_delay"],
            respect_robots=cfg["respect_robots"],
            on_status_change=on_status,
            on_page_done=on_page,
            on_sse_event=on_sse,
        )
        self.session.active_engine = engine

        try:
            engine.start()
        except KeyboardInterrupt:
            engine.stop()
            self._out(f"{YELLOW('Stopping...')}")
            time.sleep(1)
        finally:
            self.session.active_engine = None

        good = [r for r in page_results if not r.error]
        bad  = [r for r in page_results if r.error]
        self.session.results = page_results
        self._out(f"\nCompleted: {BOLD(str(len(good)))} pages crawled, {len(bad)} errors")
        print()

    def cmd_status(self, _args: str) -> None:
        if self.session.active_engine is None:
            self._out("No active crawl.")
        else:
            self._out(f"Crawl in progress — {len(self.session.results)} pages so far.")
        print()

    def _get_ai_provider(self):
        """Build an AI provider from current config."""
        name = self.session.config["provider"]
        return GeminiProvider() if name == "gemini" else ClaudeProvider()

    def cmd_results(self, args: str) -> None:
        try:
            n = int(args.strip()) if args.strip() else 10
        except ValueError:
            self._err("Usage: /results [n]")
            print()
            return

        # Deduplicate by URL, keeping highest-scored version
        seen: dict[str, PageResult] = {}
        for r in self.session.results:
            if r.error:
                continue
            if r.url not in seen or r.score > seen[r.url].score:
                seen[r.url] = r

        good = sorted(seen.values(), key=lambda r: r.score, reverse=True)[:n]

        if not good:
            self._out("No results yet — run /crawl first.")
            print()
            return

        # Generate summaries on demand for results that don't have one
        needs_summary = [r for r in good if not r.summary and r.text]
        if needs_summary and self.session.goal:
            self._out(f"{DIM('Generating summaries...')}")
            failed = 0
            try:
                ai = self._get_ai_provider()
            except Exception as e:
                self._err(f"Could not initialise AI provider: {e}")
                ai = None

            if ai:
                for r in needs_summary:
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
            self._out(f"{BOLD(f'{i}.')}  {CYAN(r.url):<80}  {DIM(f'score={r.score:.2f}')}")
            if r.summary:
                self._out(f"    {r.summary}")
            elif r.text:
                snippet = r.text[:120].replace("\n", " ")
                self._out(f"    {DIM(snippet)}")
            print()

    def cmd_export(self, args: str) -> None:
        path = args.strip() or "results.csv"
        good = [r for r in self.session.results if not r.error]
        if not good:
            self._err("No results to export.")
            print()
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["url", "depth", "score", "links_count", "summary", "text_snippet"]
            )
            writer.writeheader()
            for r in good:
                writer.writerow({
                    "url":          r.url,
                    "depth":        r.depth,
                    "score":        r.score,
                    "links_count":  len(r.links),
                    "summary":      r.summary,
                    "text_snippet": r.text[:500].replace("\n", " ") if r.text else "",
                })
        self._ok(f"Saved {len(good)} results → {path}")
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
        try:
            value = coerce(raw_value)
        except (ValueError, TypeError) as e:
            self._err(f"Invalid value for '{key}': {e}")
            print()
            return

        # Extra validation for provider
        if field_name == "provider" and value not in ("claude", "gemini"):
            self._err("provider must be 'claude' or 'gemini'")
            print()
            return

        self.session.config[field_name] = value
        self._ok(f"{field_name} = {value}")
        print()

    def cmd_clear(self, _args: str) -> None:
        os.system("clear")

    def cmd_help(self, _args: str) -> None:
        print()
        lines = [
            ("/goal <text>",       "Set the crawl goal"),
            ("/crawl <url> [url…]", "Start a crawl"),
            ("/status",            "Show current crawl status"),
            ("/results [n]",       "Show top n results (default 10)"),
            ("/export [file]",     "Save results to CSV (default: results.csv)"),
            ("/config",            "Show current settings"),
            ("/set <key> <value>", "Change a setting"),
            ("/clear",             "Clear the screen"),
            ("/help",              "Show this message"),
            ("/quit",              "Exit"),
        ]
        self._out("Commands:")
        for cmd, desc in lines:
            self._out(f"  {CYAN(f'{cmd:<26}')} {desc}")
        print()

    def cmd_quit(self, _args: str) -> None:
        self._out("Bye!")
        sys.exit(0)


def main() -> None:
    REPL().run()


if __name__ == "__main__":
    main()
