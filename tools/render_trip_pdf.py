"""Render a validated itinerary into a compact personalized travel plan PDF with photos.

Usage:
    python tools/render_trip_pdf.py .tmp/<trip_slug>

Reads request.normalized.json and itinerary.json from that folder, plus photos.json if
fetch_trip_photos.py has run, and writes outputs/<trip_slug>_travel_plan.pdf. Run validate_itinerary.py first.

The PDF is built at the richest density that fits MAX_PAGES. If even the sparsest density doesn't fit, it prints
a WARNING and still writes the PDF, so unattended runs can deliver it. Missing photos are simply left out.
"""

import io
import json
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.flowables import BalancedColumns

ROOT = Path(__file__).resolve().parent.parent
MAX_PAGES = 7

# Tried in order until the PDF fits. photo_h is the day photo height in mm; photo_every shows photos on every
# Nth day (0 = no day photos). Activity, location, cost, how to get there and why it fits are always kept.
DENSITIES = [
    {"details": True, "tips": True, "photo_h": 42, "photo_every": 1},
    {"details": False, "tips": True, "photo_h": 34, "photo_every": 1},
    {"details": False, "tips": False, "photo_h": 28, "photo_every": 1},
    {"details": False, "tips": False, "photo_h": 28, "photo_every": 3},
    {"details": False, "tips": False, "photo_h": 0, "photo_every": 0},
    {"details": False, "tips": False, "photo_h": 0, "photo_every": 0, "run_in": True},  # same text, fewer lines
]

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
MARGIN = 13 * mm
FRAME_PADDING = 6  # points; SimpleDocTemplate's frame insets its content by this on each side
CONTENT_W = PAGE_W - 2 * MARGIN - 2 * FRAME_PADDING
TOP_MARGIN = 13 * mm
BOTTOM_MARGIN = 12 * mm
HERO_H_PHOTO = 66 * mm
HERO_H_PLAIN = 38 * mm
HERO_BAND = 25 * mm
PHOTO_GAP = 2 * mm
THUMB_W, THUMB_H = 25 * mm, 17 * mm


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
    "h1": ParagraphStyle("h1", fontName=FONT_BOLD, fontSize=13.5, leading=17, textColor=INK, spaceBefore=7, spaceAfter=3, keepWithNext=1),
    "h2": ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=10, leading=13, textColor=ACCENT, spaceBefore=5, spaceAfter=2, keepWithNext=1),
    "col_h": ParagraphStyle("col_h", fontName=FONT_BOLD, fontSize=9.5, leading=12, textColor=ACCENT, spaceBefore=4, spaceAfter=1),
    "h3": ParagraphStyle("h3", fontName=FONT_BOLD, fontSize=9.6, leading=12.5, textColor=INK),
    "body": ParagraphStyle("body", fontName=FONT, fontSize=9.1, leading=12.3, textColor=INK, spaceAfter=2),
    "small": ParagraphStyle("small", fontName=FONT, fontSize=7.8, leading=10.2, textColor=MUTED),
    "fine": ParagraphStyle("fine", fontName=FONT, fontSize=6.8, leading=8.8, textColor=MUTED),
    "why": ParagraphStyle("why", fontName=FONT_ITALIC, fontSize=8.5, leading=11, textColor=ACCENT),
    "label": ParagraphStyle("label", fontName=FONT_BOLD, fontSize=7.6, leading=10, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName=FONT, fontSize=8.5, leading=11, textColor=INK),
    "cell_bold": ParagraphStyle("cell_bold", fontName=FONT_BOLD, fontSize=8.5, leading=11, textColor=INK),
    "time": ParagraphStyle("time", fontName=FONT_BOLD, fontSize=7, leading=11, textColor=ACCENT),
    "badge": ParagraphStyle("badge", fontName=FONT_BOLD, fontSize=7.6, leading=9.5, textColor=colors.white, alignment=TA_CENTER),
}


def p(text, style="body"):
    return Paragraph(escape(str(text or "")), STYLES[style])


def rich(html, style="body"):
    """Paragraph from already-escaped markup."""
    return Paragraph(html, STYLES[style])


def kv(label, value):
    return rich(f"<b>{escape(label)}:</b> {escape(str(value))}", "cell")


def fmt_date(iso):
    return date.fromisoformat(iso).strftime("%a %d %b %Y")


