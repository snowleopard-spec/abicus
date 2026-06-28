"""Pure-logic helpers extracted from the original app.py.

The router imports from here so the request handlers stay thin and the
pipeline is straightforward to unit-test in isolation.
"""

from __future__ import annotations

import io
import json
import os
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from fastapi import UploadFile

from abicus.apps.assets.fx_rates import convert_to_usd
from abicus.apps.assets.parsers.broker_a import parse as parse_broker_a
from abicus.apps.assets.parsers.broker_c import parse as parse_broker_c
from abicus.apps.assets.parsers.manual import parse as parse_manual

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
SAVE_PATH = DATA_DIR / "last_compiled.parquet"
META_PATH = DATA_DIR / "last_compiled_meta.json"

PARSERS = {
    "broker_a": parse_broker_a,
    "broker_c": parse_broker_c,
    "manual": parse_manual,
}

PLOTLY_COLORS = [
    "#8B7355", "#B8860B", "#6B8E6B", "#A0522D", "#708090",
    "#CD853F", "#556B2F", "#8B6914", "#7B6B5A", "#9E7B5B",
]

DISPLAY_COLS = [
    "Asset Name", "Asset Class", "Broad Asset Class", "Currency",
    "Institution", "Account Type", "Jurisdiction", "Beneficiary",
    "Balance (Local)", "Balance (USD)", "US Situs Flag", "Tag",
]


# ----------------------------------------------------------------------
# Config loading
# ----------------------------------------------------------------------
def load_config() -> dict:
    with open(CONFIG_DIR / "sources.yaml") as f:
        sources_config = yaml.safe_load(f)

    mapping_asset_class = pd.read_csv(CONFIG_DIR / "mapping_asset_class.csv")
    mapping_us_situs = pd.read_csv(CONFIG_DIR / "mapping_us_situs.csv")
    mapping_broad_ac = pd.read_csv(CONFIG_DIR / "mapping_broad_asset_class.csv")
    asset_class_labels = pd.read_csv(CONFIG_DIR / "asset_class_labels.csv")

    lookthrough_path = CONFIG_DIR / "currency_lookthrough.csv"
    if lookthrough_path.exists():
        currency_lookthrough = pd.read_csv(lookthrough_path)
    else:
        currency_lookthrough = pd.DataFrame(columns=["Asset Name", "Currency", "Weight"])

    broad_ac_map = dict(
        zip(mapping_broad_ac["Asset Class"], mapping_broad_ac["Broad Asset Class"])
    )

    return {
        "sources_config": sources_config,
        "mapping_asset_class": mapping_asset_class,
        "mapping_us_situs": mapping_us_situs,
        "asset_class_labels": asset_class_labels,
        "currency_lookthrough": currency_lookthrough,
        "broad_ac_map": broad_ac_map,
    }


# ----------------------------------------------------------------------
# Allocation + lookthrough
# ----------------------------------------------------------------------
def apply_currency_lookthrough(data: pd.DataFrame, lookthrough_df: pd.DataFrame) -> pd.DataFrame:
    if lookthrough_df.empty:
        return data
    lookthrough_assets = lookthrough_df["Asset Name"].unique()
    mask = data["Asset Name"].isin(lookthrough_assets)
    passthrough = data[~mask].copy()
    to_explode = data[mask].copy()
    if to_explode.empty:
        return data
    exploded_rows = []
    for _, row in to_explode.iterrows():
        asset_lt = lookthrough_df[lookthrough_df["Asset Name"] == row["Asset Name"]]
        for _, lt_row in asset_lt.iterrows():
            new_row = row.copy()
            new_row["Currency"] = lt_row["Currency"]
            new_row["Balance (USD)"] = row["Balance (USD)"] * lt_row["Weight"]
            new_row["Balance (Local)"] = row["Balance (Local)"] * lt_row["Weight"]
            exploded_rows.append(new_row)
    if exploded_rows:
        return pd.concat([passthrough, pd.DataFrame(exploded_rows)], ignore_index=True)
    return passthrough


def get_chart_data(data: pd.DataFrame, attribute: str, value_col: str = "Balance (USD)") -> dict:
    if attribute not in data.columns or data[value_col].isna().all():
        return {"rows": [], "total": 0.0}
    grouped = data.groupby(attribute)[value_col].sum().reset_index()
    grouped = grouped.sort_values(value_col, ascending=False).reset_index(drop=True)
    total = float(grouped[value_col].sum())
    if total == 0:
        return {"rows": [], "total": 0.0}
    rows = [
        {
            "label": str(row[attribute]),
            "value": float(row[value_col]),
            "pct": float(row[value_col] / total * 100),
        }
        for _, row in grouped.iterrows()
    ]
    return {"rows": rows, "total": total}


