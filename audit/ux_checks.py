"""
ux_checks.py: phone-first navigation, brand consistency, forms, embeds, and
stale content. Fills the gaps that the per-page design checks and the link
checker do not cover.

All checks here are heuristics over the HTML we crawled. A real phone test is
still the final word on tap targets and layout; the PageSpeed integration
(pagespeed.py) adds Google's own mobile-usability audits on top.
"""

import concurrent.futures
import re
from datetime import date
from urllib.parse import urlparse

import requests

from audit.dates import extract_page_dates
from audit.guest_experience import _result
from audit.safety import assert_safe_url, UnsafeURLError
from audit.structure import SG_MOBILE, SG_BRAND, SG_LINKS

_TOGGLE_RE = re.compile(r"menu|nav-?toggle|hamburger|burger|navbar-toggle|mobile-?nav|drawer|offcanvas|off-canvas", re.I)
_GIVE_TEXT_RE = re.compile(r"\bgiv(?:e|ing)\b|donat|tithe|offering|generosity")
_GIVE_PROVIDER_RE = re.compile(
    r"givelify|tithe\.ly|tithely|pushpay|planning ?center|subsplash|stripe\.com|paypal|donorbox|ministrybrands|"
    r"breezechms|churchteams|zeffy|givemn|eservice|onlinegiving|realm\.|kindrid|securegive|vanco|givebutter|"
    r"anedot|app\.giving|/giving-?form|/give/", re.I)


def _toggle_present(doc):
    for tag in doc.soup.find_all(["button", "a", "div", "span", "label", "input", "summary"]):
        blob = " ".join([
            " ".join(tag.get("class", [])), tag.get("id", ""), tag.get("aria-label", ""),
            tag.get("aria-controls", ""), tag.get("data-toggle", ""), tag.get("data-target", ""),
        ])
        if _TOGGLE_RE.search(blob) and (tag.name in ("button", "label", "input", "summary") or tag.get("aria-label")
                                        or tag.get("aria-controls") or tag.get("data-toggle")):
            return True
    return False


def check_mobile_nav_giving(docs):
    home = docs[0]
    nav_links = [l for l in home.links if l["in_nav"] and not l["href"].startswith(("mailto:", "tel:"))]
    has_menu = len(nav_links) >= 3 and _toggle_present(home)

    give_link = next((l for l in home.links if l["in_nav"] and l["text"] and len(l["text"]) <= 30
                      and _GIVE_TEXT_RE.search(l["text"])), None)
    provider = any(_GIVE_PROVIDER_RE.search(l["href"]) for d in docs for l in d.links) or \
        any(_GIVE_PROVIDER_RE.search(src) for d in docs for src in d.iframes)

    fix = []
    if not has_menu:
        fix.append("Use a collapsing menu (hamburger) with 3 or more links so navigation fits a phone screen.")
    if not give_link:
        fix.append("Put Give in the header or menu so it is one tap from anywhere.")
    if not provider:
        fix.append("Use a mobile-ready giving platform and link straight to it. Then test a gift on a real phone.")
    return _result(
        "ux-mobile-nav-giving", "Phone-friendly menu and giving", SG_MOBILE,
        [("a menu with a mobile toggle and 3+ links", has_menu),
         ("a Give link in the header or menu", bool(give_link)),
         ("a giving platform (secure online giving form)", provider)],
        home.url, " ".join(fix) + " This is a markup check, so tap through the menus and giving form on a phone.",
    )


def _logo_src(doc):
    header = doc.soup.find("header") or doc.soup
    for img in header.find_all("img"):
        blob = " ".join([img.get("src", ""), img.get("alt", ""), " ".join(img.get("class", [])), img.get("id", "")])
        if re.search(r"logo|brand|site-?title", blob, re.I):
            return urlparse(img.get("src", "")).path.rsplit("/", 1)[-1].lower() or None
    return None


def _rel_text(tag):
    rel = tag.get("rel")
    return " ".join(rel) if isinstance(rel, list) else (rel or "")


