"""
summary.py — picks the highest-priority items across every category for a
top-of-report executive summary. Built for a client-facing deliverable: a
prospect should be able to read five bullet points and know what matters
most, without wading through the full findings list.
"""

_CATEGORY_WEIGHT = {
    "Ministry Essentials": 3,   # business-relevant, prospect-facing — weighted highest
    "SEO": 2,
    "Links": 2,
    "Performance": 1,
    "Design & Polish": 1,
}
_STATUS_WEIGHT = {"fail": 2, "warn": 1, "pass": 0}


def build_executive_summary(tagged_issues, top_n=5):
    """
    tagged_issues: list of issue dicts, each with an added "category" key.
    Returns the top_n highest-priority non-pass issues, deduplicated by
    (category, label) so the same finding across many pages only appears once.
    """
    seen = set()
    deduped = []
    for issue in tagged_issues:
        if issue.get("status") == "pass":
            continue
        key = (issue.get("category"), issue.get("label"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)

    def priority(issue):
        cat_w = _CATEGORY_WEIGHT.get(issue.get("category"), 1)
        status_w = _STATUS_WEIGHT.get(issue.get("status"), 0)
        return (status_w * 10 + cat_w)

    deduped.sort(key=priority, reverse=True)
    return deduped[:top_n]