def compute_all_allocations(master: pd.DataFrame, lookthrough_df: pd.DataFrame) -> dict:
    master_ccy_lt = apply_currency_lookthrough(master, lookthrough_df)
    cash_only = master[master["Asset Class"] == "Cash"] if "Asset Class" in master.columns else master.iloc[0:0]
    return {
        "broad_asset_class": get_chart_data(master, "Broad Asset Class"),
        "asset_class": get_chart_data(master, "Asset Class"),
        "currency": get_chart_data(master, "Currency"),
        "currency_lookthrough": get_chart_data(master_ccy_lt, "Currency"),
        "jurisdiction": get_chart_data(master, "Jurisdiction"),
        "institution": get_chart_data(master, "Institution"),
        "account_type": get_chart_data(master, "Account Type"),
        "us_situs": get_chart_data(master, "US Situs Flag"),
        "cash_by_institution": get_chart_data(cash_only, "Institution"),
    }


# ----------------------------------------------------------------------
# JSON helpers
# ----------------------------------------------------------------------
def df_to_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", default_handler=str))


def unmapped_summary(master: pd.DataFrame) -> dict:
    unmapped_ac_names = []
    unmapped_us_names = []
    if "Asset Class" in master.columns:
        unmapped_ac_names = sorted(master[master["Asset Class"] == "UNMAPPED"]["Asset Name"].unique().tolist())
    if "US Situs Flag" in master.columns:
        unmapped_us_names = sorted(master[master["US Situs Flag"] == "UNMAPPED"]["Asset Name"].unique().tolist())
    return {"asset_class": unmapped_ac_names, "us_situs": unmapped_us_names}


# ----------------------------------------------------------------------
# Compile pipeline
# ----------------------------------------------------------------------
async def upload_to_bytesio(upload: UploadFile) -> io.BytesIO:
    data = await upload.read()
    buf = io.BytesIO(data)
    buf.name = upload.filename or "upload.xlsx"
    return buf


def compile_master(
    file_buffers: list[tuple[str, io.BytesIO, str]],
    config: dict,
    rates: dict,
    fx_error: bool,
) -> dict:
    compile_log: list[str] = []
    compile_errors: list[str] = []
    price_errors: list[str] = []
    yfinance_error = False
    fetched_prices: dict = {}
    all_data: list[pd.DataFrame] = []

    for fname, buf, src_name in file_buffers:
        if src_name not in config["sources_config"]["sources"]:
            compile_errors.append(f"{fname}: Unknown source '{src_name}'.")
            continue
        src_cfg = config["sources_config"]["sources"][src_name]
        parser_name = src_cfg["parser"]
        if parser_name not in PARSERS:
            compile_errors.append(f"{fname}: Parser '{parser_name}' not implemented.")
            continue
        try:
            df = PARSERS[parser_name](buf, src_cfg, config["mapping_asset_class"], config["mapping_us_situs"])
            if df is None or len(df) == 0:
                compile_errors.append(f"{fname}: No data returned.")
                continue
            if hasattr(df, "attrs"):
                if df.attrs.get("yfinance_error"):
                    yfinance_error = True
                price_errors.extend(df.attrs.get("price_errors", []))
                fetched_prices.update(df.attrs.get("fetched_prices", {}))
            all_data.append(df)
            compile_log.append(f"{fname} -> {src_name} ({len(df)} items)")
        except Exception as e:
            compile_errors.append(f"{fname}: {e}\n\n{traceback.format_exc()}")

    master: Optional[pd.DataFrame] = None
    if all_data:
        master = pd.concat(all_data, ignore_index=True)
        if rates and not fx_error:
            master = convert_to_usd(master, rates)
        master["Broad Asset Class"] = master["Asset Class"].map(config["broad_ac_map"]).fillna("Other")

    return {
        "master": master,
        "compile_log": compile_log,
        "compile_errors": compile_errors,
        "price_errors": price_errors,
        "yfinance_error": yfinance_error,
        "fetched_prices": fetched_prices,
    }


def build_session_response(session_id: str, session: dict, config: dict, fx_error: bool) -> dict:
    master = session.get("master")
    if master is None or len(master) == 0:
        return {
            "session_id": session_id,
            "holdings": [],
            "total_usd": 0.0,
            "allocations": {},
            "compile_log": session.get("compile_log", []),
            "compile_errors": session.get("compile_errors", []),
            "price_errors": list(set(session.get("price_errors", []))),
            "yfinance_error": session.get("yfinance_error", False),
            "fetched_prices": session.get("fetched_prices", {}),
            "fx_rates": session.get("fx_rates", {}),
            "fx_error": fx_error,
            "unmapped": {"asset_class": [], "us_situs": []},
        }
    display = master.reindex(columns=DISPLAY_COLS)
    total_usd = (
        float(master["Balance (USD)"].sum())
        if "Balance (USD)" in master.columns and master["Balance (USD)"].notna().any()
        else 0.0
    )
    return {
        "session_id": session_id,
        "holdings": df_to_records(display),
        "total_usd": total_usd,
        "allocations": compute_all_allocations(master, config["currency_lookthrough"]),
        "compile_log": session.get("compile_log", []),
        "compile_errors": session.get("compile_errors", []),
        "price_errors": list(set(session.get("price_errors", []))),
        "yfinance_error": session.get("yfinance_error", False),
        "fetched_prices": session.get("fetched_prices", {}),
        "fx_rates": session.get("fx_rates", {}),
        "fx_error": fx_error,
        "unmapped": unmapped_summary(master),
    }


