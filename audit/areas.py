"""
areas.py: turns the flat pile of issues from every check module into the four
scored areas shown in the report.

Scoring (kept simple and explainable):
  - a sub-section's score is the average points of its issues
  - an area's score is the average of its sub-section scores, so a sub-section
    with 60 per-page findings counts the same as one with 3 site-level checks
  - the overall score is the average of the four area scores

Display:
  - site-level checks (the visitor-facing and PageSpeed checks) are always
    listed, passes included, because they read as a checklist
  - per-page findings (SEO, speed, design, links, accessibility) list only
    what needs attention, and the same finding on several pages is merged into
    one line with a page count
"""

from audit import scoring
from audit.structure import (
    AREAS, GROUP_TO_AREA, SG_SEO, SG_A11Y, SG_SPEED, SG_MOBILE, SG_BRAND, SG_LINKS,
)

_AREA_BY_KEY = {a["key"]: a for a in AREAS}


# --- Tagging issues from the older per-page modules with their new sub-section ---

def tag_seo(issues):
    out = []
    for i in issues:
        group = SG_A11Y if i["id"] == "alt-text" else SG_SEO
        out.append(dict(i, group=group))
    return out


def tag_performance(issues):
    return [dict(i, group=SG_SPEED) for i in issues]


def tag_design(issues):
    return [dict(i, group=SG_MOBILE if i["id"].startswith("viewport") else SG_BRAND) for i in issues]


def tag_links(issues):
    # Each broken link is its own finding, so these are never merged
    return [dict(i, group=SG_LINKS, no_merge=True) for i in issues]


def tag_accessibility(issues):
    return [dict(i, group=SG_A11Y) for i in issues]


# --- Assembly ---

def _display_issues(issues):
    """Site-level issues in full, then merged non-pass per-page issues (worst first)."""
    site = [i for i in issues if i.get("site_level")]
    per_page = [i for i in issues if not i.get("site_level") and i["status"] != "pass"]

    merged, order = {}, []
    singles = []
    for i in per_page:
        if i.get("no_merge"):
            singles.append(i)
            continue
        key = (i["label"], i["status"])
        if key not in merged:
            merged[key] = dict(i, affected=1)
            order.append(key)
        else:
            merged[key]["affected"] += 1
    rows = []
    for key in order:
        m = merged[key]
        if m["affected"] > 1:
            m["detail"] = f"{m['detail']} The same issue appears on {m['affected']} pages."
        rows.append(m)
    rows += singles
    rows.sort(key=lambda r: 0 if r["status"] == "fail" else 1)
    return site + rows


def build_areas(issues, notes=None):
    """
    issues: flat list; every issue needs a "group" from structure.py.
    notes:  {sub-section name: one-line note shown under that sub-section}
    Returns a JSON-serializable list of areas.
    """
    notes = notes or {}
    by_group = {}
    for i in issues:
        if i.get("group") in GROUP_TO_AREA:
            by_group.setdefault(i["group"], []).append(i)

    areas = []
    for area in AREAS:
        subgroups, scores = [], []
        total = {"pass": 0, "warn": 0, "fail": 0}
        for sg in area["subgroups"]:
            items = by_group.get(sg["name"], [])
            if not items and sg["name"] not in notes:
                continue
            score = scoring.score_from_issues(items)
            counts = scoring.counts_by_status(items)
            for k in total:
                total[k] += counts[k]
            if score is not None:
                scores.append(score)
            subgroups.append({
                "name": sg["name"], "subtitle": sg["subtitle"], "score": score,
                "grade": scoring.grade_letter(score), "counts": counts,
                "issues": _display_issues(items), "note": notes.get(sg["name"]),
            })
        score = round(sum(scores) / len(scores)) if scores else None
        areas.append({
            "key": area["key"], "name": area["name"], "subtitle": area["subtitle"],
            "score": score, "grade": scoring.grade_letter(score), "counts": total, "subgroups": subgroups,
        })
    return areas


def overall_score(areas):
    scores = [a["score"] for a in areas if a["score"] is not None]
    return round(sum(scores) / len(scores)) if scores else None


def tag_for_summary(issues):
    """Adds category = area name so the executive summary can weight by area."""
    out = []
    for i in issues:
        key = GROUP_TO_AREA.get(i.get("group"))
        if key:
            out.append(dict(i, category=_AREA_BY_KEY[key]["name"]))
    return out
