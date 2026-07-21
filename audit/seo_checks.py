"""
seo_checks.py — per-page and site-level SEO diagnostics.

Every check function returns a dict:
  { "id", "label", "status": "pass"|"warn"|"fail", "detail", "page" }
"""

import requests
from urllib.parse import urlparse


def _issue(id_, label, status, detail, page):
    return {"id": id_, "label": label, "status": status, "detail": detail, "page": page}


def check_page(page):
    issues = []
    if not page.soup:
        return issues
    soup = page.soup
    url = page.url

    # Title
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    if not title:
        issues.append(_issue("title-missing", "Page title", "fail", "No <title> tag found.", url))
    elif len(title) > 60:
        issues.append(_issue("title-length", "Page title", "warn",
                              f"Title is {len(title)} characters — over the ~60 char limit search engines display.", url))
    elif len(title) < 15:
        issues.append(_issue("title-length", "Page title", "warn",
                              f"Title is only {len(title)} characters — likely too short to be descriptive.", url))
    else:
        issues.append(_issue("title-ok", "Page title", "pass", f'"{title}" ({len(title)} chars)', url))

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    desc_content = meta_desc.get("content", "").strip() if meta_desc else ""
    if not desc_content:
        issues.append(_issue("meta-desc-missing", "Meta description", "fail", "No meta description found.", url))
    elif len(desc_content) > 160:
        issues.append(_issue("meta-desc-length", "Meta description", "warn",
                              f"Description is {len(desc_content)} characters — over the ~160 char limit.", url))
    else:
        issues.append(_issue("meta-desc-ok", "Meta description", "pass", f"{len(desc_content)} characters", url))

    # H1 usage
    h1s = soup.find_all("h1")
    if len(h1s) == 0:
        issues.append(_issue("h1-missing", "Heading structure", "fail", "No <h1> found on page.", url))
    elif len(h1s) > 1:
        issues.append(_issue("h1-multiple", "Heading structure", "warn",
                              f"{len(h1s)} <h1> tags found — a single clear h1 is recommended.", url))
    else:
        issues.append(_issue("h1-ok", "Heading structure", "pass", "Exactly one <h1> found.", url))

    # Image alt text coverage
    imgs = soup.find_all("img")
    if imgs:
        with_alt = sum(1 for i in imgs if i.get("alt", "").strip())
        pct = round(with_alt / len(imgs) * 100)
        status = "pass" if pct == 100 else ("warn" if pct >= 60 else "fail")
        issues.append(_issue("alt-text", "Image alt text", status,
                              f"{with_alt}/{len(imgs)} images ({pct}%) have alt text.", url))

    # Canonical tag
    canonical = soup.find("link", rel="canonical")
    if not canonical:
        issues.append(_issue("canonical-missing", "Canonical tag", "warn", "No canonical link tag found.", url))
    else:
        issues.append(_issue("canonical-ok", "Canonical tag", "pass", canonical.get("href", ""), url))

    # Open Graph completeness (also feeds design/brand score)
    og_tags = soup.find_all("meta", property=lambda p: p and p.startswith("og:"))
    if len(og_tags) < 3:
        issues.append(_issue("og-incomplete", "Social preview tags", "warn",
                              f"Only {len(og_tags)} Open Graph tags found — link previews may look broken.", url))
    else:
        issues.append(_issue("og-ok", "Social preview tags", "pass", f"{len(og_tags)} Open Graph tags found.", url))

    return issues


def check_site(seed_url, pages):
    """Site-wide checks that only need to run once (robots.txt, sitemap)."""
    issues = []
    parsed = urlparse(pages[0].url if pages else seed_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    try:
        r = requests.get(f"{root}/robots.txt", timeout=6)
        if r.status_code == 200 and r.text.strip():
            issues.append(_issue("robots-ok", "robots.txt", "pass", "robots.txt found and reachable.", root))
        else:
            issues.append(_issue("robots-missing", "robots.txt", "warn", "robots.txt missing or empty.", root))
    except requests.RequestException:
        issues.append(_issue("robots-error", "robots.txt", "warn", "Could not fetch robots.txt.", root))

    try:
        r = requests.get(f"{root}/sitemap.xml", timeout=6)
        if r.status_code == 200 and "<urlset" in r.text.lower() or "<sitemapindex" in r.text.lower():
            issues.append(_issue("sitemap-ok", "XML sitemap", "pass", "sitemap.xml found.", root))
        else:
            issues.append(_issue("sitemap-missing", "XML sitemap", "warn", "No sitemap.xml at the default location.", root))
    except requests.RequestException:
        issues.append(_issue("sitemap-error", "XML sitemap", "warn", "Could not fetch sitemap.xml.", root))

    return issues
