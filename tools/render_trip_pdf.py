"""Render a validated itinerary into the personalized travel plan PDF.

Usage:
    python tools/render_trip_pdf.py .tmp/<trip_slug>

Reads request.normalized.json and itinerary.json from that folder and writes
outputs/<trip_slug>_travel_plan.pdf. Run validate_itinerary.py first.
"""

import json
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parent.parent
# (regular, bold, italic) candidates: Windows, macOS, Linux
FONT_SETS = [
    [Path("C:/Windows/Fonts") / f for f in ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf")],
    [Path("C:/Windows/Fonts") / f for f in ("arial.ttf", "arialbd.ttf", "ariali.ttf")],
    [Path("/System/Library/Fonts/Supplemental") / f for f in ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf")],
    [Path("/usr/share/fonts/truetype/dejavu") / f for f in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf")],
]

INK = colors.HexColor("#1F2A37")
MUTED = colors.HexColor("#5B6676")
ACCENT = colors.HexColor("#0E7C86")
ACCENT_SOFT = colors.HexColor("#E3F2F3")
WARM = colors.HexColor("#C8553D")
WARM_SOFT = colors.HexColor("#FBEAE5")
RULE = colors.HexColor("#D5DBE1")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def register_fonts():
    """Use a Unicode system font so currency symbols and accents render; fall back to Helvetica."""
    for paths in FONT_SETS:
        if all(p.exists() for p in paths):
            pdfmetrics.registerFont(TTFont("Body", str(paths[0])))
            pdfmetrics.registerFont(TTFont("Body-Bold", str(paths[1])))
            pdfmetrics.registerFont(TTFont("Body-Italic", str(paths[2])))
            pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold",
                                          italic="Body-Italic", boldItalic="Body-Bold")
            return "Body", "Body-Bold", "Body-Italic"
    print("WARNING: no Unicode system font found; using Helvetica (some symbols may not render).")
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


FONT, FONT_BOLD, FONT_ITALIC = register_fonts()

STYLES = {
    "cover_title": ParagraphStyle("cover_title", fontName=FONT_BOLD, fontSize=32, leading=38, textColor=INK),
    "cover_sub": ParagraphStyle("cover_sub", fontName=FONT, fontSize=14, leading=20, textColor=MUTED),
    "cover_tag": ParagraphStyle("cover_tag", fontName=FONT, fontSize=11, leading=16, textColor=ACCENT),
    "h1": ParagraphStyle("h1", fontName=FONT_BOLD, fontSize=20, leading=26, textColor=INK, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=13.5, leading=18, textColor=ACCENT, spaceBefore=8, spaceAfter=4, keepWithNext=1),
    "h3": ParagraphStyle("h3", fontName=FONT_BOLD, fontSize=11, leading=15, textColor=INK),
    "body": ParagraphStyle("body", fontName=FONT, fontSize=10, leading=14.5, textColor=INK, spaceAfter=4),
    "small": ParagraphStyle("small", fontName=FONT, fontSize=8.8, leading=12.5, textColor=MUTED),
    "why": ParagraphStyle("why", fontName=FONT_ITALIC, fontSize=9.4, leading=13, textColor=ACCENT),
    "label": ParagraphStyle("label", fontName=FONT_BOLD, fontSize=8.5, leading=11, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName=FONT, fontSize=9.2, leading=12.8, textColor=INK),
    "cell_bold": ParagraphStyle("cell_bold", fontName=FONT_BOLD, fontSize=9.2, leading=12.8, textColor=INK),
    "badge": ParagraphStyle("badge", fontName=FONT_BOLD, fontSize=8, leading=10, textColor=colors.white, alignment=TA_CENTER),
}


def p(text, style="body"):
    return Paragraph(escape(str(text or "")), STYLES[style])


def rich(html, style="body"):
    """Paragraph from already-escaped markup."""
    return Paragraph(html, STYLES[style])


def kv(label, value):
    return rich(f"<b>{escape(label)}:</b> {escape(str(value))}", "cell")


def fmt_date(iso):
    d = date.fromisoformat(iso)
    return d.strftime("%a %d %b %Y")


def bullets(items, style="body"):
    return [rich(f"•&nbsp;&nbsp;{escape(str(i))}", style) for i in items if i]


def card(rows, bg, border, width=CONTENT_W):
    t = Table([[r] for r in rows], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    return t


def grid(data, col_widths, header=True):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), ACCENT_SOFT)]
    t.setStyle(TableStyle(style))
    return t


def cover(req, it):
    likes = ", ".join(req["what_they_like"])
    story = [
        Spacer(1, 55 * mm),
        p("PERSONAL TRAVEL PLAN", "cover_tag"),
        Spacer(1, 4 * mm),
        p(req["destination"], "cover_title"),
        Spacer(1, 3 * mm),
        p(f"{fmt_date(req['start_date'])}  to  {fmt_date(req['end_date'])}  ·  {req['num_days']} days", "cover_sub"),
        Spacer(1, 2 * mm),
        p(f"Prepared for {req['traveler_name']}", "cover_sub"),
        Spacer(1, 14 * mm),
        card([p("Built around what you love", "label"), p(likes, "h3")], ACCENT_SOFT, ACCENT),
        Spacer(1, 4 * mm),
        p(f"{req.get('group_detail', req['group_type']).capitalize()}  ·  {req['pace'].title()} pace  ·  {req['budget_level'].title()} budget  ·  from {req['origin_city']}", "small"),
    ]
    if it["must_not_miss_events"]:
        n = len(it["must_not_miss_events"])
        story += [Spacer(1, 2 * mm), p(f"{n} event{'s' if n != 1 else ''} you shouldn't miss inside", "small")]
    story.append(PageBreak())
    return story


