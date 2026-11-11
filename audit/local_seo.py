"""
local_seo.py: how findable the church is locally, judged from the website alone.

Google Business Profile itself (claimed, verified, hours, photos) lives inside
Google and cannot be read from the site. What the site CAN show is whether it
is wired to the profile and whether its details agree with it:

  - a link to the profile or its review page
  - Church / LocalBusiness schema markup with an address and hours
  - one consistent phone number across pages

The report says plainly that the profile itself must be confirmed in Google.
"""

import re
from urllib.parse import urlparse, parse_qs

from audit.guest_experience import _result, extract_city
from audit.structure import SG_LOCAL, SG_SEO

_GBP_HREF_RE = re.compile(
    r"g\.page|google\.[a-z.]+/maps/place|maps\.app\.goo\.gl|goo\.gl/maps|search\.google\.com/local|g\.co/kgs|"
    r"business\.google\.com|google\.[a-z.]+/maps\?cid=|g\.page/r/", re.I)
_LOCAL_TYPES = {"church", "placeofworship", "localbusiness", "religiousorganization", "organization",
                "placeofworshipwebsite", "placeofworship", "nonprofit", "ngo"}
_PHONE_RE = re.compile(r"(?<!\d)\(?(\d{3})\)?[-.\s](\d{3})[-.\s](\d{4})(?!\d)")


def _types(obj):
    t = obj.get("@type")
    t = t if isinstance(t, list) else [t]
    return {str(x).lower().rsplit("/", 1)[-1] for x in t if x}


def _local_schema(docs):
    """Returns (has_schema_with_address, has_hours, first_doc_url)."""
    has_addr = has_hours = False
    url = None
    for d in docs:
        for obj in d.jsonld:
            if _types(obj) & _LOCAL_TYPES:
                addr = obj.get("address")
                if addr and (isinstance(addr, str) or addr.get("streetAddress") or addr.get("addressLocality")):
                    has_addr = True
                    url = url or d.url
                if obj.get("openingHours") or obj.get("openingHoursSpecification") or obj.get("event"):
                    has_hours = True
                    url = url or d.url
    return has_addr, has_hours, url


def _phones(docs):
    phones = {}
    for d in docs:
        for link in d.links:
            if link["href"].startswith("tel:"):
                digits = re.sub(r"\D", "", link["href"])[-10:]
                if len(digits) == 10:
                    phones.setdefault(digits, set()).add(d.url)
        for m in _PHONE_RE.finditer(d.raw_text):
            phones.setdefault("".join(m.groups()), set()).add(d.url)
    return phones


def check_google_profile(docs):
    home = docs[0]
    gbp_link = next(((d, l) for d in docs for l in d.links if _GBP_HREF_RE.search(l["href"])), None)
    has_addr, has_hours, schema_url = _local_schema(docs)
    phones = _phones(docs)
    phone_ok = 1 <= len(phones) <= 2

    fix = []
    if not gbp_link:
        fix.append("Link to your Google Business Profile (a Google Maps place link or a review link) from the footer or contact page.")
    if not has_addr:
        fix.append("Add Church or LocalBusiness schema markup with your street address.")
    if not has_hours:
        fix.append("Include service hours in that schema markup so Google can show them.")
    if not phones:
        fix.append("List your phone number as a tap-to-call link.")
    elif len(phones) > 2:
        fix.append(f"{len(phones)} different phone numbers appear across the site. Use one main number everywhere, matching your Google profile.")
    fix.append("Whether the profile is claimed and verified, and its hours and photos, cannot be seen from the website. "
               "Confirm them at business.google.com.")

    return _result(
        "tech-google-profile", "Google Business Profile wiring and consistent contact details", SG_LOCAL,
        [("a link to your Google Business Profile or review page", bool(gbp_link)),
         ("Church or LocalBusiness schema with an address", has_addr),
         ("service hours in schema markup", has_hours),
         ("one consistent phone number across the site", phone_ok)],
        (gbp_link[0].url if gbp_link else (schema_url or home.url)), " ".join(fix),
    )