def bullets(items, style="cell"):
    return [rich(f"•&nbsp;{escape(str(i))}", style) for i in items if i]


def link(url, text):
    """A clickable link, or plain text if the URL isn't a web address."""
    label = escape(str(text or url or ""))
    if not str(url or "").lower().startswith(("http://", "https://")):
        return label
    return f'<a href="{escape(url, {chr(34): "&quot;"})}" color="#0E7C86">{label}</a>'


def card(rows, bg, border, width=CONTENT_W):
    t = Table([[r] for r in rows], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
    ]))
    return t


def grid(data, col_widths, header=True):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), ACCENT_SOFT)]
    t.setStyle(TableStyle(style))
    return t


def draw_cover_fit(canvas, path, x, y, w, h):
    """Draw an image filling the box, cropping whatever overflows."""
    with Image.open(path) as img:
        iw, ih = img.size
    scale = max(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    clip = canvas.beginPath()
    clip.rect(x, y, w, h)
    canvas.clipPath(clip, stroke=0, fill=0)
    canvas.drawImage(path, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh)


class Photo(Flowable):
    """A photo cropped to a fixed box, with an optional caption strip along the bottom."""

    def __init__(self, path, width, height, caption=None):
        super().__init__()
        self.path, self.width, self.height, self.caption = path, width, height, caption

    def wrap(self, avail_w, avail_h):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        draw_cover_fit(c, self.path, 0, 0, self.width, self.height)
        if self.caption:
            c.setFillColor(colors.black)
            c.setFillAlpha(0.5)
            c.rect(0, 0, self.width, 5 * mm, stroke=0, fill=1)
            c.setFillAlpha(1)
            c.setFillColor(colors.white)
            c.setFont(FONT, 7.4)
            c.drawString(2 * mm, 1.5 * mm, fit_text(self.caption, FONT, 7.4, self.width - 4 * mm))
        c.restoreState()


def fit_text(text, font, size, width):
    """Shorten text with an ellipsis until it fits the width."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def caption_for(title):
    """'Fontainhas (quarter)' reads better as 'Fontainhas'."""
    return title.split(" (")[0].strip()


class PhotoLibrary:
    """The downloaded photos, plus a record of which ones this build used (for the credits)."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.used = {}
        self.manifest = {}
        path = self.folder / "photos.json"
        if path.exists():
            try:
                self.manifest = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                print("WARNING: photos.json is unreadable; rendering without photos.")

    def path(self, title):
        """The photo file for a title, or None if there isn't a good one. Marks it as used."""
        entry = self.manifest.get(title) if isinstance(title, str) else None
        if not entry:
            return None
        path = self.folder / "photos" / entry.get("file", "")
        if not path.is_file():
            return None
        self.used[title] = entry
        return str(path)

    def has(self, title):
        entry = self.manifest.get(title) if isinstance(title, str) else None
        return bool(entry) and (self.folder / "photos" / entry.get("file", "")).is_file()

    def flowable(self, title, width, height, caption=True):
        path = self.path(title)
        return Photo(path, width, height, caption_for(title) if caption else None) if path else None


def intro(req, it, hero_h):
    """Page 1: what's under the hero (the hero itself is drawn by page_decor)."""
    # The frame starts just below TOP_MARGIN, so push the first flowable clear of the hero.
    story = [Spacer(1, hero_h - TOP_MARGIN - FRAME_PADDING + 3 * mm),
             p(f"{req.get('group_detail', req['group_type']).capitalize()}  ·  {req['pace'].title()} pace  ·  "
               f"{req['budget_level'].title()} budget  ·  from {req['origin_city']}", "small"),
             Spacer(1, 1.5 * mm),
             p(it["summary"]),
             Spacer(1, 1 * mm),
             card([p("BUILT AROUND WHAT YOU LOVE", "label"), p(", ".join(req["what_they_like"]), "h3")],
                  ACCENT_SOFT, ACCENT)]
    if req.get("special_needs"):
        story += [Spacer(1, 1 * mm), kv("Planned around", req["special_needs"])]
    if it.get("goals_map"):
        story.append(p("How this trip delivers on your goals", "h1"))
        rows = []
        for g in it["goals_map"]:
            days = ", ".join(str(d) for d in g.get("days", []))
            rows.append([p(g.get("goal"), "cell_bold"), p(g.get("how"), "cell"),
                         p(f"Day {days}" if days else "", "small")])
        story.append(grid(rows, [46 * mm, CONTENT_W - 66 * mm, 20 * mm], header=False))
    return story


def events(it):
    story = [p("Events not to miss", "h1")]
    if not it["must_not_miss_events"]:
        story.append(p(it.get("no_events_note") or "No major events were found for your dates; the day plans focus on year-round highlights."))
        return story
    status_colors = {"confirmed": ACCENT, "tentative": WARM, "recurring": MUTED}
    for ev in it["must_not_miss_events"]:
        status = ev.get("status", "confirmed")
        when = ", ".join(fmt_date(d) for d in ev["dates"][:2])
        if len(ev["dates"]) > 2:
            when = f"{fmt_date(ev['dates'][0])} to {fmt_date(ev['dates'][-1])}"
        if ev.get("time"):
            when += f"  ·  {ev['time']}"
        badge = Table([[p(status.upper(), "badge")]], colWidths=[20 * mm])
        badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), status_colors.get(status, MUTED)),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        title = Table([[p(ev["name"], "h3"), badge]], colWidths=[CONTENT_W - 38 * mm, 22 * mm])
        title.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        rows = [title,
                rich(f"{escape(when)}  ·  {escape(ev['venue'])}  ·  {link(ev['source_url'], 'Source')}", "small"),
                rich(escape(ev["why_for_you"]), "why"),
                kv("Get there", ev["how_to_get_there"]), kv("Tickets", ev["tickets"])]
        if ev.get("tip"):
            rows.append(kv("Tip", ev["tip"]))
        story += [KeepTogether(card(rows, WARM_SOFT, WARM)), Spacer(1, 2 * mm)]
    return story


