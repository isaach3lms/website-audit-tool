"""
guest_experience.py: the visitor-facing checks for church/ministry websites.

Answers one question: could a nervous first-time visitor decide to walk in the
door using only this website? Fourteen checks, filed into the sub-sections
defined in structure.py (First-Time Visitor and Clarity, Essential Content and
Messaging, plus real photos under User Experience and Design).

Like the old ministry checks these are business signals, not technical
failures, so a check never scores "fail". Each check is made of components
(for example the kids check needs programs, safety/check-in details, and how
kids are placed):

  all components found   -> pass  (1.0 points)
  some components found  -> warn  (found / total points)
  nothing found          -> warn  (0 points)

Scoring honors the optional "points" key on an issue (see scoring.py), so a
site that covers half of a topic scores better than one that ignores it, while
the label shown to the reader stays pass/notice like every other check.

These are text-and-markup heuristics (no headless browser, no image analysis).
They run across ALL crawled pages combined, because a church often keeps its
answers on a Plan Your Visit page rather than the homepage. Anything living on
a page the crawl did not reach will look missing.
"""

import re
from urllib.parse import urljoin, urlparse

from audit.pagedoc import Doc as _Doc, normalize as _normalize, search as _search, \
    search_near as _search_near, find_link as _find_link
from audit.structure import (
    SG_FIVE, SG_LOGISTICS, SG_KIDS, SG_WELCOME, SG_SERVICE, SG_EXPECT, SG_BELIEFS, SG_BRAND,
)

CATEGORY = "Guest Experience"


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------

def _result(id_, label, group, components, page_url, fix="", tip=""):
    """
    components: list of (name, found_bool). Builds the issue dict.
    Extra keys beyond the usual {id, label, status, detail, page}:
      group      -> which sub-section it belongs to (see structure.py)
      points     -> 0.0 to 1.0, used by scoring.score_from_issues
      site_level -> shown in the report even when it passes
    """
    found = [n for n, ok in components if ok]
    missing = [n for n, ok in components if not ok]

    if not missing:
        status, points = "pass", 1.0
        detail = "Found: " + ", ".join(found) + "."
        if tip:
            detail += " " + tip
    else:
        status, points = "warn", round(len(found) / len(components), 2)
        if found:
            detail = f"Found: {', '.join(found)}. Missing: {', '.join(missing)}."
        else:
            detail = f"Not found: {', '.join(missing)}."
        if fix:
            detail += " " + fix

    return {"id": id_, "label": label, "status": status, "detail": detail,
            "page": page_url, "group": group, "points": points, "site_level": True}


# ---------------------------------------------------------------------------
# Shared patterns
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"(?<![\w:])\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)(?![a-z])|\b\d{1,2}(?::\d{2})?\s?o'?clock\b")
_SERVICE_WORD_RE = re.compile(r"service|worship|sunday|gather|mass|sermon|morning|saturday|wednesday")

_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
           "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
_AMBIGUOUS_STATES = {"OR", "IN", "ME", "OK", "HI", "ID", "LA", "DE", "MA", "PA"}
_CITY_STATE_RE = re.compile(
    r"(?:^|[\s,|•·-])((?:[A-Z][A-Za-z.'-]+)(?: [A-Z][A-Za-z.'-]+)?),\s*(" + "|".join(_STATES) + r")\b(\s+\d{5})?"
)
_CITY_PREFIXES = {"new", "north", "south", "east", "west", "st.", "saint", "san", "santa", "los", "las", "fort",
                  "mount", "mt.", "lake", "port", "wake", "el", "la", "palm", "long", "grand", "bay", "cape",
                  "rock", "red", "big", "little", "old", "high", "glen", "boca", "winston", "chapel", "apex"}


def extract_city(docs):
    """Best-effort city name (original case) from JSON-LD or a 'City, ST' pattern on the first pages."""
    for d in docs[:3]:
        for obj in d.jsonld:
            addr = obj.get("address")
            if isinstance(addr, dict) and isinstance(addr.get("addressLocality"), str):
                return addr["addressLocality"].strip()
    for d in docs[:3]:
        for m in _CITY_STATE_RE.finditer(d.raw_text):
            city, state, zip_ = m.group(1), m.group(2), m.group(3)
            if state in _AMBIGUOUS_STATES and not zip_:
                continue
            words = city.split(" ")
            if len(words) == 2 and words[0].lower() not in _CITY_PREFIXES:
                city = words[1]
            return city
    return None


