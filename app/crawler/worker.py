"""Shared data types for crawl results."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageResult:
    url: str
    depth: int
    text: str
    links: list[str] = field(default_factory=list)
    score: float = 0.0
    error: str = ""
    summary: str = ""
    extracted_content: str = ""
    title: str = ""
    status_code: int = 0