def logistics(req, it):
    story = [p("Getting there & around", "h1")]
    gt = it["getting_there"]
    if gt.get("overview"):
        story.append(p(gt["overview"]))
    if gt.get("options"):
        rows = [[p(h, "cell_bold") for h in (f"From {req['origin_city']}", "Details", "Time", "Approx. cost")]]
        for o in gt["options"]:
            rows.append([p(o.get("mode"), "cell_bold"), p(o.get("details"), "cell"),
                         p(o.get("duration"), "cell"), p(o.get("cost"), "cell")])
        story.append(grid(rows, [30 * mm, CONTENT_W - 88 * mm, 28 * mm, 30 * mm]))

    ga = it["getting_around"]
    story.append(Spacer(1, 1.5 * mm))
    if ga.get("overview"):
        story.append(p(ga["overview"]))
    story += bullets(ga.get("tips", []))

    if it["where_to_stay"]:
        story.append(p("Where to stay", "h1"))
        rows = [[p(h, "cell_bold") for h in ("Area", "Why it suits you", "Price / night")]]
        for s in it["where_to_stay"]:
            area = escape(s.get("area", ""))
            if s.get("example"):
                area += f"<br/><font size=7.4 color='#5B6676'>e.g. {escape(s['example'])}</font>"
            rows.append([rich(area, "cell_bold"), p(s.get("why"), "cell"), p(s.get("price_range"), "cell")])
        story.append(grid(rows, [48 * mm, CONTENT_W - 76 * mm, 28 * mm]))
    return story


def photo_strip(day, library, height):
    """Up to two day photos side by side. With one photo, the day's summary sits beside it."""
    half = (CONTENT_W - PHOTO_GAP) / 2
    photos = [t for t in (day.get("photos") or []) if library.has(t)][:2]
    if not photos:
        return None, False
    cells = [library.flowable(t, half, height * mm) for t in photos]
    used_summary = False
    if len(cells) == 1:
        used_summary = bool(day.get("summary"))
        cells.append(p(day["summary"]) if used_summary else "")
    strip = Table([cells], colWidths=[half + PHOTO_GAP, half], rowHeights=[height * mm])
    strip.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return strip, used_summary


