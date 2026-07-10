"""
html_export.py
===============

Build a self-contained HTML snapshot of a spending review:
- Title from an editable JSON template
- Month chip row that filters both the chart and the transaction table
- Plotly bar chart (interactive, loads plotly.js from CDN)
- Account and Category dropdowns
- HTML table of transactions
- Footer with generation timestamp

The chart is rendered client-side from the embedded row data so it stays
in sync with the chips and dropdowns. Plotly.js loads from a CDN — the
table and filters work fully offline; only the chart needs the CDN.

Public API:
    build_html(df, start_date, end_date) -> str
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .categorise import UNCATEGORISED


# Lighter earthy palette — kept in sync with breakdown.js / outflows.js /
# pdf_export.py. Rust reserved for Uncategorised so it stands out.
_PALETTE = [
    "#B49F7A", "#95B54F", "#B49877", "#8AA88A", "#BFA294",
    "#A59988", "#BFA284", "#968878", "#C4AE94", "#8FA075",
    "#C4B08C", "#8FA8A0", "#A0B482", "#B8C594",
]
_UNCAT_COLOUR = "#C77B4F"

_TABLE_COLUMNS = ["date", "description", "amount", "category", "account"]

_CONFIG_PATH = Path(__file__).parent / "config" / "html_export.json"
_DEFAULT_TITLE_TEMPLATE = "Spending Snapshot, {start_date} – {end_date}"


def _format_sgd(x: float) -> str:
    return f"${x:,.2f}"


def _load_title_template() -> str:
    """Read title_template from apps/outflows/config/html_export.json. Falls
    back to the default template if the file is missing, unreadable, or has
    no usable value — so a bad edit never breaks exports."""
    try:
        with _CONFIG_PATH.open() as f:
            cfg = json.load(f)
        tmpl = cfg.get("title_template")
        if isinstance(tmpl, str) and tmpl.strip():
            return tmpl
    except (OSError, json.JSONDecodeError):
        pass
    return _DEFAULT_TITLE_TEMPLATE


def _render_title(template: str, start_date: date, end_date: date) -> str:
    fmt = "%d %b %Y"
    return (
        template
        .replace("{start_date}", start_date.strftime(fmt))
        .replace("{end_date}", end_date.strftime(fmt))
    )


def _serialise_table(df: pd.DataFrame) -> list[dict]:
    """Convert table rows to a JSON-friendly list of dicts.
    `month` is added so the client can group without re-parsing the date."""
    rows = []
    for _, row in df[_TABLE_COLUMNS].iterrows():
        date_iso = (
            row["date"].isoformat() if isinstance(row["date"], date)
            else str(row["date"])
        )
        rows.append({
            "date": date_iso,
            "month": date_iso[:7],  # YYYY-MM
            "description": str(row["description"]),
            "amount": float(row["amount"]),
            "category": str(row["category"]),
            "account": str(row["account"]),
        })
    return rows


def _months_from_rows(rows: list[dict]) -> list[str]:
    return sorted({r["month"] for r in rows})


def build_html(df: pd.DataFrame, start_date: date, end_date: date) -> str:
    """
    Build a self-contained HTML snapshot of the spending review.

    Args:
        df: DataFrame containing the transactions to render. Expected columns:
            date, description, amount, category, account.
        start_date, end_date: inclusive bounds shown in the (default) title.

    Returns:
        Complete HTML document as a string.
    """
    title_template = _load_title_template()
    title = _render_title(title_template, start_date, end_date)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_spend = df["amount"].sum()
    n_tx = len(df)

    table_data = _serialise_table(df)
    months = _months_from_rows(table_data)
    accounts = sorted(df["account"].unique().tolist())
    categories = sorted(df["category"].unique().tolist())

    # Embed data + filter options as JSON. The browser-side script drives
    # both the chart and the table off this. Escape </ and similar so a
    # description string can't break out of the <script> tag.
    data_json = (
        json.dumps({
            "rows": table_data,
            "months": months,
            "accounts": accounts,
            "categories": categories,
            "palette": _PALETTE,
            "uncatColour": _UNCAT_COLOUR,
            "uncatLabel": UNCATEGORISED,
        })
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    safe_title = html.escape(title)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{safe_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Source+Sans+Pro:wght@300;400;600&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
  body {{
    font-family: 'Source Sans Pro', sans-serif;
    color: #3D3229;
    background: #FAF7F2;
    margin: 0;
    padding: 2rem;
    max-width: 1100px;
    margin-left: auto;
    margin-right: auto;
  }}
  h1 {{
    font-family: 'Playfair Display', serif;
    color: #556B2F;
    font-weight: 600;
    font-size: 2rem;
    margin: 0 0 0.25rem 0;
    letter-spacing: -0.5px;
  }}
  .summary {{
    font-family: 'Playfair Display', serif;
    color: #3D3229;
    font-weight: 600;
    font-size: 2rem;
    letter-spacing: -0.5px;
    margin: 0 0 1.5rem 0;
  }}
  .month-picker {{
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 0.6rem 0.8rem;
    background: white;
    border: 1px solid #DED6C4;
    border-radius: 6px;
    margin: 1rem 0;
  }}
  .month-picker-label {{
    font-weight: 600;
    color: #6B5D4F;
    font-size: 0.85rem;
    margin-right: 0.3rem;
  }}
  .month-chip {{
    display: inline-flex;
    align-items: center;
    padding: 0.25rem 0.65rem;
    border: 1px solid #C4B8A8;
    border-radius: 999px;
    background: #FAF7F2;
    color: #6B5D4F;
    font-size: 0.85rem;
    cursor: pointer;
    user-select: none;
    transition: background 0.1s, color 0.1s, border-color 0.1s;
  }}
  .month-chip input {{ display: none; }}
  .month-chip.is-on {{
    background: #8B7355;
    border-color: #8B7355;
    color: white;
  }}
  .month-chip:hover {{ border-color: #6B5D4F; }}
  .month-chip.is-on:hover {{ background: #6B5D4F; border-color: #6B5D4F; }}
  #chart {{
    background: white;
    border: 1px solid #DED6C4;
    border-radius: 6px;
    padding: 0.5rem;
  }}
  .filters {{
    display: flex;
    gap: 1rem;
    margin: 1.5rem 0 1rem 0;
    align-items: center;
    flex-wrap: wrap;
  }}
  .filters label {{
    font-weight: 600;
    color: #3D3229;
    margin-right: 0.5rem;
  }}
  .filters select {{
    font-family: 'Source Sans Pro', sans-serif;
    font-size: 0.95rem;
    padding: 0.4rem 0.6rem;
    border: 1px solid #C4B8A8;
    border-radius: 4px;
    background: white;
    color: #3D3229;
    min-width: 180px;
  }}
  .row-count {{
    margin-left: auto;
    color: #6B5D4F;
    font-size: 0.9rem;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: white;
    font-size: 0.95rem;
  }}
  thead th {{
    background: #EDE7DF;
    color: #3D3229;
    text-align: left;
    padding: 0.6rem 0.8rem;
    font-weight: 600;
    border-bottom: 1px solid #C4B8A8;
  }}
  tbody td {{
    padding: 0.5rem 0.8rem;
    border-bottom: 1px solid #EDE7DF;
  }}
  tbody tr:hover {{
    background: #FAF7F2;
  }}
  td.amount {{
    text-align: right;
    font-variant-numeric: tabular-nums;
  }}
  .privacy {{
    background: #FFF4E0;
    border-left: 3px solid #C77B4F;
    padding: 0.6rem 0.9rem;
    margin: 1rem 0;
    font-size: 0.9rem;
    color: #6B5D4F;
  }}
  footer {{
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid #E0D5C4;
    color: #8B7355;
    font-size: 0.85rem;
  }}
</style>
</head>
<body>
  <h1>{safe_title}</h1>
  <div class="summary" id="summary">{n_tx} transactions, {_format_sgd(total_spend)} total</div>

  <div class="privacy">Contains real transaction data — review before sharing.</div>

  <div class="month-picker" id="month-picker">
    <span class="month-picker-label">Months:</span>
    <div id="month-chips" style="display:flex; flex-wrap:wrap; gap:0.4rem; flex:1;"></div>
  </div>

  <div id="chart"></div>

  <div class="filters">
    <div><label for="filter-account">Account</label><select id="filter-account"></select></div>
    <div><label for="filter-category">Category</label><select id="filter-category"></select></div>
    <div class="row-count" id="row-count"></div>
  </div>

  <table id="transactions">
    <thead>
      <tr>
        <th>Date</th>
        <th>Description</th>
        <th style="text-align:right">Amount</th>
        <th>Category</th>
        <th>Account</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

  <footer>Generated by Spending Review on {generated}</footer>

<script>
  const DATA = {data_json};
  const selectedMonths = new Set(DATA.months);

  function escapeHtml(s) {{
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }}
  function formatSGD(n) {{
    return '$' + n.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
  }}
  function monthLabel(iso) {{
    const [y, m] = iso.split('-');
    const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return names[parseInt(m, 10) - 1] + ' ' + y.slice(2);
  }}

  function populateSelect(id, values) {{
    const sel = document.getElementById(id);
    sel.innerHTML = '<option value="__ALL__">All</option>' +
      values.map(v => `<option value="${{escapeHtml(v)}}">${{escapeHtml(v)}}</option>`).join('');
  }}

  function renderChips() {{
    const wrap = document.getElementById('month-chips');
    wrap.innerHTML = '';
    for (const m of DATA.months) {{
      const label = document.createElement('label');
      label.className = 'month-chip is-on';
      label.innerHTML = `<input type="checkbox" checked data-month="${{m}}">${{monthLabel(m)}}`;
      label.querySelector('input').addEventListener('change', (e) => {{
        const mo = e.target.dataset.month;
        if (e.target.checked) {{
          selectedMonths.add(mo);
          label.classList.add('is-on');
        }} else {{
          selectedMonths.delete(mo);
          label.classList.remove('is-on');
        }}
        render();
      }});
      wrap.appendChild(label);
    }}
  }}

  function filteredRows() {{
    const acct = document.getElementById('filter-account').value;
    const cat = document.getElementById('filter-category').value;
    return DATA.rows.filter(r =>
      selectedMonths.has(r.month) &&
      (acct === '__ALL__' || r.account === acct) &&
      (cat === '__ALL__' || r.category === cat)
    );
  }}

  function renderChart(rows) {{
    const totals = {{}};
    const counts = {{}};
    for (const r of rows) {{
      totals[r.category] = (totals[r.category] || 0) + r.amount;
      counts[r.category] = (counts[r.category] || 0) + 1;
    }}
    const cats = Object.keys(totals).sort((a, b) => totals[b] - totals[a]);
    const colors = [];
    let paletteIdx = 0;
    for (const c of cats) {{
      if (c === DATA.uncatLabel) {{
        colors.push(DATA.uncatColour);
      }} else {{
        colors.push(DATA.palette[paletteIdx % DATA.palette.length]);
        paletteIdx++;
      }}
    }}
    const totalsK = cats.map(c => totals[c] / 1000);
    Plotly.react('chart', [{{
      type: 'bar',
      orientation: 'h',
      x: totalsK,
      y: cats,
      marker: {{ color: colors }},
      text: totalsK.map(v => `$${{v.toFixed(1)}}K`),
      textposition: 'outside',
      cliponaxis: false,
      customdata: cats.map(c => [formatSGD(totals[c]), counts[c]]),
      hovertemplate: '<b>%{{y}}</b><br>%{{customdata[0]}}<br>%{{customdata[1]}} transactions<extra></extra>',
    }}], {{
      height: Math.max(300, 40 * cats.length + 100),
      margin: {{ l: 160, r: 80, t: 20, b: 60 }},
      xaxis: {{
        title: 'Total spend ($K)',
        tickprefix: '$',
        tickformat: ',.1f',
        gridcolor: '#EEE',
        showgrid: true,
      }},
      yaxis: {{ autorange: 'reversed', ticksuffix: '   ' }},
      plot_bgcolor: 'white',
      paper_bgcolor: 'white',
      font: {{ family: 'Source Sans Pro, sans-serif' }},
    }}, {{ displayModeBar: false, responsive: true }});
  }}

  function renderTable(rows) {{
    const tbody = document.querySelector('#transactions tbody');
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${{escapeHtml(r.date)}}</td>
        <td>${{escapeHtml(r.description)}}</td>
        <td class="amount">${{formatSGD(r.amount)}}</td>
        <td>${{escapeHtml(r.category)}}</td>
        <td>${{escapeHtml(r.account)}}</td>
      </tr>
    `).join('');
    const total = rows.reduce((s, r) => s + r.amount, 0);
    document.getElementById('row-count').textContent =
      `${{rows.length}} of ${{DATA.rows.length}} rows · ${{formatSGD(total)}}`;
  }}

  function render() {{
    const rows = filteredRows();
    const total = rows.reduce((s, r) => s + r.amount, 0);
    document.getElementById('summary').textContent =
      `${{rows.length}} transactions, ${{formatSGD(total)}} total`;
    renderChart(rows);
    renderTable(rows);
  }}

  renderChips();
  populateSelect('filter-account', DATA.accounts);
  populateSelect('filter-category', DATA.categories);
  document.getElementById('filter-account').addEventListener('change', render);
  document.getElementById('filter-category').addEventListener('change', render);
  render();
</script>
</body>
</html>
"""
