"""
scoring.py — turns lists of check issues into 0-100 category scores.

pass = 1 point, warn = 0.5 points, fail = 0 points, averaged and scaled.
"""

STATUS_POINTS = {"pass": 1.0, "warn": 0.5, "fail": 0.0}


def score_from_issues(issues):
    if not issues:
        return None
    total = sum(STATUS_POINTS.get(i["status"], 0) for i in issues)
    return round(total / len(issues) * 100)


def grade_letter(score):
    if score is None:
        return "—"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def counts_by_status(issues):
    out = {"pass": 0, "warn": 0, "fail": 0}
    for i in issues:
        out[i["status"]] = out.get(i["status"], 0) + 1
    return out