def block_row(block, density):
    meta = "  ·  ".join(x for x in (block["location"], block.get("duration"), block.get("cost")) if x)
    if density.get("run_in"):
        content = [rich(f"<b>{escape(block['activity'])}</b> <font size=7.8 color='#5B6676'>{escape(meta)}</font>", "cell"),
                   rich(f"<b>Get there:</b> {escape(block['how_to_get_there'])} "
                        f"<font color='#0E7C86'><i>{escape(block['why_for_you'])}</i></font>", "cell")]
    else:
        content = [p(block["activity"], "cell_bold"), p(meta, "small")]
        if density["details"] and block.get("details"):
            content.append(p(block["details"], "cell"))
        content += [kv("Get there", block["how_to_get_there"]), rich(escape(block["why_for_you"]), "why")]
        if density["tips"] and block.get("tip"):
            content.append(kv("Tip", block["tip"]))
    t = Table([[p(block["time_of_day"].upper(), "time"), content]], colWidths=[19 * mm, CONTENT_W - 19 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def day_sections(it, library, density):
    story = [p("Your day-by-day plan", "h1")]
    order = {"morning": 0, "afternoon": 1, "evening": 2}
    for i, day in enumerate(it["days"], 1):
        header = Table([[p(f"DAY {i}", "badge"), p(f"{fmt_date(day['date'])}  ·  {day['theme']}", "h3")]],
                       colWidths=[15 * mm, CONTENT_W - 15 * mm])
        header.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), ACCENT), ("BACKGROUND", (1, 0), (1, 0), ACCENT_SOFT),
                                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (1, 0), (1, 0), 7),
                                    ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
        lead = [header, Spacer(1, 1.2 * mm)]

        strip, summary_used = None, False
        if density["photo_every"] and (i - 1) % density["photo_every"] == 0:
            strip, summary_used = photo_strip(day, library, density["photo_h"])
        if strip:
            lead += [strip, Spacer(1, 1.2 * mm)]
        if day.get("summary") and not summary_used:
            lead.append(p(day["summary"], "cell"))

        blocks = sorted(day["blocks"], key=lambda b: order.get(b["time_of_day"].lower(), 3))
        rows = [block_row(b, density) for b in blocks]
        # Keep the header with the first activity; the remaining activities may flow onto the next page.
        story.append(KeepTogether(lead + rows[:1]))
        story += rows[1:]
        story.append(Spacer(1, 2.5 * mm))
    return story


def food(it, library):
    if not it["food"]:
        return []
    with_photos = any(library.has(f.get("photo")) for f in it["food"])
    rows = []
    for f in it["food"]:
        name = escape(f.get("name", ""))
        if f.get("area"):
            name += f"<br/><font size=7.4 color='#5B6676'>{escape(f['area'])}</font>"
        row = [rich(name, "cell_bold"), p(f.get("what_to_order"), "cell"), p(f.get("why_for_you"), "cell"),
               p(f.get("price"), "cell")]
        if with_photos:
            row.insert(0, library.flowable(f.get("photo"), THUMB_W, THUMB_H, caption=False) or "")
        rows.append(row)
    header = ["Place", "Order this", "Why you'll like it", "Per person"]
    widths = [38 * mm, 42 * mm, CONTENT_W - 104 * mm, 24 * mm]
    if with_photos:
        header.insert(0, "")
        widths = [THUMB_W + 3 * mm, 32 * mm, 34 * mm, CONTENT_W - (THUMB_W + 3 * mm + 90 * mm), 24 * mm]
    table = grid([[p(h, "cell_bold") for h in header]] + rows, widths)
    if with_photos:
        table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (0, -1), 0)]))
    return [p("Where & what to eat", "h1"), table]


def practical(it):
    pr = it["practical"]
    columns = []
    if pr.get("weather"):
        columns += [p("Weather", "col_h"), p(pr["weather"], "cell")]
    if pr.get("currency"):
        columns += [p("Money", "col_h"), p(pr["currency"], "cell")]
    if pr.get("daily_budget"):
        col_w = (CONTENT_W - 8 * mm) / 2
        rows = [[p(b.get("item"), "cell"), p(b.get("cost"), "cell")] for b in pr["daily_budget"]]
        columns += [p("Estimated daily spend", "col_h"), grid(rows, [col_w * 0.58, col_w * 0.42], header=False)]
    for key, title in (("before_you_go", "Before you go"), ("packing", "Pack this"),
                       ("etiquette", "Local etiquette"), ("safety", "Stay safe")):
        if pr.get(key):
            columns += [p(title, "col_h")] + bullets(pr[key])
    if pr.get("emergency"):
        columns += [p("Emergency", "col_h"), p(pr["emergency"], "cell")]
    story = [p("Practical info", "h1")]
    if columns:
        story.append(BalancedColumns(columns, nCols=2, needed=60, innerPadding=8, leftPadding=0, rightPadding=0,
                                     topPadding=0, bottomPadding=0))
    return story


