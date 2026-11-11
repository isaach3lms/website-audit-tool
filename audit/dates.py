"""
dates.py: finds explicit calendar dates (with a year) in page text.

Used to judge whether sermons, events, and footers look current. Only dates
that include a year are returned, because "Nov 2" alone cannot be placed.
"""

import re
from datetime import date

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))

# "Nov 2, 2026" / "November 2nd 2026"
_MDY_RE = re.compile(rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b", re.I)
# "2 November 2026"
_DMY_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\.?,?\s+(20\d{{2}})\b", re.I)
# "2026-11-02"
_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
# "11/02/2026"
_US_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")


def _safe(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def extract_dates(text):
    """Returns a list of datetime.date found in `text` (any order, may repeat)."""
    out = []
    for m in _MDY_RE.finditer(text):
        out.append(_safe(m.group(3), _MONTHS[m.group(1).lower()], m.group(2)))
    for m in _DMY_RE.finditer(text):
        out.append(_safe(m.group(3), _MONTHS[m.group(2).lower()], m.group(1)))
    for m in _ISO_RE.finditer(text):
        out.append(_safe(m.group(1), m.group(2), m.group(3)))
    for m in _US_RE.finditer(text):
        out.append(_safe(m.group(3), m.group(1), m.group(2)))
    return [d for d in out if d]


def extract_page_dates(doc):
    """Dates from visible text plus <time datetime="..."> attributes."""
    found = extract_dates(doc.raw_text)
    for t in doc.soup.find_all("time"):
        found += extract_dates(t.get("datetime", ""))
    return found