def at_a_glance(req, it):
    story = [p("Your trip at a glance", "h1"), p(it["summary"])]
    story += [p("Why you're going", "h2"), rich(f"<i>“{escape(req['why_visiting'])}”</i>")]
    story += [p("What you want from this trip", "h2")] + bullets(req["trip_goals"])
    if req.get("special_needs"):
        story += [p("Planned around", "h2"), p(req["special_needs"])]

    story += [p("The plan in one view", "h2")]
    rows = [[p("Day", "cell_bold"), p("Date", "cell_bold"), p("Theme", "cell_bold")]]
    for i, day in enumerate(it["days"], 1):
        rows.append([p(str(i), "cell"), p(fmt_date(day["date"]), "cell"), p(day["theme"], "cell")])
    story.append(grid(rows, [14 * mm, 38 * mm, CONTENT_W - 52 * mm]))
    story.append(PageBreak())
    return story


def events(it):
    story = [p("Events not to miss", "h1")]
    if not it["must_not_miss_events"]:
        story.append(p(it.get("no_events_note") or "No major events were found for your dates; the day plans focus on year-round highlights."))
        story.append(PageBreak())
        return story
    status_colors = {"confirmed": ACCENT, "tentative": WARM, "recurring": MUTED}
    for ev in it["must_not_miss_events"]:
        status = ev.get("status", "confirmed")
        when = ", ".join(fmt_date(d) for d in ev["dates"])
        if ev.get("time"):
            when += f"  ·  {ev['time']}"
        badge = Table([[p(status.upper(), "badge")]], colWidths=[24 * mm])
        badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), status_colors.get(status, MUTED)),
                                   ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        title = Table([[p(ev["name"], "h3"), badge]], colWidths=[CONTENT_W - 50 * mm, 26 * mm])
        title.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        rows = [title, p(f"{when}  ·  {ev['venue']}", "small"),
                rich(f"Why this is for you: {escape(ev['why_for_you'])}", "why"),
                kv("How to get there", ev["how_to_get_there"]), kv("Tickets", ev["tickets"])]
        if ev.get("tip"):
            rows.append(kv("Tip", ev["tip"]))
        rows.append(p(ev["source_url"], "small"))
        story += [KeepTogether(card(rows, WARM_SOFT, WARM, CONTENT_W)), Spacer(1, 4 * mm)]
    story.append(PageBreak())
    return story


def logistics(req, it):
    story = [p("Getting there & getting around", "h1")]
    gt = it["getting_there"]
    story += [p(f"From {req['origin_city']}", "h2"), p(gt.get("overview", ""))]
    if gt.get("options"):
        rows = [[p(h, "cell_bold") for h in ("Option", "Details", "Time", "Approx. cost")]]
        for o in gt["options"]:
            rows.append([p(o.get("mode"), "cell_bold"), p(o.get("details"), "cell"),
                         p(o.get("duration"), "cell"), p(o.get("cost"), "cell")])
        story.append(grid(rows, [30 * mm, CONTENT_W - 90 * mm, 28 * mm, 32 * mm]))

    ga = it["getting_around"]
    story += [p("Getting around", "h2"), p(ga.get("overview", ""))] + bullets(ga.get("tips", []))

    if it["where_to_stay"]:
        story += [p("Where to stay", "h2")]
        rows = [[p(h, "cell_bold") for h in ("Area", "Why it suits you", "Price / night")]]
        for s in it["where_to_stay"]:
            area = escape(s.get("area", ""))
            if s.get("example"):
                area += f"<br/><font size=8 color='#5B6676'>e.g. {escape(s['example'])}</font>"
            rows.append([rich(area, "cell_bold"), p(s.get("why"), "cell"), p(s.get("price_range"), "cell")])
        story.append(grid(rows, [42 * mm, CONTENT_W - 74 * mm, 32 * mm]))
    story.append(PageBreak())
    return story