def _favicon(doc):
    for link in doc.soup.find_all("link", href=True):
        if "icon" in _rel_text(link).lower():
            return urlparse(link["href"]).path.rsplit("/", 1)[-1].lower()
    return None


def _styles(doc):
    sheets = set()
    for link in doc.soup.find_all("link", href=True):
        if "stylesheet" in _rel_text(link).lower():
            sheets.add(urlparse(link["href"]).path.rsplit("/", 1)[-1].lower())
    return sheets


def check_brand_consistency(docs):
    """Compares logo, favicon, and stylesheets across pages. Returns None for a one-page crawl."""
    if len(docs) < 2:
        return None
    home = docs[0]
    logos = [_logo_src(d) for d in docs]
    seen_logos = {l for l in logos if l}
    logo_ok = bool(seen_logos) and len(seen_logos) == 1 and sum(1 for l in logos if l) >= max(2, len(docs) // 2)

    icons = {_favicon(d) for d in docs}
    favicon_ok = len(icons) == 1 and None not in icons

    home_styles = _styles(home)
    overlaps = []
    for d in docs[1:]:
        s = _styles(d)
        union = home_styles | s
        overlaps.append(len(home_styles & s) / len(union) if union else 1.0)
    styles_ok = bool(home_styles) and all(o >= 0.5 for o in overlaps)

    fix = []
    if not logo_ok:
        fix.append("Use the same logo in the header on every page (logos seen: "
                   + (", ".join(sorted(seen_logos)) if seen_logos else "none detected") + ").")
    if not favicon_ok:
        fix.append("Set one favicon site-wide.")
    if not styles_ok:
        fix.append("Pages load different stylesheets, which usually means inconsistent fonts and colors. Share one theme.")
    return _result(
        "ux-brand-consistency", "Same logo, favicon, and styles on every page", SG_BRAND,
        [("one logo across pages", logo_ok), ("one favicon across pages", favicon_ok),
         ("shared stylesheets and fonts across pages", styles_ok)],
        home.url, " ".join(fix),
    )


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

_SEARCH_FORM_RE = re.compile(r"search|login|log-in|signin|sign-in", re.I)


def _contact_forms(doc):
    forms = []
    for form in doc.soup.find_all("form"):
        blob = " ".join([form.get("role", ""), form.get("id", ""), " ".join(form.get("class", [])), form.get("action", "")])
        if _SEARCH_FORM_RE.search(blob) or form.find("input", attrs={"type": "search"}):
            continue
        if not form.find(["input", "textarea", "select"]):
            continue
        forms.append(form)
    return forms


def _field_labelled(form, field):
    if field.get("type") in ("hidden", "submit", "button", "image", "reset"):
        return True
    if field.get("aria-label") or field.get("aria-labelledby") or field.get("title"):
        return True
    fid = field.get("id")
    if fid and form.find("label", attrs={"for": fid}):
        return True
    return field.find_parent("label") is not None


def check_forms(docs):
    """Contact paths and form quality. Returns an issue for the whole site."""
    forms = [(d, f) for d in docs for f in _contact_forms(d)]
    has_embed_form = any(re.search(r"forms\.gle|docs\.google\.com/forms|typeform|jotform|wufoo|formstack|cognito|"
                                   r"planningcenter|churchcenter|ministryplatform|hubspot", s, re.I)
                         for d in docs for s in d.iframes)
    has_contact_link = any(l["href"].startswith(("mailto:", "tel:")) for d in docs for l in d.links)
    page = (forms[0][0].url if forms else docs[0].url)

    components = [("a way to reach the church (form, email link, or phone link)",
                   bool(forms or has_embed_form or has_contact_link))]
    if forms:
        fields = [(f, fld) for _, f in forms for fld in f.find_all(["input", "textarea", "select"])]
        unlabeled = [fld for f, fld in fields if not _field_labelled(f, fld)]
        components.append(("every form field has a label", not unlabeled))
        components.append(("every form has a submit button and a destination",
                           all((f.find(["button", "input"], attrs={"type": "submit"}) or f.find("button"))
                               and (f.get("action") or f.get("data-action") or f.get("hx-post") or f.find("input", attrs={"name": "_wpcf7"}))
                               for _, f in forms)))
    fix = ("Make sure guests have an obvious way to reach you. Label every form field and confirm each form "
           "submits and sends a confirmation. This check reads the markup, so submit each form once to be sure.")
    return _result("ux-forms", "Contact and forms", SG_LINKS, components, page, fix)


# ---------------------------------------------------------------------------
# Embeds (iframes)
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 6
MAX_EMBEDS = 8
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _fetch_embed(url):
    try:
        assert_safe_url(url)
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True, headers={"User-Agent": _UA})
        resp.close()
        return resp.status_code, None
    except UnsafeURLError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, str(exc)


