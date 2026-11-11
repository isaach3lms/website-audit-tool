"""
accessibility_checks.py: basic, request-level accessibility signals per page.

These catch the common, mechanical failures (missing language, unlabeled form
fields, links with no name, "click here" links). They are not a replacement
for a real accessibility audit; Google PageSpeed's accessibility score (see
pagespeed.py) adds a much deeper automated pass when an API key is set.

Image alt text is judged by seo_checks.py and filed under Accessibility by the
area builder, so it is not repeated here.
"""

import re

_VAGUE_RE = re.compile(r"^(?:click here|here|read more|learn more|more|link|this)$", re.I)


def _issue(id_, label, status, detail, page):
    return {"id": id_, "label": label, "status": status, "detail": detail, "page": page}


def check_page(page):
    issues = []
    if not page.soup:
        return issues
    soup, url = page.soup, page.url

    html = soup.find("html")
    lang = html.get("lang", "").strip() if html else ""
    if lang:
        issues.append(_issue("a11y-lang", "Page language declared", "pass", f'lang="{lang}"', url))
    else:
        issues.append(_issue("a11y-lang", "Page language declared", "warn",
                             "No lang attribute on <html>, so screen readers may mispronounce the page.", url))

    fields = [f for f in soup.find_all(["input", "textarea", "select"])
              if f.get("type") not in ("hidden", "submit", "button", "image", "reset")]
    if fields:
        unlabeled = 0
        for f in fields:
            fid = f.get("id")
            if f.get("aria-label") or f.get("aria-labelledby") or f.get("title"):
                continue
            if fid and soup.find("label", attrs={"for": fid}):
                continue
            if f.find_parent("label"):
                continue
            unlabeled += 1
        if unlabeled:
            issues.append(_issue("a11y-form-labels", "Form fields labelled", "warn" if unlabeled <= 2 else "fail",
                                 f"{unlabeled} of {len(fields)} form fields have no label (a placeholder alone does not count).", url))
        else:
            issues.append(_issue("a11y-form-labels", "Form fields labelled", "pass",
                                 f"All {len(fields)} form fields are labelled.", url))

    nameless = 0
    for el in soup.find_all(["a", "button"]):
        if el.name == "a" and not el.get("href"):
            continue
        if el.get_text(strip=True) or el.get("aria-label") or el.get("aria-labelledby") or el.get("title"):
            continue
        if el.find("img", alt=lambda a: a and a.strip()):
            continue
        nameless += 1
    if nameless:
        issues.append(_issue("a11y-link-names", "Links and buttons have names", "warn",
                             f"{nameless} link(s) or button(s) have no text or label, so screen readers announce nothing useful.", url))
    else:
        issues.append(_issue("a11y-link-names", "Links and buttons have names", "pass",
                             "Every link and button has a readable name.", url))

    vague = [a for a in soup.find_all("a", href=True) if _VAGUE_RE.match(a.get_text(" ", strip=True))]
    if len(vague) >= 3:
        issues.append(_issue("a11y-vague-links", "Descriptive link text", "warn",
                             f"{len(vague)} links say things like 'click here' or 'read more'. Use text that says where the link goes.", url))
    else:
        issues.append(_issue("a11y-vague-links", "Descriptive link text", "pass",
                             "Link text is descriptive.", url))
    return issues
