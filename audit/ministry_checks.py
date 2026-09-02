"""
ministry_checks.py — signals specific to church/ministry websites that a
generic SEO/performance tool wouldn't know to look for.

These are business-relevant, not technical-failure checks, so they only ever
score pass/warn (never fail) — a missing sermon archive isn't "broken," it's
a missed opportunity worth flagging to a prospect.

Runs across ALL crawled pages combined (not just the homepage), since a
ministry often puts giving, sermons, or staff bios on a dedicated subpage
rather than the homepage itself.
"""

import re

_TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b", re.IGNORECASE)
_ZIP_RE = re.compile(r"\b\d{5}(-\d{4})?\b")
_STREET_RE = re.compile(
    r"\b\d+\s+[\w\s]{2,30}\b(street|st\.?|avenue|ave\.?|road|rd\.?|"
    r"boulevard|blvd\.?|drive|dr\.?|lane|ln\.?|way|circle|cir\.?)\b",
    re.IGNORECASE,
)
_ANALYTICS_RE = re.compile(
    r"(googletagmanager\.com|google-analytics\.com|gtag\(|G-[A-Z0-9]{6,}|UA-\d{4,}|GTM-[A-Z0-9]{4,})"
)

_KEYWORDS = {
    "donate": ["give", "giving", "donate", "donation", "tithe", "generosity"],
    "sermons": ["sermon", "sermons", "messages", "watch", "listen", "media", "podcast"],
    "staff": ["staff", "pastor", "leadership", "our team", "meet the team", "elders", "about us"],
    "service_words": ["service", "worship", "sunday", "gather"],
}


def _issue(id_, label, status, detail, page):
    return {"id": id_, "label": label, "status": status, "detail": detail, "page": page}


def _any_link_or_text_matches(pages, keywords):
    """Returns the first page where link text or visible text contains any keyword."""
    for page in pages:
        if not page.soup:
            continue
        for a in page.soup.find_all("a"):
            text = a.get_text(separator=" ", strip=True).lower()
            if any(k in text for k in keywords):
                return page.url
        body_text = page.soup.get_text(separator=" ", strip=True).lower()
        if any(k in body_text for k in keywords):
            return page.url
    return None


def check_site(pages):
    issues = []
    homepage = pages[0].url if pages else ""

    # Giving / donation link findability
    found_at = _any_link_or_text_matches(pages, _KEYWORDS["donate"])
    if found_at:
        issues.append(_issue("ministry-donate", "Giving / donate link", "pass",
                              "Found a giving-related link or mention.", found_at))
    else:
        issues.append(_issue("ministry-donate", "Giving / donate link", "warn",
                              "No giving/donate link or mention found across crawled pages — "
                              "this is often the #1 revenue-impacting fix for a church site.", homepage))

    # Service times
    time_page = None
    for page in pages:
        if not page.soup:
            continue
        text = page.soup.get_text(separator=" ", strip=True).lower()
        if _TIME_RE.search(text) and any(k in text for k in _KEYWORDS["service_words"]):
            time_page = page.url
            break
    if time_page:
        issues.append(_issue("ministry-service-times", "Service times", "pass",
                              "Found service times near worship-related text.", time_page))
    else:
        issues.append(_issue("ministry-service-times", "Service times", "warn",
                              "Couldn't find clear service times — a first-time visitor may not "
                              "know when to show up.", homepage))

    # Physical location / address
    loc_page = None
    for page in pages:
        if not page.soup:
            continue
        text = page.soup.get_text(separator=" ", strip=True)
        has_map = bool(page.soup.find("iframe", src=lambda s: s and "google.com/maps" in s))
        if has_map or (_STREET_RE.search(text) and _ZIP_RE.search(text)):
            loc_page = page.url
            break
    if loc_page:
        issues.append(_issue("ministry-location", "Physical location", "pass",
                              "Found an address or embedded map.", loc_page))
    else:
        issues.append(_issue("ministry-location", "Physical location", "warn",
                              "No street address or map found — makes it harder for first-time "
                              "visitors to find you.", homepage))

    # Sermon / message archive
    found_at = _any_link_or_text_matches(pages, _KEYWORDS["sermons"])
    if found_at:
        issues.append(_issue("ministry-sermons", "Sermon / message archive", "pass",
                              "Found a sermons/messages/media link.", found_at))
    else:
        issues.append(_issue("ministry-sermons", "Sermon / message archive", "warn",
                              "No sermon or message archive found — a common way visitors "
                              "'try before they come'.", homepage))

    # Staff / leadership bios
    found_at = _any_link_or_text_matches(pages, _KEYWORDS["staff"])
    if found_at:
        issues.append(_issue("ministry-staff", "Staff / leadership page", "pass",
                              "Found a staff, pastor, or leadership page.", found_at))
    else:
        issues.append(_issue("ministry-staff", "Staff / leadership page", "warn",
                              "No staff or leadership bios found — visitors often want to "
                              "know who they'd be meeting before they show up.", homepage))

    # Analytics / ad tracking present (relevant given Between Sundays runs Google Ads for clients)
    analytics_page = None
    for page in pages:
        if page.html and _ANALYTICS_RE.search(page.html):
            analytics_page = page.url
            break
    if analytics_page:
        issues.append(_issue("ministry-analytics", "Analytics tracking", "pass",
                              "Google Analytics/Tag Manager tracking detected.", analytics_page))
    else:
        issues.append(_issue("ministry-analytics", "Analytics tracking", "warn",
                              "No Google Analytics/Tag Manager tracking detected — traffic and "
                              "ad performance can't be measured without it.", homepage))

    return issues
