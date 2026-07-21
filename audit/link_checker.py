"""
link_checker.py — finds every unique link referenced across the crawled
pages (internal and external) and checks whether it actually resolves.

Unlike the crawler (which only *follows* same-domain links to find more
pages), this checks every <a href> found — including external ones — since
a link to a dead external page is exactly the kind of thing an audit should
catch, even though the crawler never visits it.
"""

import concurrent.futures
from urllib.parse import urljoin, urlparse

import requests

from audit.safety import assert_safe_url, UnsafeURLError

REQUEST_TIMEOUT = 6
MAX_WORKERS = 10
# Many sites 403 HEAD/GET requests from an identifiable bot UA (even though
# the page works fine for real visitors), which would show up as false
# broken links. A common browser UA avoids that noise.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _issue(id_, label, status, detail, page):
    return {"id": id_, "label": label, "status": status, "detail": detail, "page": page}


def collect_links(pages):
    """
    Returns { normalized_url: {"referrers": set[str], "is_internal": bool} }
    """
    if not pages:
        return {}
    root_netloc = urlparse(pages[0].url).netloc.replace("www.", "")
    links = {}

    for page in pages:
        if not page.soup:
            continue
        for a in page.soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            abs_url = urljoin(page.url, href)
            abs_url = urlparse(abs_url)._replace(fragment="").geturl()
            if not abs_url.startswith(("http://", "https://")):
                continue
            is_internal = urlparse(abs_url).netloc.replace("www.", "") == root_netloc
            entry = links.setdefault(abs_url, {"referrers": set(), "is_internal": is_internal})
            entry["referrers"].add(page.url)

    return links


def _check_one(url, session):
    try:
        assert_safe_url(url)
        resp = session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        # Some servers don't implement HEAD properly (405/501) — retry with GET.
        if resp.status_code in (405, 501):
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
            resp.close()
        return resp.status_code, None
    except UnsafeURLError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, str(exc)


def check_links(links, max_links=60):
    """
    Checks up to max_links unique URLs concurrently.
    Returns list of dicts: {url, status_code, ok, error, is_internal, referrers, skipped}
    """
    items = list(links.items())
    to_check, skipped = items[:max_links], items[max_links:]
    results = []

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_url = {pool.submit(_check_one, url, session): (url, meta) for url, meta in to_check}
        for future in concurrent.futures.as_completed(future_to_url):
            url, meta = future_to_url[future]
            status_code, error = future.result()
            results.append({
                "url": url,
                "status_code": status_code,
                "ok": error is None and status_code is not None and status_code < 400,
                "error": error,
                "is_internal": meta["is_internal"],
                "referrers": sorted(meta["referrers"]),
                "skipped": False,
            })

    for url, meta in skipped:
        results.append({
            "url": url, "status_code": None, "ok": None, "error": None,
            "is_internal": meta["is_internal"], "referrers": sorted(meta["referrers"]),
            "skipped": True,
        })

    # Internal broken links first, then external, then skipped.
    results.sort(key=lambda r: (r["skipped"], r["ok"] is not False, not r["is_internal"]))
    return results


def to_issues(link_results):
    issues = []
    for r in link_results:
        if r["skipped"]:
            continue
        kind = "Internal link" if r["is_internal"] else "External link"
        referrer = r["referrers"][0] if r["referrers"] else ""
        extra = f" (linked from {len(r['referrers'])} pages)" if len(r["referrers"]) > 1 else ""

        if r["ok"]:
            issues.append(_issue("link-ok", kind, "pass", f"{r['url']} → {r['status_code']}", referrer))
        elif r["error"]:
            issues.append(_issue("link-unreachable", kind, "fail",
                                  f"{r['url']} → unreachable ({r['error']}){extra}", referrer))
        elif r["status_code"] and r["status_code"] >= 500:
            issues.append(_issue("link-server-error", kind, "fail",
                                  f"{r['url']} → server error {r['status_code']}{extra}", referrer))
        else:
            # 4xx: broken internal links are a hard fail; broken external links are a notice
            # (the target site's problem, not necessarily this one's).
            status = "fail" if r["is_internal"] else "warn"
            issues.append(_issue("link-broken", kind, status,
                                  f"{r['url']} → {r['status_code']}{extra}", referrer))
    return issues