def day_pages(it):
    story = []
    order = {"morning": 0, "afternoon": 1, "evening": 2}
    for i, day in enumerate(it["days"], 1):
        header = Table([[p(f"DAY {i}", "badge"), p(f"{fmt_date(day['date'])}  ·  {day['theme']}", "h3")]],
                       colWidths=[18 * mm, CONTENT_W - 18 * mm])
        header.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), ACCENT), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                    ("LEFTPADDING", (1, 0), (1, 0), 10), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [header, Spacer(1, 3 * mm)]
        if day.get("summary"):
            story += [p(day["summary"]), Spacer(1, 2 * mm)]

        for block in sorted(day["blocks"], key=lambda b: order.get(b["time_of_day"].lower(), 3)):
            meta = "  ·  ".join(x for x in (block.get("duration"), block.get("cost")) if x)
            rows = [rich(f"<font color='#0E7C86'>{escape(block['time_of_day'].upper())}</font>&nbsp;&nbsp;"
                         f"<b>{escape(block['activity'])}</b>", "cell"),
                    p(f"{block['location']}" + (f"  ·  {meta}" if meta else ""), "small")]
            if block.get("details"):
                rows.append(p(block["details"], "cell"))
            rows += [kv("How to get there", block["how_to_get_there"]),
                     rich(f"Why this is for you: {escape(block['why_for_you'])}", "why")]
            if block.get("tip"):
                rows.append(kv("Tip", block["tip"]))
            rows.append(p("Feeds: " + ", ".join(block["serves"]), "small"))
            story += [KeepTogether(card(rows, colors.HexColor("#F7F9FA"), ACCENT)), Spacer(1, 3 * mm)]
        story.append(PageBreak())
    return story


def food(it):
    if not it["food"]:
        return []
    story = [p("Where & what to eat", "h1")]
    rows = [[p(h, "cell_bold") for h in ("Place", "Order this", "Why you'll like it", "Price")]]
    for f in it["food"]:
        name = escape(f.get("name", ""))
        if f.get("area"):
            name += f"<br/><font size=8 color='#5B6676'>{escape(f['area'])}</font>"
        rows.append([rich(name, "cell_bold"), p(f.get("what_to_order"), "cell"),
                     p(f.get("why_for_you"), "cell"), p(f.get("price"), "cell")])
    story.append(grid(rows, [40 * mm, 42 * mm, CONTENT_W - 106 * mm, 24 * mm]))
    return story


def goals(it):
    story = [Spacer(1, 6 * mm), p("How this trip delivers on your goals", "h1")]
    rows = [[p(h, "cell_bold") for h in ("Your goal", "How the plan gets you there", "Days")]]
    for g in it["goals_map"]:
        rows.append([p(g.get("goal"), "cell_bold"), p(g.get("how"), "cell"),
                     p(", ".join(str(d) for d in g.get("days", [])), "cell")])
    story += [grid(rows, [48 * mm, CONTENT_W - 70 * mm, 22 * mm]), PageBreak()]
    return story


def practical(it):
    pr = it["practical"]
    story = [p("Practical info", "h1")]
    if pr.get("weather"):
        story += [p("Weather", "h2"), p(pr["weather"])]
    if pr.get("currency"):
        story += [p("Money", "h2"), p(pr["currency"])]
    if pr.get("daily_budget"):
        story += [p("Estimated daily spend", "h2")]
        rows = [[p("Item", "cell_bold"), p("Approx. cost", "cell_bold")]]
        rows += [[p(b.get("item"), "cell"), p(b.get("cost"), "cell")] for b in pr["daily_budget"]]
        story.append(grid(rows, [CONTENT_W - 50 * mm, 50 * mm]))
    for key, title in (("before_you_go", "Before you go"), ("packing", "Pack this"), ("etiquette", "Local etiquette"), ("safety", "Stay safe")):
        if pr.get(key):
            story += [p(title, "h2")] + bullets(pr[key])
    if pr.get("emergency"):
        story += [p("Emergency", "h2"), p(pr["emergency"])]

    story += [Spacer(1, 4 * mm), p("Sources", "h2")]
    for s in it["sources"]:
        if isinstance(s, dict):
            story.append(rich(f"{escape(s.get('title', ''))}<br/><font color='#5B6676'>{escape(s.get('url', ''))}</font>", "small"))
        else:
            story.append(p(s, "small"))
        story.append(Spacer(1, 1.5 * mm))
    story += [Spacer(1, 4 * mm),
              p(f"Researched on {date.today():%d %b %Y}. Event times, prices and opening hours change, so confirm bookings before you go.", "small")]
    return story


def page_decor(req):
    def draw(canvas, doc):
        if doc.page == 1:
            canvas.saveState()
            canvas.setFillColor(ACCENT)
            canvas.rect(0, PAGE_H - 14 * mm, PAGE_W, 14 * mm, stroke=0, fill=1)
            canvas.restoreState()
            return
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.line(MARGIN, PAGE_H - 12 * mm, PAGE_W - MARGIN, PAGE_H - 12 * mm)
        canvas.setFont(FONT, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, PAGE_H - 10 * mm, f"{req['destination']}  ·  {req['traveler_name']}'s plan")
        canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    folder = Path(sys.argv[1])
    req = json.loads((folder / "request.normalized.json").read_text(encoding="utf-8"))
    it = json.loads((folder / "itinerary.json").read_text(encoding="utf-8"))

    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{req['trip_slug']}_travel_plan.pdf"

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"{req['destination']} travel plan", author="Personalized Trip Planner")
    story = (cover(req, it) + at_a_glance(req, it) + events(it) + logistics(req, it)
             + day_pages(it) + food(it) + goals(it) + practical(it))
    decor = page_decor(req)
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    print(out_path)


if __name__ == "__main__":
    main()
