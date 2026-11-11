"""
pagedoc.py: a crawled page, digested once, shared by every check module.

Building the visible text, link list, and JSON-LD for each page is the
expensive part of most checks, so it happens here a single time and the check
modules only search the result.
"""

import json
import re
from urllib.parse import urljoin, urlparse

from bs4.element import Comment, Doctype, CData, ProcessingInstruction, Declaration

_SKIP_PARENTS = {"script", "style", "noscript", "template", "head", "title"}
_SKIP_NODES = (Comment, Doctype, CData, ProcessingInstruction, Declaration)
VIDEO_SRC_RE = re.compile(r"youtube|youtu\.be|vimeo|wistia|vidyard|loom\.com", re.I)


def normalize(text):
    text = (text or "").replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def visible_raw(soup):
    """Visible text with original case. Unlike soup.get_text(), skips script/style contents."""
    parts = []
    for node in soup.find_all(string=True):
        if isinstance(node, _SKIP_NODES):
            continue
        if node.parent is not None and node.parent.name in _SKIP_PARENTS:
            continue
        piece = node.strip()
        if piece:
            parts.append(piece)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _flatten_jsonld(data, out):
    if isinstance(data, list):
        for item in data:
            _flatten_jsonld(item, out)
    elif isinstance(data, dict):
        if "@graph" in data:
            _flatten_jsonld(data["@graph"], out)
        out.append(data)


class Doc:
    """One reachable crawled page."""

    def __init__(self, page):
        self.url = page.url
        self.soup = page.soup
        self.html = page.html or ""
        self.elapsed_ms = getattr(page, "elapsed_ms", None)
        self.raw_text = visible_raw(page.soup)
        self.text = normalize(self.raw_text)

        self.links = []
        for a in page.soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                if href.startswith(("mailto:", "tel:")):
                    self.links.append({"text": normalize(a.get_text(" ", strip=True)), "href": href,
                                       "in_nav": False})
                continue
            label = normalize(a.get_text(" ", strip=True) or a.get("aria-label", "") or a.get("title", ""))
            self.links.append({
                "text": label,
                "href": urljoin(page.url, href),
                "in_nav": a.find_parent(["nav", "header"]) is not None,
            })

        heading_bits = [t.get_text(" ", strip=True) for t in page.soup.find_all(["title", "h1", "h2"])]
        self.headings = normalize(" ".join(heading_bits))
        self.title = (page.soup.title.get_text(" ", strip=True) if page.soup.title else "").strip()
        self.iframes = [f["src"].strip() for f in page.soup.find_all("iframe", src=True) if f["src"].strip()]
        self.has_video = bool(
            page.soup.find("video") or page.soup.find("audio")
            or any(VIDEO_SRC_RE.search(s) for s in self.iframes)
        )

        self.jsonld = []
        for tag in page.soup.find_all("script", type="application/ld+json"):
            try:
                _flatten_jsonld(json.loads(tag.string or tag.get_text() or ""), self.jsonld)
            except (ValueError, TypeError):
                continue

    @property
    def path(self):
        return urlparse(self.url).path.lower() + "/"


def search(docs, pattern):
    for d in docs:
        m = pattern.search(d.text)
        if m:
            return d, m
    return None, None


def search_near(docs, pattern, context, window=140):
    """First match of `pattern` that has `context` within `window` characters."""
    for d in docs:
        for m in pattern.finditer(d.text):
            lo, hi = max(0, m.start() - window), m.end() + window
            if context.search(d.text[lo:hi]):
                return d, m
    return None, None


def find_link(docs, text_re=None, href_re=None, max_text=60):
    for d in docs:
        for link in d.links:
            if link["href"].startswith(("mailto:", "tel:")):
                continue
            if text_re and link["text"] and len(link["text"]) <= max_text and text_re.search(link["text"]):
                return d, link
            if href_re and href_re.search(urlparse(link["href"]).path.lower() + "/"):
                return d, link
    return None, None