# ---------------------------------------------------------------------------
# First-Time Visitor and Clarity: the 5-second test
# ---------------------------------------------------------------------------

_CHURCH_NAME_RE = re.compile(
    r"church|chapel|cathedral|fellowship|parish|tabernacle|ministries|assembly|congregation|community|"
    r"baptist|methodist|lutheran|presbyterian|bible|temple|vineyard|calvary|worship center|christian"
)
_DENOM_RE = re.compile(
    r"\b(?:baptist|methodist|catholic|lutheran|presbyterian|pentecostal|assemblies of god|non-?denominational|"
    r"anglican|episcopal|church of christ|evangelical|reformed|orthodox|nazarene|vineyard|calvary|covenant|"
    r"congregational|adventist|mennonite|quaker|church of god|foursquare|charismatic|interdenominational|"
    r"united church|disciples of christ|free church|bible church|apostolic|wesleyan|moravian|a\.?m\.?e\.?|"
    r"pca|lcms|elca|sbc|umc|cbf|pcusa)\b"
)
_NEXT_STEP_RE = re.compile(
    r"plan (?:your|a) (?:first )?(?:visit|sunday)|new here|i'?m new|im new|join us|visit(?: us)?\b|what to expect|"
    r"get directions|watch (?:live|online)|service times?|get connected|start here|find your place|first[- ]time|"
    r"come (?:visit|see|worship)|contact us"
)


def _check_five_second(docs, home):
    name_ok = bool(home.title and _CHURCH_NAME_RE.search(_normalize(home.title))) or bool(
        _CHURCH_NAME_RE.search(_normalize(" ".join(h.get_text(" ", strip=True) for h in home.soup.find_all("h1")))))
    city_ok = bool(extract_city([home]))
    denom_ok = bool(_DENOM_RE.search(home.text))
    times_ok = bool(_search_near([home], _TIME_RE, _SERVICE_WORD_RE, 150)[0])
    cta_ok = any(
        l["text"] and len(l["text"]) <= 40 and _NEXT_STEP_RE.search(l["text"]) and (l["in_nav"] or i < 25)
        for i, l in enumerate(home.links) if not l["href"].startswith(("mailto:", "tel:"))
    )
    return _result(
        "guest-five-second", "5-second test: can a stranger tell who, where, when, and what next?", SG_FIVE,
        [("church name", name_ok), ("city and state", city_ok), ("denomination or tradition", denom_ok),
         ("service times", times_ok), ("a clear next step (plan a visit, new here, directions)", cta_ok)],
        home.url,
        "A stranger should see all five on the homepage without scrolling on a phone. "
        "This reads the page text, so confirm on a real phone.",
    )


_ARRIVAL_RE = re.compile(
    r"\barrive|doors? open|\bcoffee\b|check[- ]?in|come early|minutes? (?:before|early|prior)|"
    r"pre[- ]?service|welcome (?:team|center|desk)|\bgreeters?\b|get settled|grab a (?:coffee|cup)|"
    r"\bbreakfast\b|\bdonuts?\b|fellowship time|connection time|kids? check"
)


def _check_service_times(docs, home):
    times_here = bool(_search_near([home], _TIME_RE, _SERVICE_WORD_RE, 150)[0])
    arrival_here = bool(_search([home], _ARRIVAL_RE)[0])

    fix = "Put the weekly times in a prominent spot on the homepage. "
    if not times_here:
        elsewhere, _ = _search_near(docs, _TIME_RE, _SERVICE_WORD_RE, 150)
        if elsewhere:
            fix = f"Times appear on {elsewhere.url} but not on the homepage, so guests have to hunt for them. "
    fix += "Add when to arrive if there is pre-service coffee or kids check-in."

    return _result(
        "guest-service-times", "Service times and arrival guidance", SG_SERVICE,
        [("service times on the homepage", times_here),
         ("arrival guidance (coffee, kids check-in)", arrival_here)],
        home.url, fix,
    )


_WEEKDAY_CONTEXT_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|midweek|mid-week|weeknight|bible study|prayer (?:meeting|night)|"
    r"small groups?|youth group)\b")