def closing(it, library):
    parts = []
    for s in it["sources"]:
        if isinstance(s, dict):
            parts.append(link(s.get("url"), s.get("title") or s.get("url")))
        else:
            parts.append(link(s, s))
    story = [Spacer(1, 5 * mm), rich("<b>Sources:</b> " + "  ·  ".join(parts), "fine")]
    if library.used:
        credits = []
        for title, e in library.used.items():
            licence = link(e.get("licence_url"), e.get("licence")) if e.get("licence_url") else escape(e.get("licence", ""))
            credits.append(f"{link(e.get('source_url'), caption_for(title))}: {escape(e.get('author', ''))}, {licence}")
        story += [Spacer(1, 1 * mm), rich("<b>Photos (Wikimedia Commons):</b> " + "  ·  ".join(credits), "fine")]
    story += [Spacer(1, 1 * mm),
              p(f"Researched on {date.today():%d %b %Y}. Event times, prices and opening hours change, so confirm bookings before you go.", "fine")]
    return story


def page_decor(req, hero_path, hero_h):
    title = req["destination"]
    subtitle = f"{fmt_date(req['start_date'])} to {fmt_date(req['end_date'])}  ·  {req['num_days']} days  ·  Prepared for {req['traveler_name']}"

    def draw(canvas, doc):
        canvas.saveState()
        if doc.page == 1:
            y = PAGE_H - hero_h
            if hero_path:
                canvas.saveState()
                draw_cover_fit(canvas, hero_path, 0, y, PAGE_W, hero_h)
                canvas.restoreState()
                canvas.setFillColor(colors.black)
                canvas.setFillAlpha(0.52)
                canvas.rect(0, y, PAGE_W, HERO_BAND, stroke=0, fill=1)
                canvas.setFillAlpha(1)
            else:
                canvas.setFillColor(ACCENT)
                canvas.rect(0, y, PAGE_W, hero_h, stroke=0, fill=1)
            width = PAGE_W - 2 * MARGIN
            size = 26
            while pdfmetrics.stringWidth(title, FONT_BOLD, size) > width and size > 13:
                size -= 1
            canvas.setFillColor(colors.white)
            canvas.setFont(FONT, 8)
            canvas.drawString(MARGIN, y + HERO_BAND - 6 * mm, "PERSONAL TRAVEL PLAN")
            canvas.setFont(FONT_BOLD, size)
            canvas.drawString(MARGIN, y + 8.5 * mm, fit_text(title, FONT_BOLD, size, width))
            canvas.setFont(FONT, 9)
            canvas.drawString(MARGIN, y + 3.2 * mm, fit_text(subtitle, FONT, 9, width))
        else:
            canvas.setStrokeColor(RULE)
            canvas.line(MARGIN, PAGE_H - 10.5 * mm, PAGE_W - MARGIN, PAGE_H - 10.5 * mm)
            canvas.setFont(FONT, 7.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(MARGIN, PAGE_H - 9 * mm, f"{req['destination']}  ·  {req['traveler_name']}'s plan")
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(PAGE_W - MARGIN, 7 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def build(req, it, folder, density):
    """Build the PDF at this density; return (pdf bytes, page count)."""
    library = PhotoLibrary(folder)
    hero_path = library.path(it.get("cover_photo"))
    hero_h = HERO_H_PHOTO if hero_path else HERO_H_PLAIN
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=TOP_MARGIN, bottomMargin=BOTTOM_MARGIN,
                            title=f"{req['destination']} travel plan", author="Personalized Trip Planner")
    # closing() lists the photos used, so it must be built after everything that places photos.
    story = (intro(req, it, hero_h) + events(it) + logistics(req, it) + day_sections(it, library, density)
             + food(it, library) + practical(it))
    story += closing(it, library)
    decor = page_decor(req, hero_path, hero_h)
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return buffer.getvalue(), doc.page


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

    for level, density in enumerate(DENSITIES, 1):
        pdf, pages = build(req, it, folder, density)
        if pages <= MAX_PAGES:
            break
    if pages > MAX_PAGES:
        print(f"WARNING: {pages} pages even at the sparsest layout (target {MAX_PAGES}). Shorten the itinerary text.")
    out_path.write_bytes(pdf)
    print(f"pages={pages} density={level} size_kb={len(pdf) // 1024}")
    print(out_path)


if __name__ == "__main__":
    main()
