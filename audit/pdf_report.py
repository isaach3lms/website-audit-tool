"""
pdf_report.py — renders a finished audit (as a plain dict) into a downloadable
PDF, styled to match the web report's Between Sundays brand colors.

Pure-Python (reportlab), no system dependencies like wkhtmltopdf/WeasyPrint
need — keeps this reliable on free-tier hosts.
"""

import io
from xml.sax.saxutils import escape as _esc

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

INK = colors.HexColor("#1C2E22")
INK_SOFT = colors.HexColor("#274435")
INK_MUTED = colors.HexColor("#5E6C61")
BRAND = colors.HexColor("#274435")
BRAND_SOFT = colors.HexColor("#A5AE9E")
BRAND_TINT = colors.HexColor("#EDEFE9")
BORDER = colors.HexColor("#E3E7DF")
PASS = colors.HexColor("#2F8F5B")
PASS_BG = colors.HexColor("#EAF6EE")
WARN = colors.HexColor("#B4790E")
WARN_BG = colors.HexColor("#FBF1DD")
FAIL = colors.HexColor("#C1440E")
FAIL_BG = colors.HexColor("#FBEAE2")

_STATUS_COLORS = {"pass": (PASS, PASS_BG), "warn": (WARN, WARN_BG), "fail": (FAIL, FAIL_BG)}


def _band_color(score):
    if score is None:
        return (INK_MUTED, BRAND_TINT)
    if score >= 80:
        return (PASS, PASS_BG)
    if score >= 60:
        return (WARN, WARN_BG)
    return (FAIL, FAIL_BG)


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("TitleX", parent=base["Title"], textColor=INK_SOFT, fontSize=22, spaceAfter=2, alignment=0),
        "subtitle": ParagraphStyle("Subtitle", parent=base["Normal"], textColor=INK_MUTED, fontSize=10, spaceAfter=16),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], textColor=INK_SOFT, fontSize=13.5, spaceBefore=16, spaceAfter=6),
        "body": ParagraphStyle("BodyX", parent=base["Normal"], textColor=INK, fontSize=10, leading=14),
        "note": ParagraphStyle("Note", parent=base["Normal"], textColor=INK_MUTED, fontSize=9, leading=13),
        "score_num": ParagraphStyle("ScoreNum", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=20, leading=22),
        "score_label": ParagraphStyle("ScoreLabel", parent=base["Normal"], fontName="Courier", fontSize=7.5, textColor=INK_MUTED, leading=10, spaceBefore=2),
        "tag_title": ParagraphStyle("TagTitle", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10, textColor=INK_SOFT, leading=13),
        "tag_detail": ParagraphStyle("TagDetail", parent=base["Normal"], fontSize=9, textColor=INK_MUTED, leading=12),
        "tag_page": ParagraphStyle("TagPage", parent=base["Normal"], fontName="Courier", fontSize=7.5, textColor=BRAND_SOFT, leading=10),
        "all_clear": ParagraphStyle("AllClear", parent=base["Normal"], fontSize=9.5, textColor=PASS, leading=13),
        "table_head": ParagraphStyle("TableHead", parent=base["Normal"], fontName="Courier", fontSize=8, textColor=INK_MUTED),
        "table_cell": ParagraphStyle("TableCell", parent=base["Normal"], fontName="Courier", fontSize=8, textColor=INK, wordWrap="CJK"),
    }


def _score_tile(label, score, grade, s):
    color, bg = _band_color(score)
    score_text = str(score) if score is not None else "—"
    label_text = f"{label} · {grade}" if grade and grade != "—" else label
    inner = Table(
        [[Paragraph(f"<font color='{color.hexval()}'>{score_text}</font>", s["score_num"])],
         [Paragraph(label_text, s["score_label"])]],
        colWidths=[1.5 * inch],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEABOVE", (0, 0), (-1, 0), 2.5, color),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return inner


def _findings_section(title, issues, counts, story, s):
    story.append(Paragraph(title, s["h2"]))
    chip = (f"<font color='#2F8F5B'>{counts.get('pass', 0)} pass</font>  "
            f"<font color='#B4790E'>{counts.get('warn', 0)} notice</font>  "
            f"<font color='#C1440E'>{counts.get('fail', 0)} issue</font>")
    story.append(Paragraph(chip, s["note"]))
    story.append(Spacer(1, 6))

    if not issues:
        story.append(Paragraph("No issues found across the crawled pages.", s["all_clear"]))
        story.append(Spacer(1, 10))
        return

    for issue in issues:
        status = issue.get("status", "warn")
        color, bg = _STATUS_COLORS.get(status, (WARN, WARN_BG))
        tag_text = "ISSUE" if status == "fail" else "NOTICE"
        label = _esc(str(issue.get("label", "")))
        detail = _esc(str(issue.get("detail", "")))
        page = _esc(str(issue.get("page", "")))
        cell = Table(
            [[Paragraph(
                f"<font color='{color.hexval()}'><b>{tag_text}</b></font><br/><br/>"
                f"<font color='{INK_SOFT.hexval()}'><b>{label}</b></font><br/>"
                f"<font color='{INK_MUTED.hexval()}'>{detail}</font><br/>"
                f"<font color='{BRAND_SOFT.hexval()}'>{page}</font>",
                s["tag_detail"]
            )]],
            colWidths=[6.3 * inch],
        )
        cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, color),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(cell)
        story.append(Spacer(1, 6))
    story.append(Spacer(1, 8))


def build_pdf(data):
    """data: the same dict passed to the report template as `report_data`. Returns PDF bytes."""
    s = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        title=f"Website Audit — {data.get('site_label', '')}",
    )
    story = []

    story.append(Paragraph(f"Website Audit — {_esc(str(data.get('site_label', '')))}", s["title"]))
    meta = (f"{_esc(str(data.get('seed_url', '')))} &nbsp;·&nbsp; {_esc(str(data.get('generated_at', '')))} "
            f"&nbsp;·&nbsp; {data.get('pages_ok', 0)}/{data.get('pages_crawled', 0)} pages reachable")
    story.append(Paragraph(meta, s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=16))

    tiles = [
        _score_tile("OVERALL", data.get("overall_score"), None, s),
        _score_tile("SEO", data.get("seo_score"), data.get("seo_grade"), s),
        _score_tile("PERFORMANCE", data.get("perf_score"), data.get("perf_grade"), s),
        _score_tile("DESIGN & POLISH", data.get("design_score"), data.get("design_grade"), s),
        _score_tile("LINKS", data.get("links_score"), data.get("links_grade"), s),
    ]
    tile_row = Table([tiles], colWidths=[1.34 * inch] * 5, hAlign="LEFT")
    tile_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(tile_row)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "\"Design &amp; Polish\" is a heuristic signal (responsiveness, custom type, palette, motion, "
        "brand completeness) — not a taste judgment.",
        s["note"]
    ))

    _findings_section("SEO", data.get("seo_issues", []), data.get("seo_counts", {}), story, s)
    _findings_section("Performance", data.get("perf_issues", []), data.get("perf_counts", {}), story, s)
    _findings_section("Design &amp; Polish", data.get("design_issues", []), data.get("design_counts", {}), story, s)
    _findings_section("Links", data.get("link_issues", []), data.get("links_counts", {}), story, s)

    doc.build(story)
    return buf.getvalue()