_SPECIAL_RE = re.compile(
    r"christmas eve|\beaster\b|good friday|maundy|holy week|ash wednesday|\badvent\b|thanksgiving|special services?|"
    r"holiday services?|palm sunday|new year'?s eve|watch night|\bchristmas\b|seasonal services?"
)


def _check_service_schedule(docs, home):
    sunday_doc, _ = _search_near(docs, _TIME_RE, re.compile(r"\bsundays?\b"), 120)
    mid_doc, _ = _search_near(docs, _TIME_RE, _WEEKDAY_CONTEXT_RE, 120)
    special_doc, _ = _search(docs, _SPECIAL_RE)
    return _result(
        "guest-service-schedule", "Sunday, midweek, and special service times", SG_SERVICE,
        [("Sunday times", bool(sunday_doc)), ("midweek times", bool(mid_doc)),
         ("special or holiday service info", bool(special_doc))],
        (sunday_doc or mid_doc or special_doc or home).url,
        "List every regular gathering with its time. If you only meet on Sundays, say so plainly, "
        "and post holiday service times before Christmas and Easter.",
    )


# ---------------------------------------------------------------------------
# Practical logistics
# ---------------------------------------------------------------------------

_STREET_RE = re.compile(
    r"\b\d{1,6}\s+(?:[a-z0-9.'-]+\s+){1,4}(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|"
    r"circle|cir|court|ct|highway|hwy|parkway|pkwy|pike|trail|trl|place|pl)\b"
)
_STATE_ZIP_RE = re.compile(r"\b[a-z]{2}\s+\d{5}(?:-\d{4})?\b|\b\d{5}(?:-\d{4})?\b")
_MAP_HREF_RE = re.compile(
    r"google\.[a-z.]+/maps|goo\.gl/maps|maps\.app\.goo\.gl|maps\.google\.|maps\.apple\.com|waze\.com|"
    r"bing\.com/maps|openstreetmap\.org", re.I)
_PARKING_RE = re.compile(
    r"\bparking\b|\bpark (?:in|on|at|near|behind|beside|along|across)\b|"
    r"\b(?:main|front|side|back|rear|east|west|north|south|visitors?|guest|accessible|church|sanctuary|welcome)"
    r" (?:entrance|door|doors)\b|\bwhich (?:door|entrance)\b|\benter (?:through|at|from|via|by)\b"
)


def _has_address(doc):
    if doc.soup.find("address") or "streetaddress" in doc.html.lower():
        return True
    return bool(_STREET_RE.search(doc.text) and _STATE_ZIP_RE.search(doc.text))


def _has_map_link(doc):
    if doc.soup.find("iframe", src=lambda s: s and _MAP_HREF_RE.search(s)):
        return True
    return any(_MAP_HREF_RE.search(link["href"]) for link in doc.links)


def _check_location_parking(docs, home):
    addr_doc = next((d for d in docs if _has_address(d)), None)
    map_doc = next((d for d in docs if _has_map_link(d)), None)
    park_doc, _ = _search(docs, _PARKING_RE)
    page = (addr_doc or map_doc or park_doc or home).url

    return _result(
        "guest-location-parking", "Location, map link, and parking", SG_LOGISTICS,
        [("street address", bool(addr_doc)),
         ("map link (Google Maps)", bool(map_doc)),
         ("parking or entrance notes", bool(park_doc))],
        page,
        "Link the address straight to Google Maps and say where to park and which door is best for guests.",
    )


_ENTRANCE_RE = re.compile(
    r"\b(?:main|front|side|back|rear|east|west|north|south|visitors?|guest|welcome|church|sanctuary|kids|children'?s?)"
    r" (?:entrance|door|doors)\b|\bwhich (?:door|entrance)\b|\benter (?:through|at|from|via|by)\b|"
    r"\b(?:look|watch) for (?:the|our)\b|\bfollow the signs\b|\bgreeters? (?:will|at|are)\b|\bcheck[- ]?in (?:desk|station|table)\b"
)
_ACCESS_RE = re.compile(
    r"wheelchair|\baccessible\b|accessibility|handicap(?:ped)?|\bada\b|\belevator\b|\bramp\b|hearing (?:loop|assist)|"
    r"assistive listening|large[- ]print|disabilit|special needs|sensory|mobility|reserved parking"
)


