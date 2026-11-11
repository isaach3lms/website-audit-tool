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
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Flowable, KeepTogether
)

INK = colors.HexColor("#0B1026")
INK_SOFT = colors.HexColor("#0B1026")
INK_MUTED = colors.HexColor("#5A6482")
BRAND = colors.HexColor("#2563FF")
BRAND_SOFT = colors.HexColor("#1E3A8A")
BRAND_TINT = colors.HexColor("#E6EEFF")
BORDER = colors.HexColor("#DCE5F7")
PASS = colors.HexColor("#16924F")
PASS_BG = colors.HexColor("#E7F7EE")
WARN = colors.HexColor("#B4790E")
WARN_BG = colors.HexColor("#FBF1DD")
FAIL = colors.HexColor("#D0361E")
FAIL_BG = colors.HexColor("#FCEBE7")

_STATUS_COLORS = {"pass": (PASS, PASS_BG), "warn": (WARN, WARN_BG), "fail": (FAIL, FAIL_BG)}


class BSMark(Flowable):
    """Vector-drawn 'bs' logo mark — rounded square, brand navy fill, white
    wordmark — so the PDF carries the Between Sundays mark without needing an
    external image asset to keep on disk or ship with the repo."""

    def __init__(self, size=34):
        super().__init__()
        self.size = size
        self.width = size
        self.height = size

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(BRAND_SOFT)
        c.roundRect(0, 0, self.size, self.size, self.size * 0.26, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", self.size * 0.46)
        c.drawCentredString(self.size / 2, self.size * 0.3, "bs")
        c.restoreState()


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
        "group_head": ParagraphStyle("GroupHead", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10.5, textColor=INK_SOFT, leading=14, spaceBefore=8, spaceAfter=5),
        "summary_item": ParagraphStyle("SummaryItem", parent=base["Normal"], fontSize=10.5, textColor=INK, leading=15),
    }


def _score_tile(label, score, grade, s, width=1.5 * inch):
    color, bg = _band_color(score)
    score_text = str(score) if score is not None else "—"
    label_text = f"{label} · {grade}" if grade and grade != "—" else label
    inner = Table(
        [[Paragraph(f"<font color='{color.hexval()}'>{score_text}</font>", s["score_num"])],
         [Paragraph(label_text, s["score_label"])]],
        colWidths=[width],
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


def _executive_summary(exec_summary, story, s):
    if not exec_summary:
        return
    story.append(Paragraph("Top priorities", s["h2"]))
    rows = []
    for i, item in enumerate(exec_summary, 1):
        status = item.get("status", "warn")
        color = FAIL if status == "fail" else WARN
        label = _esc(str(item.get("label", "")))
        detail = _esc(str(item.get("detail", "")))
        category = _esc(str(item.get("category", "")))
        text = (f"<font color='{color.hexval()}'><b>{i}.</b></font> "
                f"<b>{label}</b> <font color='{INK_MUTED.hexval()}'>({category})</font><br/>"
                f"<font color='{INK_MUTED.hexval()}'>{detail}</font>")
        rows.append([Paragraph(text, s["summary_item"])])
    table = Table(rows, colWidths=[6.3 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_TINT),
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))


def _issue_card(issue, s):
    status = issue.get("status", "warn")
    color, bg = _STATUS_COLORS.get(status, (WARN, WARN_BG))
    tag_text = {"fail": "ISSUE", "pass": "PASS"}.get(status, "NOTICE")
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
    return cell


def _area_section(area, story, s):
    """One scored area: heading, then each sub-section with its findings."""
    score = area.get("score")
    color, _ = _band_color(score)
    score_txt = f"{score} ({_esc(str(area.get('grade', '')))})" if score is not None else "n/a"
    head = [
        Paragraph(f"{_esc(str(area.get('name', '')))} "
                  f"<font color='{color.hexval()}' size='12'>{score_txt}</font>", s["h2"]),
        Paragraph(_esc(str(area.get("subtitle", ""))), s["note"]),
        Spacer(1, 4),
    ]
    for sg in area.get("subgroups", []):
        counts = sg.get("counts", {})
        sg_score = sg.get("score")
        chip = (f"{counts.get('pass', 0)} pass, {counts.get('warn', 0)} notice, {counts.get('fail', 0)} issue"
                + (f", score {sg_score}" if sg_score is not None else ""))
        head.append(Paragraph(
            f"{_esc(str(sg.get('name', '')))} "
            f"<font color='{INK_MUTED.hexval()}' size='8.5'>{_esc(str(sg.get('subtitle', '')))}</font>",
            s["group_head"]))
        head.append(Paragraph(chip, s["note"]))
        if sg.get("note"):
            head.append(Paragraph(_esc(str(sg["note"])), s["note"]))
            head.append(Spacer(1, 3))
        issues = sg.get("issues", [])
        if not issues:
            if not sg.get("note"):
                story.append(KeepTogether(head + [Paragraph("No issues found across the crawled pages.", s["all_clear"]),
                                                  Spacer(1, 6)]))
            else:
                story.append(KeepTogether(head))
            head = []
            continue
        # a heading never ends a page on its own: it travels with its first card
        story.append(KeepTogether(head + [_issue_card(issues[0], s), Spacer(1, 6)]))
        head = []
        for issue in issues[1:]:
            story.append(_issue_card(issue, s))
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
        title=f"Website Audit - {data.get('site_label', '')}",
    )
    story = []

    header_text = Table(
        [[Paragraph(f"Website Audit: {_esc(str(data.get('site_label', '')))}", s["title"])]],
        colWidths=[5.5 * inch],
    )
    header_text.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    header_row = Table([[BSMark(34), header_text]], colWidths=[0.5 * inch, 5.5 * inch])
    header_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(header_row)

    meta = (f"{_esc(str(data.get('seed_url', '')))} &nbsp;&middot;&nbsp; {_esc(str(data.get('generated_at', '')))} "
            f"&nbsp;&middot;&nbsp; {data.get('pages_ok', 0)}/{data.get('pages_crawled', 0)} pages reachable")
    story.append(Paragraph(meta, s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=16))

    areas = data.get("areas", [])
    short = {"visitor": "FIRST-TIME VISITOR", "content": "CONTENT", "ux": "UX AND DESIGN", "technical": "TECHNICAL AND SEO"}
    tiles = [_score_tile("OVERALL", data.get("overall_score"), data.get("overall_grade"), s, 1.3 * inch)]
    for a in areas:
        tiles.append(_score_tile(short.get(a.get("key"), str(a.get("name", "")).upper()), a.get("score"),
                                 a.get("grade"), s, 1.3 * inch))
    tile_row = Table([tiles], colWidths=[1.4 * inch] * len(tiles), hAlign="LEFT")
    tile_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(tile_row)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Scores are heuristic signals from the site's text, markup, and Google PageSpeed when configured, "
        "not a verdict. Visitor-facing items are opportunities, never hard failures. Anything that lives only "
        "on a page outside the crawl will look missing.", s["note"]))
    story.append(Spacer(1, 6))

    _executive_summary(data.get("exec_summary", []), story, s)

    for area in areas:
        _area_section(area, story, s)

    doc.build(story)
    return buf.getvalue()