def check_local_keywords(docs):
    """Is the city named where search engines and people look first?"""
    home = docs[0]
    city = extract_city(docs)
    if not city:
        return _result(
            "tech-local-keywords", "City named in the title and headline", SG_LOCAL,
            [("a city and state on the homepage", False)], home.url,
            "Put your city and state on the homepage (header or footer) and in the page title, "
            "for example 'Grace Church in Raleigh, NC'.",
        )
    c = city.lower()
    meta = home.soup.find("meta", attrs={"name": "description"})
    desc = (meta.get("content", "") if meta else "").lower()
    h1 = " ".join(h.get_text(" ", strip=True) for h in home.soup.find_all("h1")).lower()
    return _result(
        "tech-local-keywords", "City named in the title and headline", SG_LOCAL,
        [(f"{city} in the homepage title", c in home.title.lower()),
         (f"{city} in the main heading or meta description", c in h1 or c in desc)],
        home.url,
        f"Name your city where search engines look first, for example 'Church in {city}' in the title tag, "
        "main heading, and meta description.",
    )


def check_url_structure(docs):
    """Clean, readable URLs. Returns an issue scored by the share of tidy URLs."""
    flagged = []
    for d in docs:
        u = urlparse(d.url)
        reasons = []
        q = parse_qs(u.query)
        if any(k in q for k in ("p", "page_id", "id", "post", "cat", "pid", "tag_ID")):
            reasons.append("numeric ID in query string")
        if re.search(r"[A-Z]", u.path):
            reasons.append("uppercase letters")
        if "_" in u.path:
            reasons.append("underscores")
        if len(u.path) > 75:
            reasons.append("very long path")
        if len([s for s in u.path.split("/") if s]) > 4:
            reasons.append("more than 4 levels deep")
        if reasons:
            flagged.append((d.url, reasons))
    n = len(docs)
    tidy = (n - len(flagged)) / n
    if not flagged:
        return {"id": "seo-url-structure", "label": "Clean URL structure", "status": "pass", "points": 1.0,
                "detail": f"All {n} crawled URLs are short, lowercase, and readable.", "page": docs[0].url,
                "group": SG_SEO, "site_level": True}
    url, reasons = flagged[0]
    status = "warn" if tidy >= 0.5 else "fail"
    return {"id": "seo-url-structure", "label": "Clean URL structure", "status": status, "points": round(tidy, 2),
            "detail": f"{len(flagged)} of {n} URLs are hard to read (for example {url}: {', '.join(reasons)}). "
                      "Use short, lowercase, descriptive paths such as /plan-your-visit.",
            "page": url, "group": SG_SEO, "site_level": True}


def check_duplicate_titles(docs):
    """Unique title tags. None when there is only one page to compare."""
    if len(docs) < 2:
        return None
    seen = {}
    for d in docs:
        t = d.title.strip().lower()
        if t:
            seen.setdefault(t, []).append(d.url)
    dupes = {t: urls for t, urls in seen.items() if len(urls) > 1}
    if not dupes:
        return {"id": "seo-unique-titles", "label": "Unique page titles", "status": "pass", "points": 1.0,
                "detail": "Every crawled page has its own title.", "page": docs[0].url, "group": SG_SEO,
                "site_level": True}
    title, urls = max(dupes.items(), key=lambda kv: len(kv[1]))
    affected = sum(len(u) for u in dupes.values())
    return {"id": "seo-unique-titles", "label": "Unique page titles", "status": "warn",
            "points": round(1 - affected / len(docs), 2),
            "detail": f"{affected} of {len(docs)} pages share a title with another page (for example "
                      f"\"{title[:60]}\" on {len(urls)} pages). Give each page a title that says what it is.",
            "page": urls[0], "group": SG_SEO, "site_level": True}


_ANALYTICS_RE = re.compile(
    r"(googletagmanager\.com|google-analytics\.com|gtag\(|G-[A-Z0-9]{6,}|UA-\d{4,}|GTM-[A-Z0-9]{4,})")


def check_analytics(docs):
    page = next((d for d in docs if _ANALYTICS_RE.search(d.html)), None)
    if page:
        return {"id": "tech-analytics", "label": "Analytics tracking", "status": "pass", "points": 1.0,
                "detail": "Google Analytics or Tag Manager tracking detected.", "page": page.url,
                "group": SG_SEO, "site_level": True}
    return {"id": "tech-analytics", "label": "Analytics tracking", "status": "warn", "points": 0.0,
            "detail": "No Google Analytics or Tag Manager tracking detected, so visits and ad results "
                      "cannot be measured.", "page": docs[0].url, "group": SG_SEO, "site_level": True}