def _check_entrance_accessibility(docs, home):
    ent_doc, _ = _search(docs, _ENTRANCE_RE)
    acc_doc, _ = _search(docs, _ACCESS_RE)
    return _result(
        "guest-entrance-accessibility", "Building entrances and accessibility", SG_LOGISTICS,
        [("entrance guidance (which door, who greets you)", bool(ent_doc)),
         ("accessibility notes (wheelchair access, hearing assistance)", bool(acc_doc))],
        (ent_doc or acc_doc or home).url,
        "Tell guests which door to use and what accessibility help exists, such as step-free entry, "
        "reserved parking, or hearing assistance.",
    )


# ---------------------------------------------------------------------------
# Expectations and welcome
# ---------------------------------------------------------------------------

_LENGTH_DURATION = (
    r"(?:an? hour and a half|an? hour|one hour|1 hour|"
    r"\d{1,3}\s*(?:-|to)\s*\d{1,3}\s*(?:minutes?|mins?|hours?|hrs?)|\d{1,3}\s*(?:minutes?|mins?|hours?|hrs?))"
    # "about an hour from Charlotte" is a drive time, not a service length
    r"\b(?!\s*(?:from|away|drive|north|south|east|west|outside|of)\b)"
)
_LENGTH_RE = re.compile(
    r"\b(?:lasts?|lasting|takes?|typically|usually|generally)\s+(?:about\s+|around\s+|roughly\s+|approximately\s+)?"
    + _LENGTH_DURATION
    + r"|\b(?:service|services|worship|gathering|message|sunday|sundays)\s+(?:is|are|runs?|lasts?)\s+"
      r"(?:about\s+|around\s+|roughly\s+|approximately\s+)?" + _LENGTH_DURATION
    + r"|\b(?:ends?|over|out|finished|done|wraps? up|dismiss(?:ed)?)\s+(?:by|around|at|about)\s+\d{1,2}(?::\d{2})?\b"
    r"|\b(?:service|worship|gathering|message)\s+(?:length|duration)\b|\bhow long (?:is|does)\b"
)
_LENGTH_CONTEXT_RE = re.compile(r"service|worship|gathering|sunday|church|message|sermon|morning")


def _check_service_length(docs, home):
    doc, _ = _search_near(docs, _LENGTH_RE, _LENGTH_CONTEXT_RE, 120)
    return _result(
        "guest-service-length", "Service length", SG_SERVICE,
        [("how long the service runs", bool(doc))],
        (doc or home).url,
        "State how long a typical Sunday runs (for example, about 75 minutes) so guests can plan their morning.",
    )


_WEAR_RE = re.compile(
    r"come as you are|dress code|what to wear|what should i wear|wear (?:whatever|what)|"
    r"dress (?:casual|casually|comfortabl\w+|however|as you)|casual (?:dress|attire|clothes|clothing)|"
    r"\bjeans\b|\bsunday best\b|\bcome dressed\b|\battire\b|any(?:thing)? (?:you|that)(?:'re| are)? comfortable"
)


def _check_what_to_wear(docs, home):
    doc, _ = _search(docs, _WEAR_RE)
    return _result(
        "guest-what-to-wear", "What to wear", SG_EXPECT,
        [("dress guidance", bool(doc))],
        (doc or home).url,
        "Tell guests they can come as they are (casual, formal, or anything in between).",
    )


_STYLE_STRONG_RE = re.compile(
    r"\bchoir\b|\borgan\b|worship (?:band|team|leader)|\blive band\b|\bfull band\b|\bhymns?\b|"
    r"praise (?:and|&) worship|\borchestra\b|\bacoustic\b|\bgospel (?:music|choir|band)\b"
)
_STYLE_WEAK_RE = re.compile(r"\bcontemporary\b|\bmodern\b|\btraditional\b|\bblended\b|\bband\b|\bpiano\b|\bguitars?\b|\bdrums\b")
_MUSIC_CONTEXT_RE = re.compile(r"worship|music|singing|songs?|\bsing\b|musical")
_LYRICS_RE = re.compile(
    r"\blyrics?\b|on (?:the )?screens?\b|\bprojected\b|\bprojection\b|\bhymnals?\b|\bhymn ?books?\b|"
    r"\bsong ?books?\b|words (?:are )?(?:on|displayed|projected)|sing along|follow along"
)


