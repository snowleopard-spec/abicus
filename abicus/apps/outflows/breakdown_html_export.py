"""
breakdown_html_export.py
========================

Build a fully self-contained HTML export of the Monthly Breakdown page.

Unlike html_export.py's spending snapshot (which loads plotly.js from a
CDN), this file inlines *everything* — Plotly and Tabulator from the
pinned copies in `vendor/`, the shell + outflows + breakdown CSS, the
live page's own breakdown.js, and the full transactions table as JSON —
so the export works offline, forever, and makes zero network requests.
Google Fonts links are deliberately omitted; font stacks fall back.

The trick that keeps this in sync with the live page: the export embeds
breakdown.js *verbatim*, preceded by a shim that replaces the `api`
global. The shim answers the two endpoints breakdown.js calls
(`/api/outflows/breakdown` and `/api/outflows/breakdown/transactions`)
from the embedded data, so month chips, clickable bars, and the
filter/sort/search transactions box all behave exactly as on the live
page. Every month is embedded — the reader can flick between months at
will.

Public API:
    build_breakdown_html() -> str
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from abicus.apps.outflows import db

_APP_DIR = Path(__file__).parent
_SHELL_CSS_DIR = _APP_DIR.parents[1] / "shell" / "static" / "css"
_VENDOR_DIR = _APP_DIR / "vendor"

_PLOTLY_JS = _VENDOR_DIR / "plotly-2.35.2.min.js"
_TABULATOR_JS = _VENDOR_DIR / "tabulator-6.3.1.min.js"
_TABULATOR_CSS = _VENDOR_DIR / "tabulator_simple-6.3.1.min.css"


def _script_safe(text: str) -> str:
    """Make arbitrary JS/JSON safe to inline inside a <script> element.
    `</script` inside a JS string literal becomes `<\\/script`, which
    evaluates identically; `</` in JSON strings likewise."""
    return text.replace("</", "<\\/")


# Mirrors the content block of templates/breakdown.html (minus the export
# buttons, which have no meaning inside an export). If the live template's
# skeleton changes, update this copy to match.
_BODY_SKELETON = """
<div id="breakdown-status" class="caption" style="margin-top:0;">Loading…</div>
<div id="breakdown-empty" class="banner banner-info hidden">
  The database was empty when this file was exported.
</div>
<div id="breakdown-error" class="banner banner-error hidden"></div>

<div id="breakdown-controls" class="breakdown-controls hidden">
  <div class="month-picker">
    <span class="month-picker-label">Months:</span>
    <div id="month-chips" class="month-chips"></div>
    <label class="exclude-toggle" title="Exclude Rent, Education, Holidays and Exceptional from totals and hide their tiles">
      <input type="checkbox" id="exclude-heavy">
      <span class="exclude-toggle-track"><span class="exclude-toggle-thumb"></span></span>
      <span class="exclude-toggle-text">Excl. Rent · Education · Holidays · Exceptional</span>
    </label>
  </div>
</div>

<div id="breakdown-grid" class="breakdown-grid hidden"></div>

<section id="breakdown-detail" class="card hidden">
  <div class="breakdown-detail-header">
    <h2 id="breakdown-detail-title">Transactions</h2>
    <button type="button" id="breakdown-detail-close" class="unsuppress-btn"
            title="Close" aria-label="Close the transactions box">×</button>
  </div>
  <div class="table-filters">
    <label>
      Category
      <select id="bd-filter-category"></select>
    </label>
    <label>
      Account
      <select id="bd-filter-account"></select>
    </label>
    <label>
      Search
      <input type="search" id="bd-filter-search" placeholder="Filter descriptions…" autocomplete="off">
    </label>
  </div>
  <div id="breakdown-detail-caption" class="caption"></div>
  <div id="breakdown-detail-table"></div>
</section>
"""

# Replaces the api.js global. Answers the two GETs breakdown.js makes from
# the embedded data; the transactions branch replicates the server's
# ORDER BY (date ASC, amount DESC, description ASC).
_API_SHIM = """
window.api = {
  async get(url) {
    const u = new URL(url, "http://export.local");
    const d = window.__ABICUS_EXPORT__;
    if (u.pathname === "/api/outflows/breakdown") return d.breakdown;
    if (u.pathname === "/api/outflows/breakdown/transactions") {
      const month = u.searchParams.get("month");
      const cat = u.searchParams.get("category");
      let rows = d.rows.filter((r) => r.date.slice(0, 7) === month);
      if (cat !== null) rows = rows.filter((r) => r.category === cat);
      rows.sort((a, b) =>
        a.date.localeCompare(b.date) ||
        (b.amount - a.amount) ||
        a.description.localeCompare(b.description));
      return { rows };
    }
    throw new Error(`Not available in this exported file: ${url}`);
  },
  async download() {
    alert("Downloads are not available in this exported file.");
  },
};
"""


def build_breakdown_html() -> str:
    rows = db.load_all_transactions()
    breakdown = db.load_monthly_breakdown()

    css = "\n".join(
        p.read_text()
        for p in [
            _TABULATOR_CSS,
            _SHELL_CSS_DIR / "tokens.css",
            _SHELL_CSS_DIR / "components.css",
            _APP_DIR / "static" / "outflows.css",
            _APP_DIR / "static" / "breakdown.css",
        ]
    )
    breakdown_js = (_APP_DIR / "static" / "breakdown.js").read_text()

    data_json = _script_safe(
        json.dumps({"breakdown": breakdown, "rows": rows}, separators=(",", ":"))
    )
    generated = datetime.now().strftime("%-d %b %Y, %H:%M")
    prices_through = rows[-1]["date"] if rows else "—"

    parts = [
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n",
        "<meta charset=\"utf-8\">\n",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n",
        "<title>Monthly Breakdown · Abicus export</title>\n",
        "<style>\n", css, "\n",
        # Export-only chrome: a simple header instead of the app shell.
        """
body { margin: 0; padding: 1.5rem 2rem 3rem; background: var(--bg-app, #FAF6EE); }
.export-header { display: flex; align-items: baseline; justify-content: space-between;
                 flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.25rem; }
.export-header h1 { margin: 0; font-size: 1.6rem; }
""",
        "</style>\n</head>\n",
        "<body data-active=\"outflows\">\n",
        "<div class=\"export-header\">\n",
        "  <h1>Monthly Breakdown</h1>\n",
        f"  <span class=\"caption\" style=\"margin:0;\">Exported {generated} · "
        f"{len(rows)} transactions · data through {prices_through}</span>\n",
        "</div>\n",
        _BODY_SKELETON,
        "<script>window.__ABICUS_EXPORT__ = ", data_json, ";</script>\n",
        "<script>\n", _script_safe(_PLOTLY_JS.read_text()), "\n</script>\n",
        "<script>\n", _script_safe(_TABULATOR_JS.read_text()), "\n</script>\n",
        "<script>\n", _API_SHIM, "\n</script>\n",
        "<script>\n", _script_safe(breakdown_js), "\n</script>\n",
        "</body>\n</html>\n",
    ]
    return "".join(parts)
