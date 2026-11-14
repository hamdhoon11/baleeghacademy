"""v0.8.48: one PDF builder for every report (monthly fees, payment report, teacher earnings, revenue, transfers, activity log, class
attendance and grades). Each report route hands it the SAME rows its screen, CSV and Excel use, so the four never disagree.

  build(title, blocks, academy=..., subtitle=..., logo=bytes|None, landscape=True) -> PDF bytes
  blocks: ("stats", [(label, value), ...])
          ("heading", text) / ("note", text)
          ("table", head, rows, {"widths": [relative...], "right": {col indexes}, "total": [row]})
          ("bars", title, labels, [(series name, values, hex color), ...], {"stacked": True, "money": True})   horizontal bars
          ("columns", title, labels, [(series name, values, hex color), ...], {"stacked": True})               vertical bars (months)
Text in Arabic or Thaana is drawn with the bundled font, shaped right to left (rtltext.py), as on receipts.
Chart colours: categorical slots 1 and 2 of the validated default palette (blue = collected, orange = still to pay), the same on screen.
"""
import datetime as dt
import io

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape as _land
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import receipts
import rtltext

INK, INK2, LAGOON, LINE, ZEBRA = colors.HexColor("#10262b"), colors.HexColor("#4a6468"), colors.HexColor("#0b4f5c"), colors.HexColor("#d3e2e2"), colors.HexColor("#f3f8f8")
BLUE, ORANGE = "#2a78d6", "#eb6834"
MAX_ROWS = 5000


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def para(v, size=8, bold=False, right=False, color=INK):
    s = "" if v is None else str(v)
    font = "Helvetica-Bold" if bold else "Helvetica"
    if rtltext.needs_unicode_font(s):
        font, s = receipts._unicode_font(bold), rtltext.visual(s)
    st = ParagraphStyle("c", fontName=font, fontSize=size, leading=size * 1.25, textColor=color, alignment=2 if right else 0, wordWrap="CJK" if len(s) > 60 and " " not in s else None)
    return Paragraph(_esc(s).replace("\n", "<br/>"), st)


def fmt(v):
    if isinstance(v, bool): return "yes" if v else "no"
    if isinstance(v, int): return f"{v:,}"
    if isinstance(v, float): return f"{v:,.2f}".rstrip("0").rstrip(".")
    return "" if v is None else str(v)


def _table(head, rows_, opts, width):
    rows_ = rows_[:MAX_ROWS]
    right = set(opts.get("right") or ())
    if not right and rows_:   # numbers line up on the right by themselves
        right = {i for i in range(len(head)) if all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows_ if i < len(r) and r[i] not in (None, ""))}
    data = [[para(h, 7.5, True, i in right, colors.white) for i, h in enumerate(head)]]
    for r in rows_:
        data.append([para(fmt(v), 7.5, False, i in right) for i, v in enumerate(r)])
    if opts.get("total"):
        data.append([para(fmt(v), 7.5, True, i in right) for i, v in enumerate(opts["total"])])
    w = opts.get("widths") or [1] * len(head)
    tw = sum(w)
    t = Table(data, colWidths=[width * x / tw for x in w], repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), LAGOON), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    for i in range(2, len(data), 2): st.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    if opts.get("total"): st += [("LINEABOVE", (0, -1), (-1, -1), 0.8, INK), ("BACKGROUND", (0, -1), (-1, -1), colors.white)]
    t.setStyle(TableStyle(st))
    return t