def _check_vibe_music(docs, home):
    style_doc, _ = _search(docs, _STYLE_STRONG_RE)
    if not style_doc:
        style_doc, _ = _search_near(docs, _STYLE_WEAK_RE, _MUSIC_CONTEXT_RE, 80)
    lyrics_doc, _ = _search(docs, _LYRICS_RE)
    return _result(
        "guest-vibe-music", "Worship vibe and music style", SG_EXPECT,
        [("music style", bool(style_doc)), ("how lyrics are shown", bool(lyrics_doc))],
        (style_doc or lyrics_doc or home).url,
        "Say whether worship is a modern band, a choir, an organ, or a mix, and whether lyrics are on a screen or in a book.",
    )


_SINGLED_RE = re.compile(
    r"singled out|put (?:you )?on the spot|on the spot|no pressure|"
    r"(?:no ?one|nobody) will (?:ask|call|make|single|embarrass|put)|"
    r"(?:won't|will not|wont) (?:be )?(?:asked|called|singled|put|embarrassed|made|forced)|"
    r"(?:not|never) (?:be )?(?:asked|required|expected|forced|made|pressured|called) to "
    r"(?:stand|speak|give|introduce|participate|sing|raise|share|do anything)|"
    r"(?:don't|do not|dont) (?:have|need) to (?:stand|sing|give|introduce|participate|do anything|say|speak|raise|fill|share)|"
    r"no need to (?:stand|introduce|give|fill|sign|do anything)|"
    r"free to (?:just |simply )?(?:sit|watch|observe|listen)|at your own pace|no obligation|no strings|"
    r"\banonymous\b|\bembarrass"
)


def _check_not_singled_out(docs, home):
    doc, _ = _search(docs, _SINGLED_RE)
    return _result(
        "guest-no-spotlight", "No spotlight on guests", SG_WELCOME,
        [("promise that guests will not be put on the spot", bool(doc))],
        (doc or home).url,
        "Say plainly that guests will not be asked to stand, introduce themselves, or participate unless they want to.",
    )


# ---------------------------------------------------------------------------
# Family and kids
# ---------------------------------------------------------------------------

_KIDS_RE = re.compile(
    r"\bkids?\b|\bchildren\b|\bchildren's\b|\bnursery\b|\bchild ?care\b|\byouth\b|sunday school|\bpreschool\b|\btoddlers?\b|\binfants?\b"
)
_KIDS_SAFETY_RE = re.compile(
    r"check[- ]?in|checked in|background[- ]?check|screened|\bsafety\b|safe (?:environment|sanctuary|place)|\bsecure\b|"
    r"\bsecurity\b|pick[- ]?up (?:code|tag|process)|name ?tags?|child protection|trained (?:volunteers|staff)|"
    r"two[- ]adult|2[- ]adult"
)
_KIDS_PLACEMENT_RE = re.compile(
    r"stay (?:with you|in (?:the )?(?:service|sanctuary|worship))|join (?:you|the service|us)|dismiss(?:ed)?|"
    r"go to (?:class|their (?:class|room))|(?:during|while) (?:the )?(?:service|sermon|message|worship)|"
    r"classes? (?:for|during)|\bages? \d|age groups?|\bgrades?\b|birth (?:through|to)|\d(?:st|nd|rd|th) grade|"
    r"cry room|family (?:service|worship)"
)


def _check_children_youth(docs, home):
    prog_doc, _ = _search(docs, _KIDS_RE)
    safety_doc, _ = _search_near(docs, _KIDS_SAFETY_RE, _KIDS_RE, 200)
    place_doc, _ = _search_near(docs, _KIDS_PLACEMENT_RE, _KIDS_RE, 200)
    return _result(
        "guest-children-youth", "Children and youth programs", SG_KIDS,
        [("kids or youth programs", bool(prog_doc)),
         ("check-in and safety details", bool(safety_doc)),
         ("ages and how kids are placed (class or stay in service)", bool(place_doc))],
        (prog_doc or home).url,
        "Parents decide fast. Explain the age groups, how check-in and background checks work, "
        "and whether kids stay in the service or go to a class.",
    )


# ---------------------------------------------------------------------------
# Photos (filed under User Experience and Design)
# ---------------------------------------------------------------------------

_BG_URL_RE = re.compile(r"background(?:-image)?\s*:[^;]*url\(\s*['\"]?([^'\")]+)", re.I)
_NON_CONTENT_IMG_RE = re.compile(
    r"logo|icon|sprite|favicon|pixel|spacer|badge|avatar|emoji|arrow|bullet|social|facebook|instagram|twitter|"
    r"youtube|tiktok|tracking|1x1|blank|loading|qr[-_]?code|\.svg(?:\?|$)", re.I)