def check_embeds(docs, fetch=None):
    """Requests each embedded iframe source once. Returns None when the site has no embeds."""
    fetch = fetch or _fetch_embed
    embeds = []
    for d in docs:
        for src in d.iframes:
            if src.startswith("//"):
                src = "https:" + src
            if src.startswith(("http://", "https://")) and src not in {e[1] for e in embeds}:
                embeds.append((d.url, src))
    if not embeds:
        return None
    embeds = embeds[:MAX_EMBEDS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_EMBEDS) as pool:
        outcomes = list(pool.map(fetch, [e[1] for e in embeds]))

    # 403/429 from big platforms usually means "bot", not "broken", so it is not counted.
    broken = [(page, src, code, err) for (page, src), (code, err) in zip(embeds, outcomes)
              if err or (code and (code >= 500 or code in (404, 410)))]
    if broken:
        page, src, code, err = broken[0]
        listing = "; ".join(f"{s} ({'unreachable' if e else c})" for _, s, c, e in broken[:3])
        return {"id": "ux-embeds", "label": "Embedded content", "status": "fail", "points": 0.0,
                "detail": f"{len(broken)} of {len(embeds)} embeds fail to load: {listing}. "
                          "Broken maps, videos, or forms look like dead ends to a visitor.",
                "page": page, "group": SG_LINKS, "site_level": True}
    return {"id": "ux-embeds", "label": "Embedded content", "status": "pass", "points": 1.0,
            "detail": f"All {len(embeds)} embeds (maps, video, forms) responded without errors.",
            "page": embeds[0][0], "group": SG_LINKS, "site_level": True}


# ---------------------------------------------------------------------------
# Fresh content
# ---------------------------------------------------------------------------

_EVENT_PAGE_RE = re.compile(r"event|calendar|upcoming|happening|announcement|news")
_COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\(c\)\s*)?(?:\d{4}\s*[-–]\s*)?(20\d{2})", re.I)


def check_fresh_content(docs, today=None):
    """Looks for outdated event dates and an old copyright year. None when neither can be judged."""
    today = today or date.today()
    components, notes, page = [], [], docs[0].url

    event_dates = []
    for d in docs:
        if _EVENT_PAGE_RE.search(d.path) or _EVENT_PAGE_RE.search(d.headings):
            dates = extract_page_dates(d)
            if dates:
                event_dates += [(x, d.url) for x in dates]
    if event_dates:
        newest, newest_url = max(event_dates)
        upcoming = newest >= today
        components.append(("event or news dates that are current", upcoming))
        if not upcoming:
            page = newest_url
            notes.append(f"The newest date on the events or news pages is {newest.isoformat()}, "
                         f"{(today - newest).days} days ago. Remove or update past events.")

    years = [int(m.group(1)) for d in docs[:3] for m in _COPYRIGHT_RE.finditer(d.raw_text + " " + d.html[-3000:])]
    if years:
        ok = max(years) >= today.year - 1
        components.append(("a current copyright year", ok))
        if not ok:
            notes.append(f"The footer says {max(years)}, which signals an unmaintained site.")

    if not components:
        return None
    return _result("ux-fresh-content", "Current events and footer", SG_LINKS, components, page, " ".join(notes))
