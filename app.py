"""
app.py — Website Audit Tool

Local run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000

Production (see README.md for full deploy steps):
    gunicorn app:app
"""

import os
import io
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, render_template, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit.crawler import crawl
from audit import seo_checks, performance_checks, design_checks, link_checker, scoring, pdf_report
from audit.safety import assert_safe_url, UnsafeURLError

MAX_LINKS_CHECKED = 60

app = Flask(__name__)

# Public deployments get pointed at arbitrary URLs by strangers, so audits
# are rate-limited per IP. Adjust to taste once you know your traffic.
limiter = Limiter(get_remote_address, app=app, default_limits=[])


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/audit", methods=["POST"])
@limiter.limit("6 per minute")
def audit():
    url = request.form.get("url", "").strip()
    max_pages = int(request.form.get("max_pages", 10))
    max_depth = int(request.form.get("max_depth", 2))
    max_pages = max(1, min(max_pages, 30))
    max_depth = max(0, min(max_depth, 4))

    if not url:
        return render_template("index.html", error="Enter a URL to audit.")

    probe_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
    try:
        assert_safe_url(probe_url)
    except UnsafeURLError as exc:
        return render_template("index.html", error=str(exc))

    pages = crawl(url, max_pages=max_pages, max_depth=max_depth)
    crawled_ok = [p for p in pages if p.ok]

    if not crawled_ok:
        return render_template("index.html", error=f"Couldn't reach {url}. Check the address and try again.")

    seo_issues, perf_issues, design_issues = [], [], []
    per_page = []

    for page in pages:
        p_seo = seo_checks.check_page(page)
        p_perf = performance_checks.check_page(page)
        p_design = design_checks.check_page(page)
        seo_issues += p_seo
        perf_issues += p_perf
        design_issues += p_design
        per_page.append({
            "url": page.url,
            "status_code": page.status_code,
            "ok": page.ok,
            "seo": p_seo,
            "perf": p_perf,
            "design": p_design,
        })

    seo_issues += seo_checks.check_site(url, crawled_ok)

    links = link_checker.collect_links(pages)
    link_results = link_checker.check_links(links, max_links=MAX_LINKS_CHECKED)
    link_issues = link_checker.to_issues(link_results)
    links_skipped = sum(1 for r in link_results if r["skipped"])

    seo_score = scoring.score_from_issues(seo_issues)
    perf_score = scoring.score_from_issues(perf_issues)
    design_score = scoring.score_from_issues(design_issues)
    links_score = scoring.score_from_issues(link_issues)
    scores = [s for s in (seo_score, perf_score, design_score, links_score) if s is not None]
    overall_score = round(sum(scores) / len(scores)) if scores else None

    root = urlparse(pages[0].url)
    site_label = root.netloc

    report_ctx = dict(
        site_label=site_label,
        seed_url=url,
        generated_at=datetime.now().strftime("%b %d, %Y %H:%M"),
        pages_crawled=len(pages),
        pages_ok=len(crawled_ok),
        seo_score=seo_score, perf_score=perf_score, design_score=design_score, links_score=links_score,
        overall_score=overall_score,
        seo_grade=scoring.grade_letter(seo_score),
        perf_grade=scoring.grade_letter(perf_score),
        design_grade=scoring.grade_letter(design_score),
        links_grade=scoring.grade_letter(links_score),
        seo_counts=scoring.counts_by_status(seo_issues),
        perf_counts=scoring.counts_by_status(perf_issues),
        design_counts=scoring.counts_by_status(design_issues),
        links_counts=scoring.counts_by_status(link_issues),
        seo_issues=[i for i in seo_issues if i["status"] != "pass"],
        perf_issues=[i for i in perf_issues if i["status"] != "pass"],
        design_issues=[i for i in design_issues if i["status"] != "pass"],
        link_issues=[i for i in link_issues if i["status"] != "pass"],
        links_checked=len(link_results) - links_skipped,
        links_total=len(link_results),
        links_skipped=links_skipped,
    )

    return render_template(
        "report.html",
        per_page=per_page,
        report_data=report_ctx,
        **report_ctx,
    )


@app.route("/audit/pdf", methods=["POST"])
@limiter.limit("10 per minute")
def audit_pdf():
    import json
    raw = request.form.get("report_data", "")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "Invalid report data.", 400

    pdf_bytes = pdf_report.build_pdf(data)
    filename = f"audit-{data.get('site_label', 'report').replace('.', '-')}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
