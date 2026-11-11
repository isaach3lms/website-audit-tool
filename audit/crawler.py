"""
crawler.py — same-domain site crawler.

Walks a site breadth-first starting at a seed URL, staying on the same
registrable domain, up to a page limit and depth limit. For every page it
records the raw HTML, response headers, timing, and status code, which the
check modules then analyze.
"""

import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from audit.safety import assert_safe_url, UnsafeURLError

USER_AGENT = "WebsiteAuditBot/1.0 (+local audit tool)"
REQUEST_TIMEOUT = 10  # seconds


class PageResult:
    def __init__(self, url, status_code=None, html="", headers=None,
                 elapsed_ms=None, error=None, depth=0):
        self.url = url
        self.status_code = status_code
        self.html = html
        self.headers = headers or {}
        self.elapsed_ms = elapsed_ms
        self.error = error
        self.depth = depth
        self.soup = BeautifulSoup(html, "html.parser") if html else None

    @property
    def ok(self):
        return self.error is None and self.status_code and self.status_code < 400


def _same_domain(url, root_netloc):
    try:
        return urlparse(url).netloc.replace("www.", "") == root_netloc.replace("www.", "")
    except Exception:
        return False


# Pages a first-time guest would look for. Matched against the link URL path and
# the link text; deliberately loose, since it only affects crawl order.
_GUEST_PAGE_RE = re.compile(
    r"visit|\bnew\b|/new|first|plan|expect|about|believ|belief|faith|kids|child|youth|nursery|worship|music|"
    r"staff|team|leader|pastor|contact|location|direction|connect|welcome|ministr|service|sunday|gather",
    re.IGNORECASE,
)


def _is_guest_page(url, link_text=""):
    return bool(_GUEST_PAGE_RE.search(urlparse(url).path) or _GUEST_PAGE_RE.search(link_text[:60]))


def _normalize(url):
    parsed = urlparse(url)
    # Strip fragments; keep query since some sites route on it.
    return parsed._replace(fragment="").geturl()


def crawl(seed_url, max_pages=10, max_depth=2, progress_cb=None, max_seconds=25):
    """
    Crawl a site starting at seed_url.

    progress_cb: optional callable(PageResult) invoked as each page finishes,
    useful for streaming a live crawl log to a UI.

    max_seconds: hard wall-clock budget for the whole crawl. Whatever's been
    fetched by then is returned as-is — important on a hosted deployment
    where the platform will kill a request that runs too long anyway.

    Returns: list[PageResult]
    """
    if not seed_url.startswith(("http://", "https://")):
        seed_url = "https://" + seed_url

    root_netloc = urlparse(seed_url).netloc
    seen = {_normalize(seed_url)}
    queue = deque([(seed_url, 0)])
    results = []
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    started = time.monotonic()

    while queue and len(results) < max_pages:
        if time.monotonic() - started > max_seconds:
            break

        url, depth = queue.popleft()
        start = time.time()
        try:
            assert_safe_url(url)
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            elapsed_ms = (time.time() - start) * 1000
            page = PageResult(
                url=url,
                status_code=resp.status_code,
                html=resp.text if "text/html" in resp.headers.get("Content-Type", "") else "",
                headers=resp.headers,
                elapsed_ms=elapsed_ms,
                depth=depth,
            )
        except UnsafeURLError as exc:
            page = PageResult(url=url, error=str(exc), depth=depth)
        except requests.RequestException as exc:
            page = PageResult(url=url, error=str(exc), depth=depth)

        results.append(page)
        if progress_cb:
            progress_cb(page)

        if page.soup and depth < max_depth:
            priority_batch, regular_batch, on_page = [], [], set()
            for a in page.soup.find_all("a", href=True):
                link = _normalize(urljoin(url, a["href"]))
                if link.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                if link in seen or link in on_page:
                    continue
                if not _same_domain(link, root_netloc):
                    continue
                on_page.add(link)
                if _is_guest_page(link, a.get_text(" ", strip=True)):
                    priority_batch.append(link)
                else:
                    regular_batch.append(link)

            # Guest-facing pages (visit, kids, beliefs, staff...) go first, both
            # for the queue-growth cap and for crawl order, so the Guest
            # Experience Review sees them even on a small crawl.
            to_front = []
            for link in priority_batch + regular_batch:
                seen.add(link)
                if len(seen) <= max_pages * 4:  # cap queue growth
                    if link in priority_batch:
                        to_front.append((link, depth + 1))
                    else:
                        queue.append((link, depth + 1))
            queue.extendleft(reversed(to_front))

    return results
