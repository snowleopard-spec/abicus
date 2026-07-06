"""Server-side PDF renderer for the Monthly Breakdown page.

Draws the on-screen tile grid using ReportLab primitives so the output is
vector-crisp with selectable text. Colours match the on-screen palette
(see breakdown.js / outflows.js — keep in sync).
"""

from __future__ import annotations

import io
from datetime import date

# Kept in sync with breakdown.js / outflows.js.
PALETTE = [
    "#B49F7A", "#95B54F", "#B49877", "#8AA88A", "#BFA294",
    "#A59988", "#BFA284", "#968878", "#C4AE94", "#8FA075",
    "#C4B08C", "#8FA8A0", "#A0B482", "#B8C594",
]
TOTAL_COLOUR = "#8B7A6A"
UNCAT_COLOUR = "#C77B4F"
UNCAT = "Uncategorised"

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_label(iso: str) -> str:
    """'2026-01' → 'Jan 26'."""
    y, m = iso.split("-")
    return f"{_MONTH_NAMES[int(m) - 1]} {y[2:]}"


def _fmt_sgd(v: float) -> str:
    return f"S${v:,.0f}"


def _fmt_sgd_precise(v: float) -> str:
    return f"S${v:,.2f}"


def _truncate(canv, text: str, font: str, size: float, max_w: float) -> str:
    while canv.stringWidth(text, font, size) > max_w and len(text) > 1:
        text = text[:-1]
    return text


def render(data: dict) -> bytes:
    """Render the Monthly Breakdown as an A4 portrait PDF.

    data shape:
      {"months": [...], "by_category": {cat: {month: total}},
       "lifetime_totals": {cat: total}}  # cats already sorted desc
    """
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    margin = 14 * mm
    usable_w = w - 2 * margin

    olive = HexColor("#556B2F")
    dark = HexColor("#3D3229")
    muted = HexColor("#8A7F72")
    tile_border = HexColor("#DED6C4")
    tile_border_total = HexColor("#D6C9B0")
    tile_bg_total = HexColor("#FBF7EF")

    months = data.get("months", [])
    by_cat = data.get("by_category", {}) or {}
    lifetime = data.get("lifetime_totals", {}) or {}
    categories = list(lifetime.keys())

    # --- Page header ---
    def draw_page_header(page_num: int) -> float:
        c.setFont("Times-Bold", 18)
        c.setFillColor(olive)
        title = f"Monthly Breakdown as of {date.today().strftime('%d %B %Y')}"
        c.drawString(margin, h - margin - 6 * mm, title)
        if page_num > 1:
            c.setFont("Helvetica", 8)
            c.setFillColor(muted)
            c.drawRightString(w - margin, h - margin - 6 * mm, f"Page {page_num}")
        return h - margin - 11 * mm  # y for content top

    page_num = 1
    y = draw_page_header(page_num)

    if not months or not categories:
        c.setFont("Helvetica", 11)
        c.setFillColor(muted)
        c.drawString(margin, y - 6 * mm,
                     "No data to render — commit some transactions to the database first.")
        c.save()
        return buf.getvalue()

    # --- Monthly Total tile (full-width) ---
    monthly_totals = [
        sum(by_cat[cat].get(m, 0.0) for cat in categories)
        for m in months
    ]
    grand_total = sum(monthly_totals)

    total_tile_h = 12 * mm + len(months) * 7 * mm
    total_tile_h = max(total_tile_h, 45 * mm)
    total_tile_h = min(total_tile_h, 90 * mm)

    _draw_tile(
        c, margin, y, usable_w, total_tile_h,
        title=(f"Monthly total  ·  {len(months)} month"
               f"{'' if len(months) == 1 else 's'}  ·  "
               f"{len(categories)} categor"
               f"{'y' if len(categories) == 1 else 'ies'}"),
        header_total=grand_total,
        months=months,
        values=monthly_totals,
        colour=TOTAL_COLOUR,
        bg=tile_bg_total,
        border=tile_border_total,
        header_font_size=11,
        title_font_size=11,
        month_font_size=8,
        value_font_size=8,
    )
    y -= total_tile_h + 4 * mm

    # --- Category tiles: 3-column grid ---
    tiles_per_row = 3
    tile_gap = 3 * mm
    tile_w = (usable_w - (tiles_per_row - 1) * tile_gap) / tiles_per_row
    # Fixed per-tile height across the whole PDF (all tiles have the same
    # number of month bars, so heights are naturally identical).
    tile_h = 10 * mm + len(months) * 5.2 * mm
    tile_h = max(tile_h, 34 * mm)
    tile_h = min(tile_h, 130 * mm)

    palette_idx = 0
    for i in range(0, len(categories), tiles_per_row):
        row_cats = categories[i:i + tiles_per_row]
        # Page-break if this row won't fit.
        if y - tile_h < margin:
            c.showPage()
            page_num += 1
            y = draw_page_header(page_num)
        for j, cat in enumerate(row_cats):
            x = margin + j * (tile_w + tile_gap)
            if cat == UNCAT:
                colour = UNCAT_COLOUR
            else:
                colour = PALETTE[palette_idx % len(PALETTE)]
                palette_idx += 1
            values = [by_cat[cat].get(m, 0.0) for m in months]
            _draw_tile(
                c, x, y, tile_w, tile_h,
                title=cat,
                header_total=lifetime.get(cat, sum(values)),
                months=months,
                values=values,
                colour=colour,
            )
        y -= tile_h + 3 * mm

    c.save()
    return buf.getvalue()


