"""
design_checks.py — heuristic "design & polish" signals.

Important honesty note: actual visual creativity/taste can't be scored by
parsing HTML. These checks measure proxies that correlate with a site having
had real design attention — a defined palette, custom type, responsiveness,
motion, favicon/brand completeness — and are surfaced to the user as signals,
not a verdict on aesthetics.
"""

import re

HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")


def _issue(id_, label, status, detail, page):
    return {"id": id_, "label": label, "status": status, "detail": detail, "page": page}


def check_page(page):
    issues = []
    if not page.soup:
        return issues
    soup = page.soup
    url = page.url

    # Responsive viewport
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if viewport:
        issues.append(_issue("viewport-ok", "Responsive viewport", "pass", "Viewport meta tag present.", url))
    else:
        issues.append(_issue("viewport-missing", "Responsive viewport", "fail",
                              "No viewport meta tag — page likely won't adapt to mobile screens.", url))

    # Favicon
    icon = soup.find("link", rel=lambda r: r and "icon" in r.lower())
    issues.append(_issue("favicon", "Favicon", "pass" if icon else "warn",
                          "Favicon linked." if icon else "No favicon link found.", url))

    # Custom web fonts (Google Fonts, @font-face, or preconnect to a font CDN)
    style_text = " ".join(s.get_text() for s in soup.find_all("style"))
    font_links = soup.find_all("link", href=lambda h: h and ("fonts.googleapis" in h or "fonts" in h.lower()))
    has_font_face = "@font-face" in style_text
    if font_links or has_font_face:
        issues.append(_issue("custom-fonts", "Custom typography", "pass",
                              "Custom web fonts detected (beyond system defaults).", url))
    else:
        issues.append(_issue("custom-fonts", "Custom typography", "warn",
                              "No custom web fonts detected — page may be using default system fonts only.", url))

    # Palette richness: distinct hex colors referenced in inline styles/style blocks
    inline_styles = " ".join(tag.get("style", "") for tag in soup.find_all(style=True))
    colors = set(c.lower() for c in HEX_RE.findall(inline_styles + " " + style_text))
    if len(colors) >= 3:
        issues.append(_issue("palette", "Color palette", "pass", f"{len(colors)} distinct colors referenced inline.", url))
    elif len(colors) > 0:
        issues.append(_issue("palette", "Color palette", "warn", f"Only {len(colors)} distinct inline colors found — may rely on an external stylesheet (not fully visible to this scan).", url))
    else:
        issues.append(_issue("palette", "Color palette", "warn", "No inline colors detected — palette likely lives entirely in external CSS, which this scan can't fully inspect.", url))

    # Motion / interactivity signals
    has_transition = "transition" in style_text or "animation" in style_text
    issues.append(_issue("motion", "Motion & interactivity", "pass" if has_transition else "warn",
                          "CSS transitions/animations detected in inline styles." if has_transition
                          else "No inline transition/animation rules detected (may still exist in external CSS).", url))

    # Visual richness: images per 1000 words of text (rough)
    text_len = len(soup.get_text(separator=" ", strip=True).split())
    img_count = len(soup.find_all("img"))
    if text_len > 0:
        ratio = img_count / max(text_len / 300, 1)
        status = "pass" if ratio >= 1 else "warn"
        issues.append(_issue("visual-density", "Visual density", status,
                              f"{img_count} images against ~{text_len} words of text.", url))

    return issues