def _stats(items, width):
    n = max(1, min(6, len(items)))
    cells = [[para(fmt(v), 13, True, color=LAGOON) for _, v in items[i:i + n]] for i in range(0, len(items), n)]
    labels = [[para(k, 7.5, color=INK2) for k, _ in items[i:i + n]] for i in range(0, len(items), n)]
    data = []
    for a, b in zip(cells, labels):
        a += [""] * (n - len(a)); b += [""] * (n - len(b)); data += [a, b]
    t = Table(data, colWidths=[width / n] * n)
    st = [("LEFTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]
    for i in range(0, len(data), 2): st.append(("LINEABOVE", (0, i), (-1, i), 0.6, LINE))
    t.setStyle(TableStyle(st))
    return t


def _label(s, n=34):
    s = str(s or "")
    s = s if len(s) <= n else s[:n - 1] + "…"
    return rtltext.visual(s) if rtltext.needs_unicode_font(s) else s


def _legend(d, series, x, y):
    lg = Legend()
    lg.x, lg.y, lg.alignment, lg.columnMaximum, lg.fontName, lg.fontSize, lg.dx, lg.dy, lg.deltax = x - 95 * len(series), y, "right", 1, "Helvetica", 8, 8, 8, 95
    lg.colorNamePairs = [(colors.HexColor(c), n) for n, _, c in series]
    d.add(lg)


def _bars(title, labels, series, opts, width):
    """Horizontal bars, one row per label (batches). Stacked by default."""
    n = max(1, len(labels))
    h = 34 + n * 16
    d = Drawing(width, h + 26)
    d.add(String(0, h + 14, title, fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
    ch = HorizontalBarChart()
    ch.x, ch.y, ch.width, ch.height = 150, 22, width - 170, h - 30
    ch.data = [list(reversed([max(0, v or 0) for v in vals])) for _, vals, _ in series]
    ch.categoryAxis.categoryNames = list(reversed([_label(x) for x in labels]))
    ch.categoryAxis.labels.fontName, ch.categoryAxis.labels.fontSize, ch.categoryAxis.labels.boxAnchor, ch.categoryAxis.labels.dx = "Helvetica", 7.5, "e", -4
    ch.categoryAxis.strokeColor = LINE
    ch.valueAxis.valueMin = 0
    ch.valueAxis.labels.fontName, ch.valueAxis.labels.fontSize = "Helvetica", 7
    ch.valueAxis.strokeColor, ch.valueAxis.gridStrokeColor, ch.valueAxis.visibleGrid = LINE, LINE, 1
    ch.valueAxis.labelTextFormat = lambda v: f"{int(v):,}"
    ch.barWidth, ch.groupSpacing, ch.barSpacing = 10, 6, 0
    if opts.get("stacked", True): ch.categoryAxis.style = "stacked"
    for i, (_, _, c) in enumerate(series):
        ch.bars[i].fillColor, ch.bars[i].strokeColor, ch.bars[i].strokeWidth = colors.HexColor(c), colors.white, 1
    d.add(ch)
    if len(series) > 1: _legend(d, series, width, h + 12)
    return d


def _columns(title, labels, series, opts, width, height=170):
    d = Drawing(width, height + 26)
    d.add(String(0, height + 14, title, fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 50, 24, width - 70, height - 30
    ch.data = [[max(0, v or 0) for v in vals] for _, vals, _ in series]
    ch.categoryAxis.categoryNames = [_label(x, 12) for x in labels]
    ch.categoryAxis.labels.fontName, ch.categoryAxis.labels.fontSize, ch.categoryAxis.strokeColor = "Helvetica", 7.5, LINE
    ch.valueAxis.valueMin = 0
    ch.valueAxis.labels.fontName, ch.valueAxis.labels.fontSize = "Helvetica", 7
    ch.valueAxis.strokeColor, ch.valueAxis.gridStrokeColor, ch.valueAxis.visibleGrid = LINE, LINE, 1
    ch.valueAxis.labelTextFormat = lambda v: f"{int(v):,}"
    ch.groupSpacing, ch.barSpacing = 10, 0
    if opts.get("stacked", True): ch.categoryAxis.style = "stacked"
    for i, (_, _, c) in enumerate(series):
        ch.bars[i].fillColor, ch.bars[i].strokeColor, ch.bars[i].strokeWidth = colors.HexColor(c), colors.white, 1
    d.add(ch)
    if len(series) > 1: _legend(d, series, width, height + 12)
    return d


def build(title, blocks, academy="Baleegh Academy", subtitle="", logo=None, landscape=True, generated=None):
    buf = io.BytesIO()
    size = _land(A4) if landscape else A4
    m = 14 * mm
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=m, rightMargin=m, topMargin=m, bottomMargin=13 * mm,
                            title=receipts.latin(title), author=receipts.latin(academy), invariant=1)
    width = size[0] - 2 * m
    stamp = generated or dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).strftime("%d %b %Y, %H:%M")
    head_txt = [para(academy, 15, True, color=LAGOON), para(title, 11, True), para(subtitle, 8.5, color=INK2) if subtitle else ""]
    img = None
    if logo:
        try:
            ir = ImageReader(io.BytesIO(logo)); iw, ih = ir.getSize()
            hh = 16 * mm; img = Image(io.BytesIO(logo), width=hh * iw / ih if ih else hh, height=hh)
            if img.drawWidth > 45 * mm: img = Image(io.BytesIO(logo), width=45 * mm, height=45 * mm * ih / iw)
        except Exception:
            img = None
    head = Table([[img or "", head_txt]], colWidths=[(img.drawWidth + 4 * mm) if img else 0.1, width - ((img.drawWidth + 4 * mm) if img else 0.1)])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("LINEBELOW", (0, 0), (-1, 0), 1.2, LAGOON), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story = [head, Spacer(1, 8)]
    for b in blocks:
        k = b[0]
        if k == "stats": story += [_stats(b[1], width), Spacer(1, 8)]
        elif k == "heading":
            h = para(b[1], 10.5, True, color=LAGOON); h.keepWithNext = True
            sp = Spacer(1, 3); sp.keepWithNext = True
            story += [Spacer(1, 4), h, sp]
        elif k == "note": story += [para(b[1], 8, color=INK2), Spacer(1, 4)]
        elif k == "table":
            opts = b[3] if len(b) > 3 else {}
            if b[2]:
                story += [_table(b[1], b[2], opts, width), Spacer(1, 8)]
                if len(b[2]) > MAX_ROWS: story += [para(f"Only the first {MAX_ROWS:,} of {len(b[2]):,} rows are shown. Download Excel for all of them.", 8, color=INK2)]
            else: story += [para("Nothing to show.", 8.5, color=INK2), Spacer(1, 6)]
        elif k == "bars" and b[2]: story += [KeepTogether([_bars(b[1], b[2], b[3], b[4] if len(b) > 4 else {}, width)]), Spacer(1, 8)]
        elif k == "columns" and b[2]: story += [KeepTogether([_columns(b[1], b[2], b[3], b[4] if len(b) > 4 else {}, width)]), Spacer(1, 8)]

    def foot(c, d_):
        c.saveState(); c.setFont("Helvetica", 7.5); c.setFillColor(INK2)
        c.drawString(m, 8 * mm, receipts.latin(f"{academy} · {title}"))
        c.drawRightString(size[0] - m, 8 * mm, f"Generated {stamp} (Maldives time) · page {d_.page}")
        c.restoreState()
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()


def send(pdf, name):
    from flask import Response
    r = Response(pdf, mimetype="application/pdf")
    r.headers["Content-Disposition"] = f'attachment; filename="{name}.pdf"'
    r.headers["Cache-Control"] = "private, no-store"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r
