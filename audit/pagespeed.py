"""
pagespeed.py: real mobile speed and accessibility numbers from Google PageSpeed Insights.

Why: a plain HTTP fetch cannot measure how fast a page paints on a phone or
run a proper accessibility scan. Google's free PageSpeed Insights API runs
Lighthouse on a simulated mid-range phone and returns both.

Setup: create a free API key (Google Cloud console, enable "PageSpeed Insights
API") and set it as the PAGESPEED_API_KEY environment variable. Without a key
the audit still runs and falls back to the built-in heuristics; the report
says so.

How it fits the request: the API call takes 15 to 40 seconds, so it starts in
a background thread BEFORE the crawl and the app collects the result at the
end, instead of adding its full length to the wait.
"""

import threading

import requests

from audit.structure import SG_SPEED, SG_A11Y, SG_MOBILE

API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
API_TIMEOUT = 55


def _call(url, api_key):
    params = [("url", url), ("strategy", "mobile"), ("key", api_key)] + [
        ("category", c) for c in ("performance", "accessibility", "seo", "best-practices")]
    resp = requests.get(API_URL, params=params, timeout=API_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


class PageSpeedJob:
    """Starts the API call immediately in a daemon thread. Call .result(timeout) later."""

    def __init__(self, url, api_key, fetch=None):
        self._out = {"status": "no_key", "message": None, "data": None}
        self._thread = None
        if not api_key:
            return
        self._out["status"] = "pending"
        fetch = fetch or _call

        def run():
            try:
                self._out.update(status="ok", data=fetch(url, api_key))
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else "?"
                msg = "the API key was rejected or the API is not enabled" if code in (400, 403) else \
                      "Google's daily quota was reached" if code == 429 else f"Google returned HTTP {code}"
                self._out.update(status="error", message=msg)
            except Exception as exc:  # network, JSON, anything: never break the audit over this
                self._out.update(status="error", message=str(exc)[:120])

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def result(self, timeout=40):
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                return {"status": "timeout", "message": "Google took too long to analyze this site", "data": None}
        return dict(self._out)


# ---------------------------------------------------------------------------
# Turning the API response into report issues
# ---------------------------------------------------------------------------

def _issue(id_, label, status, points, detail, page, group):
    return {"id": id_, "label": label, "status": status, "points": points, "detail": detail,
            "page": page, "group": group, "site_level": True}


def _band(score):
    return "pass" if score >= 90 else ("warn" if score >= 50 else "fail")


def _metric(audits, key, good, ok, fmt):
    a = audits.get(key) or {}
    value = a.get("numericValue")
    if value is None:
        return None
    status = "pass" if value <= good else ("warn" if value <= ok else "fail")
    return value, status, {"pass": 1.0, "warn": 0.5, "fail": 0.0}[status], fmt(value)


def to_issues(result, page_url):
    """
    Returns (issues_by_group, note).
      issues_by_group: {group_name: [issue, ...]} (empty when no data)
      note: one plain-language line about data availability, or None when fine
    """
    status = result.get("status")
    if status == "no_key":
        return {}, ("Real mobile speed and accessibility scores are off. Set the PAGESPEED_API_KEY environment "
                    "variable to add Google PageSpeed results. Speed below uses basic request-level signals only.")
    if status != "ok":
        return {}, f"Google PageSpeed data was unavailable ({result.get('message') or status}). Speed below uses basic request-level signals only."

    lh = (result.get("data") or {}).get("lighthouseResult") or {}
    cats, audits = lh.get("categories") or {}, lh.get("audits") or {}
    out = {SG_SPEED: [], SG_A11Y: [], SG_MOBILE: []}

    perf = (cats.get("performance") or {}).get("score")
    if perf is not None:
        s = round(perf * 100)
        out[SG_SPEED].append(_issue(
            "psi-performance", "Mobile performance score (Google PageSpeed)", _band(s), round(perf, 2),
            f"{s} out of 100 on a simulated phone. 90 and up is good.", page_url, SG_SPEED))
    for key, label, good, ok, fmt in (
        ("largest-contentful-paint", "Largest Contentful Paint (mobile)", 2500, 4000, lambda v: f"{v / 1000:.1f} s to show the main content. Under 2.5 s is good."),
        ("cumulative-layout-shift", "Layout shift (mobile)", 0.1, 0.25, lambda v: f"{v:.2f}. Under 0.10 means the page does not jump around while loading."),
        ("total-blocking-time", "Time until the page responds (mobile)", 200, 600, lambda v: f"{v:.0f} ms blocked. Under 200 ms is good."),
    ):
        m = _metric(audits, key, good, ok, fmt)
        if m:
            _, st, pts, detail = m
            out[SG_SPEED].append(_issue(f"psi-{key}", label, st, pts, detail, page_url, SG_SPEED))

    acc = (cats.get("accessibility") or {}).get("score")
    if acc is not None:
        s = round(acc * 100)
        failing = []
        for ref in (cats["accessibility"].get("auditRefs") or []):
            a = audits.get(ref.get("id"), {})
            if a.get("score") == 0 and a.get("title"):
                failing.append(a["title"])
        extra = f" Top failures: {'; '.join(failing[:4])}." if failing else ""
        out[SG_A11Y].append(_issue(
            "psi-accessibility", "Accessibility score (Google PageSpeed)", _band(s), round(acc, 2),
            f"{s} out of 100. 90 and up is good.{extra}", page_url, SG_A11Y))

    viewport = audits.get("viewport")
    if viewport and viewport.get("score") is not None:
        ok = viewport["score"] >= 1
        out[SG_MOBILE].append(_issue(
            "psi-viewport", "Mobile viewport (Google PageSpeed)", "pass" if ok else "fail", 1.0 if ok else 0.0,
            "Page is set up for phone screens." if ok else "Page is not optimized for phone screens.", page_url, SG_MOBILE))
    target = audits.get("target-size") or audits.get("tap-targets")
    if target and target.get("score") is not None:
        ok = target["score"] >= 1
        out[SG_MOBILE].append(_issue(
            "psi-tap-targets", "Tap targets big enough (Google PageSpeed)", "pass" if ok else "warn", 1.0 if ok else 0.3,
            "Buttons and links are large and spaced enough to tap." if ok
            else "Some buttons or links are too small or too close together to tap reliably on a phone.", page_url, SG_MOBILE))
    return out, None