_STOCK_RE = re.compile(
    r"unsplash|pexels|shutterstock|istockphoto|\bistock|gettyimages|adobestock|stock\.adobe|depositphotos|pixabay|"
    r"freepik|dreamstime|123rf|bigstock|stocksy|stock[-_ ]?(?:photo|image)|\bstock\b|photo-\d{10,13}-[0-9a-f]{12}", re.I)
_REAL_CUE_RE = re.compile(
    r"congregation|sanctuary|our church|church (?:building|family|service)|building|campus|lobby|caf[eé]|coffee|"
    r"worship|pastor|volunteers?|\bteam\b|members?|baptism|\bkids\b|children|youth|potluck|picnic|gathering|\bstaff\b|"
    r"\bband\b|choir|greeters?", re.I)


def _content_images(docs):
    """Unique content images across the crawl, minus logos/icons/trackers."""
    seen, images = set(), []
    for d in docs:
        candidates = []
        for img in d.soup.find_all("img"):
            src = (img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                   or img.get("data-original") or "")
            if not src and img.get("srcset"):
                src = img["srcset"].split(",")[0].strip().split(" ")[0]
            fig = img.find_parent("figure")
            caption = fig.find("figcaption").get_text(" ", strip=True) if fig and fig.find("figcaption") else ""
            candidates.append((src, img.get("alt", ""), caption, img.get("width"), img.get("height"), " ".join(img.get("class", []))))
        for tag in d.soup.find_all(style=True):
            m = _BG_URL_RE.search(tag["style"])
            if m:
                candidates.append((m.group(1), "", "", None, None, ""))

        for src, alt, caption, w, h, cls in candidates:
            if not src or src.startswith("data:"):
                continue
            absolute = urljoin(d.url, src)
            if absolute in seen:
                continue
            seen.add(absolute)
            if _NON_CONTENT_IMG_RE.search(f"{absolute} {alt} {cls}"):
                continue
            if any(v and re.match(r"^\d+$", str(v)) and int(v) <= 80 for v in (w, h)):
                continue
            name = urlparse(absolute).path.rsplit("/", 1)[-1].lower()
            images.append({"src": absolute, "alt": _normalize(alt), "name": name,
                           "caption": _normalize(caption), "page": d.url})
    return images


def _check_real_photos(docs, home):
    images = _content_images(docs)
    stock = [i for i in images if _STOCK_RE.search(f"{i['src']} {i['alt']}")]
    cues = [i for i in images if _REAL_CUE_RE.search(f"{i['alt']} {i['name']} {i['caption']}")]

    fix_bits = []
    if len(images) < 3:
        fix_bits.append(f"Only {len(images)} content photo(s) found across the crawled pages.")
    if stock:
        fix_bits.append(f"{len(stock)} image(s) look like stock photos (for example {stock[0]['name'] or stock[0]['src']}).")
    if not cues:
        fix_bits.append("Describe real people and places in alt text and file names so they can be verified.")
    fix_bits.append("Show your actual congregation, building, and coffee area. This is a text and file-name check, so confirm by eye.")

    page = (stock[0]["page"] if stock else (cues[0]["page"] if cues else (images[0]["page"] if images else home.url)))
    return _result(
        "guest-real-photos", "Real photos, not stock", SG_BRAND,
        [("3+ content photos", len(images) >= 3),
         ("photos free of stock-library markers", not stock),
         ("descriptive alt text or file names (people, building, worship)", bool(cues))],
        page, " ".join(fix_bits),
    )


# ---------------------------------------------------------------------------
# Plain language
# ---------------------------------------------------------------------------