# ----------------------------------------------------------------------
# Save / load
# ----------------------------------------------------------------------
def save_compiled(df: pd.DataFrame, fx_rates: dict, stock_prices: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SAVE_PATH, index=False)
    meta = {"fx_rates": fx_rates or {}, "stock_prices": stock_prices or {}}
    with open(META_PATH, "w") as f:
        json.dump(meta, f)


def load_compiled() -> tuple[Optional[pd.DataFrame], Optional[dict], Optional[dict]]:
    if not SAVE_PATH.exists():
        return None, None, None
    df = pd.read_parquet(SAVE_PATH)
    saved_rates: Optional[dict] = None
    saved_prices: Optional[dict] = None
    if META_PATH.exists():
        with open(META_PATH) as f:
            meta = json.load(f)
        saved_rates = meta.get("fx_rates", {})
        saved_prices = meta.get("stock_prices", {})
    return df, saved_rates, saved_prices


def saved_meta() -> dict:
    if not SAVE_PATH.exists():
        return {"exists": False, "timestamp": None, "item_count": None}
    mtime = os.path.getmtime(SAVE_PATH)
    ts = datetime.fromtimestamp(mtime).strftime("%d %b %Y, %H:%M")
    try:
        n = len(pd.read_parquet(SAVE_PATH))
    except Exception:
        n = None
    return {"exists": True, "timestamp": ts, "item_count": n}


# ----------------------------------------------------------------------
# Unmapped append helper
# ----------------------------------------------------------------------
def append_unmapped_to_mappings(master: pd.DataFrame) -> dict:
    added_ac = added_us = 0
    for csv_path, flag_col, col_name in [
        (CONFIG_DIR / "mapping_asset_class.csv", "Asset Class", "Asset Class"),
        (CONFIG_DIR / "mapping_us_situs.csv", "US Situs Flag", "US Situs Flag"),
    ]:
        existing = pd.read_csv(csv_path)
        existing_names = existing["Underlying Instrument Description"].tolist()
        unmapped_names = master[master[flag_col] == "UNMAPPED"]["Asset Name"].unique()
        new_rows = [
            {"Underlying Instrument Description": n, col_name: ""}
            for n in unmapped_names if n not in existing_names
        ]
        if new_rows:
            pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True).to_csv(csv_path, index=False)
        if flag_col == "Asset Class":
            added_ac = len(new_rows)
        else:
            added_us = len(new_rows)
    return {"added_asset_class": added_ac, "added_us_situs": added_us}


# ----------------------------------------------------------------------
# PDF + Excel generation
# ----------------------------------------------------------------------
def fmt_k(value: float) -> str:
    return f"${value/1000:,.0f}k"


