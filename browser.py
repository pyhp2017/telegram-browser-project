import requests
import html2text
from bs4 import BeautifulSoup
from readability import Document
from duckduckgo_search import DDGS
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

CHUNK_SIZE = 3500  # stay safely under Telegram's 4096-char limit


def fetch_page(url: str) -> dict:
    """Fetch a URL and return title, text content, and extracted links."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    resp.raise_for_status()

    # Use readability to extract main article content
    doc = Document(resp.text)
    title = doc.title() or "Untitled"
    content_html = doc.summary(html_partial=True)

    # Convert HTML to plain text
    converter = html2text.HTML2Text()
    converter.ignore_links = True
    converter.ignore_images = True
    converter.ignore_emphasis = False
    converter.body_width = 0
    converter.ul_item_mark = "-"
    text = converter.handle(content_html).strip()

    if not text or len(text) < 50:
        # Fallback: strip all tags from full page
        soup_full = BeautifulSoup(resp.text, "html.parser")
        for tag in soup_full(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup_full.get_text(separator="\n", strip=True)

    # Extract links from the full page
    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    seen_urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full_url = urljoin(resp.url, href)
        if not full_url.startswith(("http://", "https://")):
            continue
        link_text = a.get_text(strip=True) or full_url
        link_text = " ".join(link_text.split())  # normalise whitespace
        if full_url not in seen_urls and link_text:
            seen_urls.add(full_url)
            links.append((link_text[:80], full_url))

    return {
        "title": title[:120],
        "url": resp.url,
        "text": text,
        "links": links[:40],
    }


def search_web(query: str, max_results: int = 10) -> list[dict]:
    """Search DuckDuckGo and return a list of results."""
    last_exc = None
    for attempt in range(3):
        try:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", "")[:100],
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")[:200],
                    })
            return results
        except Exception as e:
            last_exc = e
    raise RuntimeError(
        f"DuckDuckGo search failed after 3 attempts: {last_exc}\n"
        "Try: pip install -U duckduckgo-search"
    ) from last_exc


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split text into chunks, preferring newline boundaries."""
    chunks = []
    while len(text) > size:
        split_at = text.rfind("\n", 0, size)
        if split_at == -1:
            split_at = size
        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip("\n")
    if text.strip():
        chunks.append(text.strip())
    return chunks or ["(No readable content found)"]
