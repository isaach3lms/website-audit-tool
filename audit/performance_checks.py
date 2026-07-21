"""
performance_checks.py — lightweight, no-headless-browser performance signals.

These are proxy signals reachable from a plain HTTP request (no real browser
rendering), so they're framed as directional, not lab-grade Lighthouse numbers.
"""


def _issue(id_, label, status, detail, page):
    return {"id": id_, "label": label, "status": status, "detail": detail, "page": page}


def check_page(page):
    issues = []
    url = page.url

    if page.error:
        issues.append(_issue("fetch-error", "Reachability", "fail", f"Request failed: {page.error}", url))
        return issues

    # Response time
    if page.elapsed_ms is not None:
        if page.elapsed_ms < 400:
            status = "pass"
        elif page.elapsed_ms < 1200:
            status = "warn"
        else:
            status = "fail"
        issues.append(_issue("ttfb", "Response time", status, f"{page.elapsed_ms:.0f} ms", url))

    # HTML payload size
    size_kb = len(page.html.encode("utf-8")) / 1024 if page.html else 0
    if size_kb:
        status = "pass" if size_kb < 100 else ("warn" if size_kb < 300 else "fail")
        issues.append(_issue("html-size", "HTML payload size", status, f"{size_kb:.0f} KB", url))

    # Compression
    encoding = page.headers.get("Content-Encoding", "")
    if encoding in ("gzip", "br"):
        issues.append(_issue("compression-ok", "Compression", "pass", f"Served with {encoding} compression.", url))
    else:
        issues.append(_issue("compression-missing", "Compression", "warn",
                              "No gzip/brotli compression detected on this response.", url))

    # Caching headers
    cache_control = page.headers.get("Cache-Control", "")
    if cache_control:
        issues.append(_issue("cache-ok", "Cache headers", "pass", f"Cache-Control: {cache_control}", url))
    else:
        issues.append(_issue("cache-missing", "Cache headers", "warn", "No Cache-Control header set.", url))

    if not page.soup:
        return issues

    # Render-blocking resources: sync scripts in <head>
    head = page.soup.head
    if head:
        blocking_scripts = [s for s in head.find_all("script", src=True)
                             if not s.get("async") and not s.get("defer")]
        if blocking_scripts:
            issues.append(_issue("render-blocking-js", "Render-blocking scripts", "warn",
                                  f"{len(blocking_scripts)} script(s) in <head> without async/defer.", url))
        else:
            issues.append(_issue("render-blocking-js-ok", "Render-blocking scripts", "pass",
                                  "No blocking head scripts detected.", url))

    # Images missing explicit dimensions (layout shift risk)
    imgs = page.soup.find_all("img")
    if imgs:
        missing_dims = sum(1 for i in imgs if not (i.get("width") and i.get("height")))
        pct = round(missing_dims / len(imgs) * 100)
        status = "pass" if pct == 0 else ("warn" if pct < 50 else "fail")
        issues.append(_issue("img-dims", "Image dimensions set", status,
                              f"{missing_dims}/{len(imgs)} images ({pct}%) missing width/height attributes.", url))

    # Total external script count (proxy for JS weight)
    scripts = page.soup.find_all("script", src=True)
    status = "pass" if len(scripts) <= 6 else ("warn" if len(scripts) <= 12 else "fail")
    issues.append(_issue("script-count", "External scripts", status, f"{len(scripts)} script files referenced.", url))

    return issues
