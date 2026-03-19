"""HTML parser: link extraction and text extraction."""
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from .url_utils import normalize_url


def _extract_main_content(soup: BeautifulSoup) -> str:
    """Extract main content text, stripping boilerplate."""
    # Remove boilerplate tags
    for tag in soup(["script", "style", "noscript", "head", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Try semantic containers first
    for selector in ["article", "main", "[role='main']", "[itemprop='articleBody']"]:
        container = soup.select_one(selector)
        if container:
            text = " ".join(container.get_text(separator=" ").split())
            if len(text) > 100:
                return text[:6000]

    # Fallback: largest text-dense div/section
    best, best_len = None, 0
    for tag in soup.find_all(["div", "section"]):
        if not isinstance(tag, Tag):
            continue
        text = tag.get_text(separator=" ", strip=True)
        if len(text) > best_len:
            best, best_len = text, len(text)

    if best and best_len > 100:
        return " ".join(best.split())[:6000]

    # Final fallback: full body text
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:6000]


def parse(html: str, base_url: str) -> tuple[list[str], str]:
    """
    Parse HTML and return (links, text_snippet).
    Links are absolute, normalized, http/https only.
    Text is main content text truncated to 6000 chars.
    """
    soup = BeautifulSoup(html, "lxml")

    # Respect <base href> tag
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = normalize_url(base_tag["href"], base_url) or base_url

    # Extract links (before decomposing tags)
    links: list[str] = []
    seen_links: set[str] = set()

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

    # Extract text (tag decomposition happens inside helper)
    text = _extract_main_content(soup)

    return links, text