def _draw_tile(
    c,
    x: float,
    y_top: float,
    w: float,
    h: float,
    *,
    title: str,
    header_total: float,
    months: list,
    values: list,
    colour: str,
    bg=None,
    border=None,
    header_font_size: float = 9.0,
    title_font_size: float = 9.5,
    month_font_size: float = 7.0,
    value_font_size: float = 6.8,
) -> None:
    """Draw a single tile at top-left (x, y_top) filling w × h.

    Mirrors the on-screen tile: title on the top-left, total on the top-right,
    horizontal bar chart underneath with month labels on the left of each bar
    and value labels to the right of each bar.
    """
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm

    dark = HexColor("#3D3229")
    muted = HexColor("#8A7F72")
    axis = HexColor("#E5DFD3")

    # --- Tile background/border ---
    if bg is not None:
        c.setFillColor(bg)
    else:
        c.setFillColor(HexColor("#FFFFFF"))
    if border is not None:
        c.setStrokeColor(border)
    else:
        c.setStrokeColor(HexColor("#DED6C4"))
    c.setLineWidth(0.5)
    c.rect(x, y_top - h, w, h, fill=1, stroke=1)

    # --- Header: title (left) + total (right) ---
    header_y = y_top - 5.5 * mm
    total_str = _fmt_sgd(header_total)
    c.setFont("Helvetica-Bold", header_font_size)
    total_w = c.stringWidth(total_str, "Helvetica-Bold", header_font_size)

    c.setFont("Helvetica-Bold", title_font_size)
    c.setFillColor(dark)
    max_title_w = w - total_w - 8 * mm
    title = _truncate(c, title, "Helvetica-Bold", title_font_size, max_title_w)
    c.drawString(x + 3 * mm, header_y, title)

    c.setFont("Helvetica-Bold", header_font_size)
    c.setFillColor(muted)
    c.drawRightString(x + w - 3 * mm, header_y, total_str)

    # --- Chart area ---
    n = len(months)
    if n == 0:
        return

    chart_top = header_y - 3.5 * mm
    chart_bottom = (y_top - h) + 3 * mm
    chart_h = chart_top - chart_bottom
    if chart_h <= 0:
        return

    # Column widths inside the chart:
    #  [ month label | bars area (with value labels at end) ]
    # Narrower label col for portrait tiles so the bar has more room.
    label_col_w = 10 * mm if w < 90 * mm else 13 * mm
    right_pad = 2 * mm
    bar_area_x = x + 3 * mm + label_col_w
    bar_area_w = (x + w - right_pad) - bar_area_x

    # Reserve room for value labels ("$1,234") to the right of the bar.
    max_val = max(values) if values else 0
    value_label_w = c.stringWidth(_fmt_sgd(max_val or 1), "Helvetica", value_font_size) + 2 * mm
    max_bar_w = max(0.0, bar_area_w - value_label_w)

    row_h = chart_h / n
    bar_h = min(row_h * 0.72, 4.5 * mm)

    # Subtle vertical axis line
    c.setStrokeColor(axis)
    c.setLineWidth(0.4)
    c.line(bar_area_x, chart_top, bar_area_x, chart_bottom)

    for i, (m, v) in enumerate(zip(months, values)):
        row_center_y = chart_top - (i + 0.5) * row_h
        bar_bottom = row_center_y - bar_h / 2

        # Month label (left)
        c.setFont("Helvetica", month_font_size)
        c.setFillColor(dark)
        c.drawRightString(
            bar_area_x - 1.5 * mm,
            row_center_y - month_font_size * 0.35,
            _month_label(m),
        )

        # Bar
        bar_w = (v / max_val) * max_bar_w if max_val > 0 else 0
        c.setFillColor(HexColor(colour))
        c.rect(bar_area_x, bar_bottom, bar_w, bar_h, fill=1, stroke=0)

        # Value label (right of bar) — omit for $0 to reduce clutter.
        if v > 0:
            c.setFont("Helvetica", value_font_size)
            c.setFillColor(dark)
            c.drawString(
                bar_area_x + bar_w + 1 * mm,
                row_center_y - value_font_size * 0.35,
                _fmt_sgd(v),
            )
