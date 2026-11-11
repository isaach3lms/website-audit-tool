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
import time
import concurrent.futures
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, render_template, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit.crawler import crawl
from audit.pagedoc import Doc
from audit import (
    seo_checks, performance_checks, design_checks, link_checker, accessibility_checks,
    guest_experience, sermon_media, ux_checks, local_seo, pagespeed, areas as areas_mod,
    summary, scoring, pdf_report, emailer,
)
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

    # Google PageSpeed takes 15 to 40 seconds, so it starts now and runs while we crawl.
    started = time.monotonic()
    ps_job = pagespeed.PageSpeedJob(probe_url, os.environ.get("PAGESPEED_API_KEY"))

    pages = crawl(url, max_pages=max_pages, max_depth=max_depth)
    crawled_ok = [p for p in pages if p.ok]

    if not crawled_ok:
        return render_template("index.html", error=f"Couldn't reach {url}. Check the address and try again.")

    docs = [Doc(p) for p in crawled_ok if p.soup]

    # Per-page checks (the older modules)
    seo_p, perf_p, design_p, a11y_p = [], [], [], []
    per_page = []
    for page in pages:
        seo_p += seo_checks.check_page(page)
        perf_p += performance_checks.check_page(page)
        design_p += design_checks.check_page(page)
        a11y_p += accessibility_checks.check_page(page)
        per_page.append({"url": page.url, "status_code": page.status_code, "ok": page.ok})
    seo_site = seo_checks.check_site(url, crawled_ok)

    # Checks that make outside requests run side by side
    links = link_checker.collect_links(pages)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_links = pool.submit(link_checker.check_links, links, MAX_LINKS_CHECKED)
        f_sermon = pool.submit(_safely, sermon_media.check_site, docs)
        f_embeds = pool.submit(_safely, ux_checks.check_embeds, docs)
        link_results = f_links.result()
        sermon_issue, embeds_issue = f_sermon.result(), f_embeds.result()
    link_issues = link_checker.to_issues(link_results)
    links_skipped = sum(1 for r in link_results if r["skipped"])

    # Site-level checks, each filed under its area by its own "group"
    site_checks = guest_experience.check_docs(docs) + [
        sermon_issue,
        _safely(ux_checks.check_mobile_nav_giving, docs),
        _safely(ux_checks.check_brand_consistency, docs),
        _safely(ux_checks.check_forms, docs),
        embeds_issue,
        _safely(ux_checks.check_fresh_content, docs),
        _safely(local_seo.check_google_profile, docs),
        _safely(local_seo.check_local_keywords, docs),
        _safely(local_seo.check_url_structure, docs),
        _safely(local_seo.check_duplicate_titles, docs),
        _safely(local_seo.check_analytics, docs),
    ]
    site_checks = [i for i in site_checks if i]

    # Google PageSpeed (mobile): collect whatever finished, with a time cap
    remaining = max(5, 45 - (time.monotonic() - started))
    ps_result = ps_job.result(timeout=remaining)
    ps_issues, ps_note = pagespeed.to_issues(ps_result, crawled_ok[0].url)
    for group_issues in ps_issues.values():
        site_checks += group_issues

    all_issues = (
        areas_mod.tag_seo(seo_p + seo_site) + areas_mod.tag_performance(perf_p)
        + areas_mod.tag_design(design_p) + areas_mod.tag_accessibility(a11y_p)
        + areas_mod.tag_links(link_issues) + site_checks
    )
    notes = {areas_mod.SG_SPEED: ps_note} if ps_note else {}
    areas = areas_mod.build_areas(all_issues, notes)
    overall_score = areas_mod.overall_score(areas)

    # Site-level findings lead the executive summary so the visitor-facing gaps surface first
    ordered = sorted(all_issues, key=lambda i: not i.get("site_level"))
    exec_summary = summary.build_executive_summary(areas_mod.tag_for_summary(ordered), top_n=5)

    report_ctx = dict(
        site_label=urlparse(pages[0].url).netloc,
        seed_url=url,
        generated_at=datetime.now().strftime("%b %d, %Y %H:%M"),
        pages_crawled=len(pages),
        pages_ok=len(crawled_ok),
        overall_score=overall_score,
        overall_grade=scoring.grade_letter(overall_score),
        areas=areas,
        exec_summary=exec_summary,
        links_checked=len(link_results) - links_skipped,
        links_total=len(link_results),
        links_skipped=links_skipped,
        pagespeed_status=ps_result.get("status"),
    )

    return render_template(
        "report.html",
        per_page=per_page,
        report_data=report_ctx,
        **report_ctx,
    )


def _safely(fn, *args):
    """A single failing check must never take the whole audit down."""
    try:
        return fn(*args)
    except Exception:
        app.logger.exception("Check failed: %s", getattr(fn, "__name__", fn))
        return None


@app.route("/audit/pdf", methods=["POST"])
@limiter.limit("10 per minute")
def audit_pdf():
    import json
    raw = request.form.get("report_data", "")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "Invalid report data.", 400

    try:
        pdf_bytes = pdf_report.build_pdf(data)
    except Exception:
        app.logger.exception("PDF generation failed")
        return "Couldn't generate the PDF for this report. Please try running the audit again.", 500

    filename = f"audit-{data.get('site_label', 'report').replace('.', '-')}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/audit/email", methods=["POST"])
@limiter.limit("5 per minute")
def audit_email():
    import json

    # This is a public, unauthenticated app, and an open "email anyone a PDF"
    # endpoint is exactly the kind of thing spammers scan the internet for.
    # Require a shared access code (set on Render as an env var) so only you
    # can actually use this, even though the route itself is reachable by anyone.
    expected_code = os.environ.get("EMAIL_ACCESS_CODE")
    if not expected_code:
        return "Email sending isn't configured on this server yet. Set EMAIL_ACCESS_CODE (and SMTP_* vars) as environment variables.", 503
    if request.form.get("access_code", "") != expected_code:
        return "Incorrect access code.", 403

    raw = request.form.get("report_data", "")
    to_email = request.form.get("to_email", "").strip()
    note = request.form.get("note", "").strip()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "Invalid report data.", 400

    try:
        pdf_bytes = pdf_report.build_pdf(data)
    except Exception:
        app.logger.exception("PDF generation failed during email send")
        return "Couldn't generate the PDF for this report.", 500

    site_label = data.get("site_label", "your site")
    subject = f"Website audit for {site_label} — Between Sundays"
    body_lines = [
        f"Hi,",
        "",
        f"Attached is a website audit for {site_label}, put together by Between Sundays.",
    ]
    if note:
        body_lines += ["", note]
    body_lines += ["", "Let us know if you'd like to talk through the findings.", "", "Between Sundays"]
    body = "\n".join(body_lines)
    filename = f"audit-{str(site_label).replace('.', '-')}.pdf"

    try:
        emailer.send_report_email(to_email, subject, body, pdf_bytes, filename)
    except emailer.InvalidRecipientError as exc:
        return str(exc), 400
    except emailer.EmailConfigError as exc:
        return str(exc), 503
    except Exception:
        app.logger.exception("Email send failed")
        return "Couldn't send the email. Double check the recipient address and try again.", 500

    return f"Sent to {to_email}.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
