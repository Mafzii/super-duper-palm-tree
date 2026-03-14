"""HTML parser: link extraction and text extraction."""
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .url_utils import normalize_url


def parse(html: str, base_url: str) -> tuple[list[str], str]:
    """
    Parse HTML and return (links, text_snippet).
    Links are absolute, normalized, http/https only.
    Text is stripped body text truncated to 2000 chars.
    """
    soup = BeautifulSoup(html, "lxml")

    # Extract links
    links: list[str] = []
    seen_links: set[str] = set()
    base_host = urlparse(base_url).netloc

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        normalized = normalize_url(href, base_url)
        if not normalized:
            continue
        parsed = urlparse(normalized)
        if parsed.scheme not in ("http", "https"):
            continue
        if normalized not in seen_links:
            seen_links.add(normalized)
            links.append(normalized)

    # Extract text
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())[:2000]

    return links, text
