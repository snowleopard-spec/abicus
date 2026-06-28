"""
html_export.py
===============

Build a self-contained HTML snapshot of a spending review:
- Title with date range
- Plotly bar chart (interactive, loads plotly.js from CDN)
- Account and Category dropdowns that filter the transaction table
- HTML table of transactions
- Footer with generation timestamp

The output is a single HTML file that works in any modern browser. The
chart needs internet access to load plotly.js; the table and filters work
fully offline.

Public API:
    build_html(df, start_date, end_date) -> str
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go

from .categorise import UNCATEGORISED


# Earthy palette — same as the Streamlit dashboard. Rust orange reserved
# for Uncategorised so it visually stands out.
_PALETTE = [
    "#8B7355", "#6B8E23", "#8B6F47", "#5C7A5C", "#A0826D",
    "#7B6F5C", "#9B7E5A", "#6B5D4F", "#A89070", "#5D6B4E",
]
_UNCAT_COLOUR = "#C77B4F"

_TABLE_COLUMNS = ["date", "description", "amount", "category", "account"]


def _format_sgd(x: float) -> str:
    return f"${x:,.2f}"


def _build_chart(df: pd.DataFrame) -> str:
    """Build the Plotly bar chart and return it as an HTML fragment."""
    cat_summary = (
        df.groupby("category", as_index=False)["amount"]
        .agg(total="sum", count="count")
        .sort_values("total", ascending=False)
        .reset_index(drop=True)
    )

    bar_colors = []
    palette_idx = 0
    for cat in cat_summary["category"]:
        if cat == UNCATEGORISED:
            bar_colors.append(_UNCAT_COLOUR)
        else:
            bar_colors.append(_PALETTE[palette_idx % len(_PALETTE)])
            palette_idx += 1

    # Display values in thousands ($K), rounded to 1dp. Hover shows the
    # underlying SGD amount so precision isn't lost.
    totals_k = cat_summary["total"] / 1000.0

    fig = go.Figure(
        go.Bar(
            x=totals_k,
            y=cat_summary["category"],
            orientation="h",
            marker_color=bar_colors,
            text=[f"${v:,.1f}K" for v in totals_k],
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "%{customdata[1]} transactions<extra></extra>"
            ),
            customdata=list(zip(
                [_format_sgd(v) for v in cat_summary["total"]],
                cat_summary["count"],
            )),
        )
    )
    fig.update_layout(
        height=max(300, 40 * len(cat_summary) + 100),
        # Wider left margin gives room for the longest category labels.
        # Right margin gives the outside bar labels room to render.
        # Bottom margin avoids the "Total spend" title overlapping ticks.
        margin=dict(l=160, r=80, t=20, b=60),
        xaxis_title="Total spend ($K)",
        # ticksuffix adds breathing room between category labels and bars.
        yaxis=dict(autorange="reversed", ticksuffix="   "),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Source Sans Pro, sans-serif"),
    )
    fig.update_xaxes(tickprefix="$", tickformat=",.1f", showgrid=True, gridcolor="#EEE")

    # full_html=False emits just the <div> + the script, no <html> wrapper.
    # include_plotlyjs="cdn" loads plotly.js from a CDN — keeps the file small.
    return fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="spending-chart")


def _serialise_table(df: pd.DataFrame) -> list[dict]:
    """Convert table rows to a JSON-friendly list of dicts."""
    rows = []
    for _, row in df[_TABLE_COLUMNS].iterrows():
        rows.append({
            "date": row["date"].isoformat() if isinstance(row["date"], date) else str(row["date"]),
            "description": str(row["description"]),
            "amount": float(row["amount"]),
            "category": str(row["category"]),
            "account": str(row["account"]),
        })
    return rows


def build_html(df: pd.DataFrame, start_date: date, end_date: date) -> str:
    """
    Build a self-contained HTML snapshot of the spending review.

    Args:
        df: DataFrame containing the transactions to render. Expected columns:
            date, description, amount, category, account.
        start_date, end_date: inclusive bounds shown in the title.

    Returns:
        Complete HTML document as a string.
    """
    fmt = "%d %b %Y"
    title = f"Spending Snapshot, {start_date.strftime(fmt)} – {end_date.strftime(fmt)}"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_spend = df["amount"].sum()
    n_tx = len(df)

    chart_html = _build_chart(df)
    table_data = _serialise_table(df)

    accounts = sorted(df["account"].unique().tolist())
    categories = sorted(df["category"].unique().tolist())

    # Embed data + filter options as JSON. The browser-side script reads these
    # and renders the table.
    # Escape </ and similar to prevent any description text from breaking out
    # of the surrounding <script> tag (a real XSS risk if a transaction
    # description ever contains the literal string '</script>').
    data_json = (
        json.dumps({
            "rows": table_data,
            "accounts": accounts,
            "categories": categories,
        })
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    # Use html.escape on the title to be defensive — date strings are safe
    # but it costs nothing.
    safe_title = html.escape(title)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{safe_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Source+Sans+Pro:wght@300;400;600&display=swap" rel="stylesheet">
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
  <div class="summary">{n_tx} transactions, {_format_sgd(total_spend)} total</div>

  <div class="privacy">Contains real transaction data — review before sharing.</div>

  {chart_html}

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

  function escapeHtml(s) {{
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }}

  function formatSGD(n) {{
    return '$' + n.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
  }}

  function populateSelect(id, values) {{
    const sel = document.getElementById(id);
    sel.innerHTML = '<option value="__ALL__">All</option>' +
      values.map(v => `<option value="${{escapeHtml(v)}}">${{escapeHtml(v)}}</option>`).join('');
  }}

  function render() {{
    const acct = document.getElementById('filter-account').value;
    const cat = document.getElementById('filter-category').value;
    const rows = DATA.rows.filter(r =>
      (acct === '__ALL__' || r.account === acct) &&
      (cat === '__ALL__' || r.category === cat)
    );
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

  populateSelect('filter-account', DATA.accounts);
  populateSelect('filter-category', DATA.categories);
  document.getElementById('filter-account').addEventListener('change', render);
  document.getElementById('filter-category').addEventListener('change', render);
  render();
</script>
</body>
</html>
"""