_JARGON = [
    "narthex", "nave", "liturgy", "liturgical", "eucharist", "communion", "sacrament", "sacraments", "benediction",
    "doxology", "invocation", "lectionary", "catechism", "vespers", "compline", "matins", "fellowship hall",
    "missional", "discipleship", "life group", "life groups", "connect group", "connect groups", "community group",
    "community groups", "koinonia", "altar call", "ordinance", "ordinances", "covenant membership", "tithe",
    "tithes", "tithing", "sanctification", "gospel-centered", "gospel centered",
    # institutional terms and heavy denominational acronyms
    "vestry", "sacristy", "chancel", "rector", "presbytery", "diocese", "synod", "parish hall",
    "vbs", "kidmin", "mops", "awana", "umw", "umm", "umyf", "lcms", "elca", "pcusa", "wmu", "cogic", "rcia", "cyo",
]
_JARGON_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(j) for j in sorted(_JARGON, key=len, reverse=True)) + r")(?![\w-])")
_EXPLAIN_RE = re.compile(
    r"glossary|church (?:terms|words|lingo|vocabulary)|\bjargon\b|what does .{1,50} mean|"
    r"in plain (?:english|language|terms)|in other words|new to church|never been to church|"
    r"vacation bible school|\([a-z ]{6,40}\)"
)


def _check_plain_language(docs, home):
    seen_terms, first_doc = [], None
    for d in docs:
        for m in _JARGON_RE.finditer(d.text):
            term = m.group(1)
            if term not in seen_terms:
                seen_terms.append(term)
            first_doc = first_doc or d
    explained = bool(_search(docs, _EXPLAIN_RE)[0])

    if len(seen_terms) >= 2 and not explained:
        sample = ", ".join(seen_terms[:6])
        return {"id": "guest-plain-language", "label": "Plain language", "status": "warn",
                "detail": f"Insider terms or acronyms used with no explanation or glossary: {sample}. "
                          "A newcomer will not know what these mean. Replace them with everyday words, "
                          "or add one-line definitions or a short glossary.",
                "page": first_doc.url, "group": SG_WELCOME, "points": 0.5, "site_level": True}

    if seen_terms:
        detail = (f"Church terms ({', '.join(seen_terms[:4])}) appear alongside explanations or in small numbers.")
    else:
        detail = "No unexplained church or religious jargon detected."
    return {"id": "guest-plain-language", "label": "Plain language", "status": "pass",
            "detail": detail, "page": (first_doc or home).url, "group": SG_WELCOME, "points": 1.0,
            "site_level": True}


# ---------------------------------------------------------------------------
# Plan a visit, beliefs, leadership
# ---------------------------------------------------------------------------

_VISIT_TEXT_RE = re.compile(
    r"plan (?:your|a) (?:first )?(?:visit|sunday)|i'?m new|im new|i am new|new here|are you new|first[- ]time|"
    r"first visit|your first (?:visit|sunday)|what to expect|new (?:to|at) (?:church|us|faith)|new (?:guests?|visitors?)|"
    r"visit us|\bvisitors?\b|start here|come visit|\bguests?\b|newcomers?"
)
_VISIT_PATH_RE = re.compile(
    r"/(?:visit|visiting|visit-us|plan-your-visit|plan-a-visit|planyourvisit|plan-visit|im-new|i-m-new|iam-new|"
    r"new-here|new-to-[a-z-]+|first-time(?:-visitors?|-guests?)?|first-visit|what-to-expect|start-here|new-guests?|"
    r"newcomers?|new-visitors?|guests?|visitors?|welcome|plan)/"
)
_VISIT_HEADING_RE = re.compile(
    r"plan (?:your|a) (?:first )?visit|i'?m new|new here|first[- ]time|what to expect|visit us|start here|new (?:to|at)"
)


def _check_plan_visit(docs, home):
    link_doc, link = _find_link([home], _VISIT_TEXT_RE, _VISIT_PATH_RE)
    deeper_doc, deeper_link = (None, None)
    if not link:
        deeper_doc, deeper_link = _find_link(docs[1:], _VISIT_TEXT_RE, _VISIT_PATH_RE)

    visit_page = next(
        (d for d in docs if _VISIT_PATH_RE.search(urlparse(d.url).path.lower() + "/") or _VISIT_HEADING_RE.search(d.headings)),
        None,
    )
    dedicated = bool(visit_page or link)

    components = [
        ("a Plan Your Visit or I'm New link on the homepage", bool(link)),
        ("a dedicated first-time guest page", dedicated),
    ]
    page = home.url
    if visit_page:
        page = visit_page.url
        topics = [
            bool(_search_near([visit_page], _TIME_RE, _SERVICE_WORD_RE, 150)[0]),
            _has_map_link(visit_page) or _has_address(visit_page) or bool(_PARKING_RE.search(visit_page.text)),
            bool(_KIDS_RE.search(visit_page.text)),
            bool(_WEAR_RE.search(visit_page.text) or _SINGLED_RE.search(visit_page.text)),
            bool(_STYLE_STRONG_RE.search(visit_page.text) or _LYRICS_RE.search(visit_page.text)),
        ]
        components.append(("first-time questions answered together on that page (3+ of times, directions, kids, what to wear, music)",
                           sum(topics) >= 3))

    fix = "Add a warm, easy-to-spot hub in the main menu that groups every first-time question into one guide."
    if not link and deeper_link:
        fix = (f"A visitor link exists on {deeper_doc.url} but not on the homepage. "
               "Put it in the main menu or hero so it is the first thing a guest sees.")
    if link and not link["in_nav"]:
        fix += " The homepage link is not in the header or menu, so consider making it more prominent."

    return _result("guest-plan-your-visit", "Plan Your Visit / I'm New page", SG_EXPECT,
                   components, page, fix)


