import re
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from readability import Document
from duckduckgo_search import DDGS
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

CHUNK_SIZE = 3500

_SKIP_TAGS = {
    "script", "style", "noscript", "iframe", "nav", "header", "footer",
    "aside", "form", "button", "input", "select", "textarea",
    "svg", "canvas", "video", "audio", "picture", "img",
}

_NOISE_PATTERN = re.compile(
    r"(cookie|consent|banner|popup|modal|newsletter|subscribe|"
    r"sidebar|widget|related|advert|promo|social|share|comment)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# w3m-style renderer
# ---------------------------------------------------------------------------

class Renderer:
    """Walks a BeautifulSoup tree and produces plain text with inline link refs."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []   # (label, url)
        self._link_index: dict[str, int] = {}    # url -> [N]
        self._ol_stack: list[int] = []           # counter stack for nested <ol>

    def _add_link(self, url: str, label: str) -> int:
        if url not in self._link_index:
            self._link_index[url] = len(self.links) + 1
            self.links.append((label[:80], url))
        return self._link_index[url]

    def render(self, node) -> str:
        if isinstance(node, NavigableString):
            return re.sub(r"[ \t]+", " ", str(node))

        if not isinstance(node, Tag):
            return ""

        name = (node.name or "").lower()

        if name in _SKIP_TAGS:
            return ""

        # Drop elements that look like noise by class/id
        if name not in ("html", "body"):
            attrs = " ".join([
                " ".join(node.get("class", [])),
                node.get("id", ""),
            ])
            if _NOISE_PATTERN.search(attrs):
                return ""

        inner = lambda: "".join(self.render(c) for c in node.children)

        # ---- structural pass-throughs ----
        if name in ("html", "body", "main", "article", "section"):
            return inner()

        if name in ("div", "span"):
            content = inner()
            return f"\n{content.strip()}\n" if name == "div" and content.strip() else content

        # ---- block elements ----
        if name == "p":
            content = inner().strip()
            return f"\n\n{content}\n\n" if content else ""

        if name == "br":
            return "\n"

        if name == "hr":
            return "\n" + "─" * 36 + "\n"

        if name == "blockquote":
            lines = inner().strip().splitlines()
            quoted = "\n".join(f"  │ {ln}" for ln in lines)
            return f"\n\n{quoted}\n\n"

        if name in ("pre", "code"):
            return f"\n{inner().strip()}\n"

        # ---- headings ----
        if name == "h1":
            text = inner().strip()
            bar = "═" * min(max(len(text), 4), 40)
            return f"\n\n{bar}\n{text.upper()}\n{bar}\n\n"

        if name == "h2":
            text = inner().strip()
            return f"\n\n{text}\n{'─' * min(max(len(text), 4), 40)}\n\n"

        if name == "h3":
            return f"\n\n▌ {inner().strip()}\n\n"

        if name in ("h4", "h5", "h6"):
            return f"\n\n◆ {inner().strip()}\n\n"

        # ---- lists ----
        if name == "ul":
            return f"\n{inner()}\n"

        if name == "ol":
            self._ol_stack.append(0)
            result = f"\n{inner()}\n"
            self._ol_stack.pop()
            return result

        if name == "li":
            content = inner().strip()
            if self._ol_stack:
                self._ol_stack[-1] += 1
                return f"\n  {self._ol_stack[-1]}. {content}"
            return f"\n  - {content}"

        # ---- links ----
        if name == "a":
            href = (node.get("href") or "").strip()
            content = inner().strip()
            if not content:
                return ""
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                full_url = urljoin(self.base_url, href)
                if full_url.startswith(("http://", "https://")):
                    num = self._add_link(full_url, content)
                    return f"{content}[{num}]"
            return content

        # ---- inline formatting ----
        if name in ("strong", "b"):
            text = inner().strip()
            return text.upper() if text else ""

        if name == "em":
            return f"/{inner().strip()}/"

        # ---- tables (simple grid) ----
        if name == "table":
            return f"\n{inner()}\n"

        if name in ("thead", "tbody", "tfoot"):
            return inner()

        if name == "tr":
            cells = [
                self.render(child).strip()
                for child in node.children
                if isinstance(child, Tag) and child.name in ("td", "th")
            ]
            return ("  │  ".join(cells) + "\n") if cells else ""

        if name in ("td", "th"):
            return inner()

        # everything else — just recurse
        return inner()


def _normalize(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)       # collapse horizontal space
    text = re.sub(r" *\n *", "\n", text)       # trim spaces around newlines
    text = re.sub(r"\n{3,}", "\n\n", text)     # max two consecutive blank lines
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    resp.raise_for_status()

    # Readability isolates the main content
    doc = Document(resp.text)
    title = (doc.title() or "Untitled")[:120]
    content_html = doc.summary(html_partial=True)

    renderer = Renderer(base_url=resp.url)
    soup = BeautifulSoup(content_html, "html.parser")
    raw = renderer.render(soup)
    text = _normalize(raw)

    # Fallback: render full page if readability returned too little
    if len(text) < 80:
        renderer = Renderer(base_url=resp.url)
        soup = BeautifulSoup(resp.text, "html.parser")
        raw = renderer.render(soup)
        text = _normalize(raw)

    return {
        "title": title,
        "url": resp.url,
        "text": text,
        "links": renderer.links[:50],
    }


def search_web(query: str, max_results: int = 10) -> list[dict]:
    last_exc = None
    for _ in range(3):
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
