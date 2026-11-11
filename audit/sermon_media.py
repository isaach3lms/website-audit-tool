"""
sermon_media.py: do the sermons and live stream exist, work, load fast, and look current?

This is the one Guest/Content check that makes outside requests: it fetches a
handful of the sermon and stream links it finds and times them. Network calls
are bounded (6 URLs, 6 second timeout, run in parallel) and go through the same
SSRF guard as the rest of the tool.

Components:
  - a sermons or media section exists
  - media links respond without errors and in under 3 seconds
  - the newest dated sermon is within 90 days (only judged when a sermon page
    with explicit dates was actually crawled)

A live-stream link is welcomed but never required, since many churches do not
stream. It only shows up as a tip.
"""

import concurrent.futures
import re
import time
from datetime import date

import requests

from audit.dates import extract_page_dates
from audit.safety import assert_safe_url, UnsafeURLError
from audit.structure import SG_SERMON

MAX_CHECKS = 6
TIMEOUT = 6
SLOW_MS = 3000
FRESH_DAYS = 90
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_SERMON_TEXT_RE = re.compile(
    r"sermons?|messages?|watch|listen|media|podcast|live ?stream|online (?:service|church)|archive|teachings?|series")
_SERMON_PATH_RE = re.compile(r"/(?:sermons?|messages?|watch|listen|media|podcasts?|live|livestream|online|teaching|series|archive)(?:/|-)")
_MEDIA_HOST_RE = re.compile(
    r"youtube\.com|youtu\.be|vimeo\.com|podbean|buzzsprout|spreaker|soundcloud|subsplash|churchonlineplatform|"
    r"boxcast|resi\.io|livestream\.com|sermonaudio|apple\.co|podcasts\.apple|spotify\.com|"
    r"facebook\.com/[^/]+/(?:videos|live)", re.I)
_LIVE_RE = re.compile(r"watch live|live ?stream|livestream|join (?:us )?online|online service|/live\b", re.I)


def _fetch(url):
    """Returns (status_code_or_None, elapsed_ms, error_or_None)."""
    start = time.time()
    try:
        assert_safe_url(url)
        resp = requests.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True,
                            headers={"User-Agent": USER_AGENT})
        resp.close()
        return resp.status_code, (time.time() - start) * 1000, None
    except UnsafeURLError as exc:
        return None, 0, str(exc)
    except requests.RequestException as exc:
        return None, (time.time() - start) * 1000, str(exc)


def _is_sermon_doc(doc):
    return bool(_SERMON_PATH_RE.search(doc.path) or re.search(r"sermon|messages|watch|media|podcast", doc.headings))


def check_site(docs, today=None, fetch=None):
    """Returns one issue dict (or None when there are no pages)."""
    if not docs:
        return None
    today = today or date.today()
    fetch = fetch or _fetch
    home = docs[0]

    sermon_docs = [d for d in docs if _is_sermon_doc(d)]
    section_link = None
    for d in docs:
        for link in d.links:
            if link["href"].startswith(("mailto:", "tel:")):
                continue
            if (link["text"] and len(link["text"]) <= 40 and _SERMON_TEXT_RE.search(link["text"])) or \
               _SERMON_PATH_RE.search(re.sub(r"^https?://[^/]+", "", link["href"].lower()) + "/"):
                section_link = section_link or link
    has_section = bool(sermon_docs or section_link or _MEDIA_HOST_RE.search(" ".join(
        l["href"] for d in docs for l in d.links)) or any(_MEDIA_HOST_RE.search(s) for d in docs for s in d.iframes))

    # Collect media URLs worth testing
    urls, seen = [], set()

    def add(u):
        if u and u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            urls.append(u)

    for d in docs:
        for src in d.iframes:
            if _MEDIA_HOST_RE.search(src):
                add(src)
    for d in docs:
        for link in d.links:
            if _MEDIA_HOST_RE.search(link["href"]) or _LIVE_RE.search(link["text"] or ""):
                add(link["href"])
    if section_link:
        add(section_link["href"])

    # Crawled sermon pages were already timed by the crawler; reuse that instead of refetching
    crawled_times = [(d.url, d.elapsed_ms) for d in sermon_docs if d.elapsed_ms is not None]
    to_fetch = [u for u in urls if u not in {c[0] for c in crawled_times}][:MAX_CHECKS]

    results = []
    if to_fetch:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CHECKS) as pool:
            for url, (code, ms, err) in zip(to_fetch, pool.map(fetch, to_fetch)):
                results.append({"url": url, "code": code, "ms": ms, "error": err})
    for url, ms in crawled_times:
        results.append({"url": url, "code": 200, "ms": ms, "error": None})

    # "Broken" means gone or erroring. 403/429 from big platforms often just means "bot", so not counted.
    broken = [r for r in results if r["error"] or (r["code"] and (r["code"] >= 500 or r["code"] in (404, 410)))]
    slow = [r for r in results if r not in broken and r["ms"] and r["ms"] > SLOW_MS]
    works = bool(results) and not broken and not slow

    # Recency, only when we actually saw a dated sermon page
    newest = None
    for d in sermon_docs:
        dates = [x for x in extract_page_dates(d) if x <= today]
        if dates:
            newest = max(newest, max(dates)) if newest else max(dates)
    recency_known = newest is not None
    fresh = recency_known and (today - newest).days <= FRESH_DAYS

    components = [
        ("a sermons or media section", has_section),
        ("sermon and stream links that load without errors in under 3 seconds", works),
    ]
    if recency_known:
        components.append((f"a sermon posted in the last {FRESH_DAYS} days", fresh))

    fix_bits = []
    if not has_section:
        fix_bits.append("Add a sermons page with the latest messages and, if you stream, a clear live link.")
    if broken:
        fix_bits.append(f"Broken: {', '.join(r['url'] for r in broken[:3])}.")
    if slow:
        fix_bits.append("Slow (over 3 seconds): " + ", ".join(f"{r['url']} ({r['ms'] / 1000:.1f}s)" for r in slow[:3]) + ".")
    if has_section and not results:
        fix_bits.append("No playable media links or embeds were found to test.")
    if recency_known and not fresh:
        fix_bits.append(f"Newest dated sermon is {newest.isoformat()}, so the archive looks stale.")
    if not recency_known and has_section:
        fix_bits.append("Recency was not judged because no dated sermon page was crawled.")

    tip = ""
    if not any(_LIVE_RE.search((l["text"] or "") + " " + l["href"]) for d in docs for l in d.links):
        tip = "Tip: a clear Watch Live link helps people who cannot attend in person."

    from audit.guest_experience import _result  # same component/points convention as the Guest checks
    page = (sermon_docs[0].url if sermon_docs else (section_link["href"] if section_link else home.url))
    return _result("content-sermon-media", "Sermon media loads and is current", SG_SERMON,
                   components, page, " ".join(fix_bits), tip)