_BELIEFS_RE = re.compile(
    r"statement of faith|what we believe|our beliefs?|\bwe believe\b|core (?:beliefs|convictions)|"
    r"\bdoctrin\w+|\bcreed\b|articles of faith|belief statement|confession of faith"
)
_BELIEFS_HREF_RE = re.compile(r"/(?:beliefs?|what-we-believe|statement-of-faith|our-beliefs?|doctrine|core-beliefs)/")
_MISSION_RE = re.compile(r"our mission|mission statement|\bour vision\b|vision statement|our purpose|core values|our values|\bour mission\b")
_PASTOR_RE = re.compile(r"\bpastors?\b")
_PASTOR_INTRO_RE = re.compile(
    r"\bmeet\b|\bwelcome\b|\bhello\b|\bhi\b|\bi'?m\b|\bi am\b|my name|a word from|message from|letter from|"
    r"\bstory\b|\bbio\b|\babout\b"
)
_PASTOR_LINK_RE = re.compile(
    r"meet (?:our |the )?(?:pastor|team|staff|leaders?)|(?:our|the) pastors?|pastor'?s? (?:welcome|message|letter|corner|bio)|"
    r"our (?:leadership|staff|team)|^leadership$|^staff$|about (?:our )?pastor|\belders\b"
)


def _check_beliefs_leadership(docs, home):
    belief_doc, _ = _search(docs, _BELIEFS_RE)
    if not belief_doc:
        belief_doc, _ = _find_link(docs, None, _BELIEFS_HREF_RE)

    mission_doc, _ = _search(docs, _MISSION_RE)
    if not mission_doc:
        mission_doc, _ = _find_link(docs, None, re.compile(r"/(?:mission|our-mission|vision|our-vision|values|our-values)/"))

    pastor_doc, _ = _search_near(docs, _PASTOR_RE, _PASTOR_INTRO_RE, 200)
    if not pastor_doc:
        pastor_doc, _ = _find_link(docs, _PASTOR_LINK_RE, None)
    video = any(d.has_video for d in docs if _PASTOR_RE.search(d.text))

    return _result(
        "guest-beliefs-leadership", "Beliefs, mission, and leadership", SG_BELIEFS,
        [("statement of faith", bool(belief_doc)), ("mission statement", bool(mission_doc)),
         ("pastor and leadership staff", bool(pastor_doc))],
        (belief_doc or mission_doc or pastor_doc or home).url,
        "Make your core beliefs, mission, and key staff easy to find, with a friendly pastor introduction, "
        "ideally a short welcome video.",
        tip="" if video else "Tip: a short pastor welcome video makes the introduction warmer.",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_CHECKS = [
    _check_five_second,
    _check_service_times,
    _check_service_schedule,
    _check_service_length,
    _check_location_parking,
    _check_entrance_accessibility,
    _check_children_youth,
    _check_what_to_wear,
    _check_vibe_music,
    _check_not_singled_out,
    _check_plain_language,
    _check_plan_visit,
    _check_beliefs_leadership,
    _check_real_photos,
]


def check_docs(docs):
    """docs: pre-built Doc list (first entry is treated as the homepage)."""
    if not docs:
        return []
    home = docs[0]
    return [check(docs, home) for check in _CHECKS]


def check_site(pages):
    """pages: crawled PageResult list (reachable pages only). Convenience wrapper over check_docs."""
    return check_docs([_Doc(p) for p in pages if p.soup])