def generate_pdf(chart_configs, ref_rates, stock_prices, hide_balances=False) -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    margin = 25 * mm
    usable_w = w - 2 * margin
    olive = HexColor("#556B2F")
    brown = HexColor("#8B7355")
    dark = HexColor("#3D3229")
    muted = HexColor("#A09080")
    border_color = HexColor("#C4B8A8")

    y = h - margin
    c.setFont("Times-Bold", 22)
    c.setFillColor(olive)
    c.drawString(margin, y, f"Asset Allocation as of {date.today().strftime('%d %B %Y')}")
    y -= 14 * mm

    for label, chart in chart_configs:
        chart_rows = chart["rows"]
        total = chart["total"]
        if total == 0:
            continue
        block_height = 20 * mm + (len(chart_rows) + 2) * 5 * mm
        if y - block_height < margin + 40 * mm:
            c.showPage()
            y = h - margin
        c.setFont("Times-Bold", 13)
        c.setFillColor(dark)
        c.drawString(margin, y, label)
        y -= 7 * mm
        bar_h = 10 * mm
        x_pos = margin
        for i, row in enumerate(chart_rows):
            color = PLOTLY_COLORS[i % len(PLOTLY_COLORS)]
            pct = row["pct"]
            seg_w = (pct / 100) * usable_w
            c.setFillColor(HexColor(color))
            c.rect(x_pos, y - bar_h, seg_w, bar_h, fill=1, stroke=0)
            if pct >= 12:
                c.setFillColor(HexColor("#FFFFFF"))
                c.setFont("Helvetica", 7)
                txt = f"{row['label']}: {pct:.1f}%"
                if c.stringWidth(txt, "Helvetica", 7) < seg_w - 4:
                    c.drawString(x_pos + 3, y - bar_h + 3, txt)
            x_pos += seg_w
        y -= bar_h + 6 * mm
        col_cat = margin + 8 * mm
        col_bal = margin + usable_w * 0.7
        col_wt = margin + usable_w - 2 * mm
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(brown)
        c.drawString(col_cat, y, "Category")
        if not hide_balances:
            c.drawRightString(col_bal, y, "Balance (USD)")
        c.drawRightString(col_wt, y, "Weight")
        y -= 1.5 * mm
        c.setStrokeColor(border_color)
        c.setLineWidth(0.5)
        c.line(margin, y, margin + usable_w, y)
        y -= 4 * mm
        c.setFont("Helvetica", 8)
        for i, row in enumerate(chart_rows):
            color = PLOTLY_COLORS[i % len(PLOTLY_COLORS)]
            c.setFillColor(HexColor(color))
            c.rect(margin, y - 1, 4 * mm, 4 * mm, fill=1, stroke=0)
            c.setFillColor(dark)
            c.drawString(col_cat, y, row["label"])
            if not hide_balances:
                c.drawRightString(col_bal, y, fmt_k(row["value"]))
            c.drawRightString(col_wt, y, f"{row['pct']:.1f}%")
            y -= 4.5 * mm
        y -= 1.5 * mm
        c.setStrokeColor(border_color)
        c.line(margin, y + 3.5 * mm, margin + usable_w, y + 3.5 * mm)
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(brown)
        c.drawString(col_cat, y, "Total")
        if not hide_balances:
            c.drawRightString(col_bal, y, fmt_k(total))
        c.drawRightString(col_wt, y, "100.0%")
        y -= 9 * mm

    if y < margin + 50 * mm:
        c.showPage()
        y = h - margin
    y -= 2 * mm
    c.setStrokeColor(border_color)
    c.line(margin, y, margin + usable_w, y)
    y -= 7 * mm
    c.setFont("Times-Bold", 12)
    c.setFillColor(muted)
    c.drawString(margin, y, "Reference Data")
    y -= 8 * mm

    if ref_rates and len(ref_rates) > 1:
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(muted)
        c.drawString(margin, y, "FX Rates")
        y -= 5 * mm
        c.setStrokeColor(border_color)
        c.setLineWidth(0.5)
        ref_col1 = margin + 4 * mm
        ref_col2 = margin + 35 * mm
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(brown)
        c.drawString(ref_col1, y, "Pair")
        c.drawString(ref_col2, y, "Rate")
        y -= 1.5 * mm
        c.line(margin, y, margin + 60 * mm, y)
        y -= 4 * mm
        c.setFont("Helvetica", 8)
        for ccy in ["GBP", "EUR", "SGD", "AUD", "HKD", "JPY"]:
            if ccy in ref_rates:
                c.setFillColor(muted)
                c.drawString(ref_col1, y, f"{ccy}/USD")
                c.drawString(ref_col2, y, f"{1/ref_rates[ccy]:.4f}")
                y -= 4 * mm
        y -= 3 * mm

    if stock_prices:
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(muted)
        c.drawString(margin, y, "Stock Prices")
        y -= 5 * mm
        c.setStrokeColor(border_color)
        c.setLineWidth(0.5)
        ref_col1 = margin + 4 * mm
        ref_col2 = margin + 35 * mm
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(brown)
        c.drawString(ref_col1, y, "Ticker")
        c.drawString(ref_col2, y, "Price")
        y -= 1.5 * mm
        c.line(margin, y, margin + 60 * mm, y)
        y -= 4 * mm
        c.setFont("Helvetica", 8)
        for ticker, price in sorted(stock_prices.items()):
            c.setFillColor(muted)
            c.drawString(ref_col1, y, ticker)
            c.drawString(ref_col2, y, f"{price:,.4f}")
            y -= 4 * mm

    c.save()
    buf.seek(0)
    return buf.getvalue()


def generate_excel(df: pd.DataFrame, columns: list[str]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df[columns].to_excel(writer, sheet_name="Holdings", index=False)
        ws = writer.sheets["Holdings"]
        ws.freeze_panes = "A2"
        for col_idx, col_name in enumerate(columns, start=1):
            sample = df[col_name].astype(str).head(50)
            max_len = max([len(str(col_name))] + [len(v) for v in sample])
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 40)
    buf.seek(0)
    return buf.getvalue()
